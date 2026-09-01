"use client";

import {
  AssistantRuntimeProvider,
  useExternalStoreRuntime,
  AuiConfig,
  Suggestions,
} from "@assistant-ui/react";
import { useEffect, useRef, type ReactNode } from "react";
import { useChatStore, generateId, type ChatMessage } from "../state/chatStore";
import { useRtaiSocket } from "../hooks/useRtaiSocket";
import type { ClientCommand } from "../types/protocol";
import { WELCOME_SUGGESTIONS } from "../data/welcomeSuggestions";

// Minimal runtime provider that wires WebSocket events → assistant-ui store.
//
// Tool rendering is NOT registered here: our backend sends arbitrary runtime
// tool names (discovered via tool_start), so a fixed name→renderer map
// (defineToolkit) cannot cover them. Instead the UI passes a single fallback
// renderer via <MessagePrimitive.Parts components={{ tools: { Fallback } }} />,
// which handles every tool call that has no dedicated UI.

const RTAI_CONFIG = AuiConfig({
  suggestions: Suggestions(WELCOME_SUGGESTIONS),
});

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

  // Create the runtime.
  // T is inferred as ChatMessage from the messages selector.
  // setMessages receives readonly ChatMessage[] per the ExternalStoreAdapter
  // contract — no cast needed.
  const runtime = useExternalStoreRuntime({
    messages,
    setMessages: (msgs) => {
      useChatStore.getState().setMessages(msgs);
    },
    isRunning,
    onNew: async (message) => {
      // Only user-authored messages are sent as prompts. This also narrows
      // AppendMessage's role-discriminated content to ThreadUserMessagePart[].
      if (message.role !== "user") return;
      const text =
        message.content[0]?.type === "text" ? message.content[0].text : "";
      if (!text.trim()) return;

      // Capture snapshot BEFORE any mutation for rollback on send failure.
      const currentMessages = useChatStore.getState().messages;

      // Identity contract: the conversation session_id is stable across every
      // turn in one chat. Each prompt gets its own distinct turn_id,
      // message_id and request_id — none is derived from or embedded in the
      // session id, and request_id is never reused as message_id.
      const newTurnId = generateId();
      const newMessageId = generateId();
      const newRequestId = generateId();
      const asstMsgId = `asst-${newTurnId}`;

      // Build optimistic messages. User content and attachments are preserved
      // verbatim from the AppendMessage so the attachment pipeline is intact.
      const userMsg: ChatMessage = {
        role: "user",
        id: newMessageId,
        content: message.content,
        attachments: message.attachments,
        createdAt: new Date(),
      };
      const asstMsg: ChatMessage = {
        role: "assistant",
        id: asstMsgId,
        content: [],
        status: { type: "running" },
        createdAt: new Date(),
      };

      // Optimistic state update: append both messages, set turn identities.
      useChatStore.setState({
        turnId: newTurnId,
        messageId: newMessageId,
        promptRequestId: newRequestId,
        cancelRequestId: null,
        cancelPending: false,
        cancelError: null,
        pendingSelections: new Map(),
        lastError: null,
        messages: [...currentMessages, userMsg, asstMsg],
        activeTurnId: newTurnId,
        activeMessageId: asstMsgId,
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
      // store stuck in a pending prompt: restore the exact snapshot and surface
      // an honest error.
      const sent = socketRef.current?.send(command) ?? false;
      if (!sent) {
        // Restore exact pre-mutation snapshot — removes both optimistic messages.
        // Clear correlations for this turn (none should exist yet, but defensive).
        const nextCorr = new Map(useChatStore.getState().partCorrelations);
        const turnPrefix = `${newTurnId}:`;
        for (const key of nextCorr.keys()) {
          if (key.startsWith(turnPrefix)) nextCorr.delete(key);
        }

        useChatStore.setState({
          messages: currentMessages,
          turnId: "",
          messageId: "",
          promptRequestId: null,
          activeTurnId: null,
          activeMessageId: null,
          cancelRequestId: null,
          cancelPending: false,
          cancelError: null,
          partCorrelations: nextCorr,
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
    <AssistantRuntimeProvider runtime={runtime} config={RTAI_CONFIG}>
      {children}
    </AssistantRuntimeProvider>
  );
}
