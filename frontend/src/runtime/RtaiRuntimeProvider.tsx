"use client";

import {
  AssistantRuntimeProvider,
  useExternalStoreRuntime,
  type ThreadMessageLike,
} from "@assistant-ui/react";
import { useCallback, useEffect, useRef, type ReactNode } from "react";
import { useChatStore, type ChatMessage } from "../state/chatStore";
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

  // WebSocket hook — declared before use in the runtime callbacks below.
  const socketRef = useRef<{ send: (cmd: ClientCommand) => void } | null>(null);
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

      // Generate IDs for this turn
      const newSessionId = `${sessionId}-turn-${Date.now()}`;
      const newTurnId = `turn-${Date.now()}`;
      const newMessageId = `msg-${Date.now()}`;

      // Update store with new IDs
      useChatStore.setState({
        sessionId: newSessionId,
        turnId: newTurnId,
      });

      // Send prompt via socket
      const command: ClientCommand = {
        protocol_version: 1,
        request_id: newMessageId,
        type: "prompt",
        session_id: newSessionId,
        turn_id: newTurnId,
        message_id: newMessageId,
        text: text,
      };

      socketRef.current?.send(command);
    },
    onCancel: async () => {
      const command: ClientCommand = {
        protocol_version: 1,
        request_id: `cancel-${Date.now()}`,
        type: "cancel",
        session_id: sessionId,
        turn_id: turnId,
      };
      socketRef.current?.send(command);
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
    <AssistantRuntimeProvider runtime={runtime}>
      {children}
    </AssistantRuntimeProvider>
  );
}
