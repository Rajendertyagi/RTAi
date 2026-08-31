"use client";

import {
  AssistantRuntimeProvider,
  useExternalStoreRuntime,
  type ThreadMessageLike,
  AuiConfig,
  Suggestions,
} from "@assistant-ui/react";
import { useCallback, useEffect, useRef, type ReactNode } from "react";
import { useChatStore, generateId, type ChatMessage } from "../state/chatStore";
import { useRtaiSocket } from "../hooks/useRtaiSocket";
import type { ClientCommand, ToolContentBlock } from "../types/protocol";

// Minimal runtime provider that wires WebSocket events → assistant-ui store.
//
// Tool rendering is NOT registered here: our backend sends arbitrary runtime
// tool names (discovered via tool_start), so a fixed name→renderer map
// (defineToolkit) cannot cover them. Instead the UI passes a single fallback
// renderer via <MessagePrimitive.Parts components={{ tools: { Fallback } }} />,
// which handles every tool call that has no dedicated UI.
export function RtaiRuntimeProvider({ children }: { children: ReactNode }) {
  // Subscribe to store
  const messages = useChatStore((s) => s.messages);
  const isRunning = useChatStore((s) => s.activeTurnId !== null);
  const sessionId = useChatStore((s) => s.sessionId);
  const turnId = useChatStore((s) => s.turnId);
  const setConnected = useChatStore((s) => s.setConnected);
  const handleMessage = useChatStore((s) => s.handleMessage);
  const registerSend = useChatStore((s) => s.registerSend);

  // WebSocket hook — declared before use in the runtime callbacks below.
  const socketRef = useRef<{ send: (cmd: ClientCommand) => boolean } | null>(null);
  const socket = useRtaiSocket((event) => {
    handleMessage(event);
    if (event.type === "status") {
      setConnected(event.state === "ready");
    }
  });

  // Expose send() to the runtime callbacks without re-creating the runtime.
  useEffect(() => {
    socketRef.current = { send: socket.send };
  }, [socket.send]);

  // Register the socket's send with the chat store so selection actions
  // (select_agent / select_model / select_mode / set_thinking) can dispatch
  // through the established transport boundary. The store never holds the
  // WebSocket directly.
  useEffect(() => {
    registerSend(socket.send);
  }, [registerSend, socket.send]);

  // Convert our backend message format to assistant-ui ThreadMessageLike.
  // The adapter calls this; we pass raw messages + this converter (not
  // pre-converted messages), which is what ExternalStoreAdapter requires.
  const convertMessage = useCallback(
    (msg: ChatMessage): ThreadMessageLike => ({
      role: msg.role,
      id: msg.id,
      createdAt: new Date(msg.timestamp),
      content:
        msg.role === "user"
          ? [{ type: "text" as const, text: msg.text }]
          : [
              { type: "text" as const, text: msg.text },
              ...msg.tools.map((tool) => ({
                type: "tool-call" as const,
                toolName: tool.title ?? tool.kind ?? "tool",
                toolCallId: tool.id,
                args: tool.rawInput ?? {},
                // Literal types on the values only — a whole-object `as const`
                // would make every property readonly and stop matching the
                // mutable part types assistant-ui expects.
                status:
                  tool.status === "running"
                    ? { type: "running" as const }
                    : tool.status === "error"
                      ? { type: "incomplete" as const, reason: "error" as const }
                      : { type: "complete" as const },
                result:
                  tool.status === "success"
                    ? tool.content?.map((c: ToolContentBlock) =>
                        c.type === "content" ? c.text : "",
                      )[0]
                    : undefined,
              })),
            ],
    }),
    [],
  );

  // Create the runtime
  const runtime = useExternalStoreRuntime({
    messages,
    convertMessage,
    isRunning,
    onNew: async (message) => {
      const text =
        message.content[0]?.type === "text" ? message.content[0].text : "";
      if (!text.trim()) return;

      // Identity contract: the conversation session_id is stable across every
      // turn in one chat. Each prompt gets its own distinct turn_id,
      // message_id and request_id — none is derived from or embedded in the
      // session id, and request_id is never reused as message_id.
      const newTurnId = generateId();
      const newMessageId = generateId();
      const newRequestId = generateId();

      // Update store with the new turn's identities. The session id is NOT
      // changed here — it stays stable for the whole conversation. In-flight
      // selection requests from the previous turn are stale and cleared here
      // (correlation rule: clear pending on new turn).
      useChatStore.setState({
        turnId: newTurnId,
        messageId: newMessageId,
        promptRequestId: newRequestId,
        cancelRequestId: null,
        cancelPending: false,
        cancelError: null,
        pendingSelections: new Map(),
        lastError: null,
      });

      // Send prompt via socket
      const command: ClientCommand = {
        protocol_version: 1,
        request_id: newRequestId,
        type: "prompt",
        session_id: sessionId,
        turn_id: newTurnId,
        message_id: newMessageId,
        text: text,
      };

      // Dispatch failure (socket unavailable/disconnected) must not leave the
      // store stuck in a pending prompt: clear the turn state and surface an
      // honest error instead of silently dropping the send.
      const sent = socketRef.current?.send(command) ?? false;
      if (!sent) {
        useChatStore.setState({
          turnId: "",
          messageId: "",
          promptRequestId: null,
          cancelRequestId: null,
          cancelPending: false,
          cancelError: null,
          activeTurnId: null,
          activeMessageId: null,
          lastError: {
            code: "send_failed",
            message: "Could not send prompt: connection unavailable",
          },
        });
      }
    },
    onCancel: async () => {
      // Each cancel is a distinct protocol command with its own request_id.
      // It reuses the target prompt's stable session_id and active turn_id,
      // never the prompt's request_id.
      const cancelRequestId = generateId();
      useChatStore.setState({
        cancelRequestId,
        cancelPending: true,
        cancelError: null,
      });
      const command: ClientCommand = {
        protocol_version: 1,
        request_id: cancelRequestId,
        type: "cancel",
        session_id: sessionId,
        turn_id: turnId,
      };
      // Dispatch failure must not leave cancelPending stuck: clear it and
      // surface an honest error while retaining the active prompt state.
      const sent = socketRef.current?.send(command) ?? false;
      if (!sent) {
        useChatStore.setState({
          cancelPending: false,
          cancelError: {
            code: "send_failed",
            message: "Could not send cancel: connection unavailable",
          },
        });
      }
    },
    onAddToolResult: () => {
      // Tool results arrive as backend events (tool_result), not client-side
      // handoff, so this is intentionally a no-op for our architecture.
    },
  });

  // Connect on mount
  useEffect(() => {
    socket.connect();
    return () => socket.close();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <AssistantRuntimeProvider
      runtime={runtime}
      config={AuiConfig({
        suggestions: Suggestions([
          {
            title: "Write a shell script",
            label: "Automation",
            prompt: "Write a shell script to automate backups",
          },
          {
            title: "Debug TypeScript",
            label: "Development",
            prompt: "Help me debug this TypeScript error",
          },
          {
            title: "Explain WebSocket",
            label: "Learning",
            prompt: "Explain how WebSocket works",
          },
        ]),
      })}
    >
      {children}
    </AssistantRuntimeProvider>
  );
}
