"use client";

import {
  AssistantRuntimeProvider,
  useExternalStoreRuntime,
  type ThreadMessageLike,
} from "@assistant-ui/react";
import { defineToolkit, Tools, AuiConfig } from "@assistant-ui/react";
import { useCallback, useEffect, useRef } from "react";
import { useChatStore } from "../state/chatStore";
import { useRtaiSocket } from "../hooks/useRtaiSocket";
import type { ClientCommand } from "../types/protocol";

// Tool UI registry — maps tool names to renderer components
// Runtime-discovered from backend; never hardcoded.
const toolRenderers: Record<string, React.FC<any>> = {};

/**
 * Register a custom renderer for a tool name.
 * Call this from your application code to bind tool names to React components.
 */
export function registerToolRenderer(toolName: string, component: React.FC<any>): void {
  toolRenderers[toolName] = component;
}

/**
 * Create a toolkit that includes registered tool renderers.
 */
export function createToolkit(): ReturnType<typeof defineToolkit> {
  const toolkit: Record<string, { type: "backend"; render: React.FC<any> }> = {};
  for (const [name, render] of Object.entries(toolRenderers)) {
    toolkit[name] = { type: "backend" as const, render };
  }
  return defineToolkit(toolkit);
}

// Minimal runtime provider that wires WebSocket events → assistant-ui store
export function RtaiRuntimeProvider({ children }: { children: React.ReactNode }) {
  // Subscribe to store
  const messages = useChatStore((s) => s.messages);
  const isRunning = useChatStore((s) => s.activeTurnId !== null);
  const sessionId = useChatStore((s) => s.sessionId);
  const turnId = useChatStore((s) => s.turnId);
  const setConnected = useChatStore((s) => s.setConnected);
  const handleMessage = useChatStore((s) => s.handleMessage);

  // WebSocket hook — declare before use in callbacks
  const socketRef = useRef<{ send: (cmd: ClientCommand) => void } | null>(null);
  const socket = useRtaiSocket((event) => {
    handleMessage(event);
    if (event.type === "status") {
      setConnected(event.state === "ready");
    }
  });

  // Store the send method for onNew/onCancel to use
  useEffect(() => {
    socketRef.current = { send: socket.send };
  }, [socket.send]);

  // Convert our backend message format to assistant-ui ThreadMessageLike
  const convertMessage = useCallback(
    (msg: (typeof messages)[0]): ThreadMessageLike => ({
      role: msg.role,
      id: msg.id,
      createdAt: new Date(msg.timestamp),
      content:
        msg.role === "user"
          ? [{ type: "text" as const, text: msg.text }]
          : [
              { type: "text" as const, text: msg.text },
              ...msg.tools.flatMap((tool) => [
                {
                  type: "tool-call" as const,
                  toolName: tool.title ?? tool.kind ?? "tool",
                  toolCallId: tool.id,
                  args: tool.rawInput ?? {},
                  status:
                    tool.status === "running"
                      ? { type: "running" as const }
                      : tool.status === "error"
                      ? { type: "incomplete" as const, reason: "error" as const }
                      : { type: "complete" as const },
                  result:
                    tool.status === "success"
                      ? tool.content?.map((c) => (c.type === "content" ? c.text : ""))[0]
                      : undefined,
                } as const,
              ]),
            ],
    }),
    [messages]
  );

  // Create the runtime
  const runtime = useExternalStoreRuntime({
    messages: messages.map(convertMessage),
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

      // Send through the socket (accessed via ref to avoid re-subscribing)
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
    onAddToolResult: (options) => {
      // Tool results come from backend events, not client-side
      // This is a no-op for our architecture
    },
  });

  // Connect on mount
  useEffect(() => {
    socket.connect();
    return () => socket.close();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Build config with toolkit
  const toolkit = createToolkit();
  const config = AuiConfig({ tools: Tools({ toolkit }) });

  return (
    <AssistantRuntimeProvider runtime={runtime} config={config}>
      {children}
    </AssistantRuntimeProvider>
  );
}
