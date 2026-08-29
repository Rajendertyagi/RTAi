"use client";

import {
  ThreadPrimitive,
  MessagePrimitive,
  ComposerPrimitive,
  AuiIf,
} from "@assistant-ui/react";
import { ArrowUp, StopCircle } from "lucide-react";
import { useAuiState, useAui } from "@assistant-ui/react";
import { useEffect, useRef } from "react";
import { useChatStore } from "../state/chatStore";
import { ToolCard } from "./ToolCard";
import { MarkdownTextPrimitive } from "@assistant-ui/react-markdown";

const messagePartsComponents = {
  Text: MarkdownTextPrimitive,
  tools: { Fallback: ToolCard },
} as const;

// Auto-scroll to bottom when new messages arrive
function useAutoScroll() {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;

    const observer = new MutationObserver(() => {
      // Only auto-scroll if user is near bottom
      const isNearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 200;
      if (isNearBottom) {
        el.scrollTop = el.scrollHeight;
      }
    });

    observer.observe(el, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, []);

  return scrollRef;
}

export function OpenChamberChat() {
  const aui = useAui();
  const scrollRef = useAutoScroll();
  const isRunning = useAuiState((s) => s.thread.isRunning);
  const isConnected = useChatStore((s) => s.connected);
  const agentInfo = useChatStore((s) => s.agentInfo);

  const handleCancel = () => {
    aui.thread().cancelRun();
  };

  return (
    <div className="app h-screen flex flex-col overflow-hidden">
      {/* Header */}
      <header className="app__header flex h-14 shrink-0 items-center border-b border-[var(--interactive-border)] bg-[var(--surface-background)] px-4">
        <div className="flex items-center gap-2">
          <span className="text-lg font-medium text-[var(--foreground)]">RTAI</span>
          <span
            className={`h-2 w-2 rounded-full ${isConnected ? "bg-[var(--status-success)]" : "bg-[var(--status-error)]"}`}
            aria-label={isConnected ? "Connected" : "Disconnected"}
          />
        </div>
        <div className="ml-auto flex items-center gap-2 text-sm text-[var(--muted-foreground)]">
          <span>{agentInfo || "Agent"}</span>
        </div>
      </header>

      {/* Main chat area */}
      <div className="app__main flex min-h-0 flex-1 overflow-hidden">
        <ThreadPrimitive.Root className="flex h-full flex-col">
          <ThreadPrimitive.Viewport
            ref={scrollRef}
            className="chat__messages flex-1 overflow-y-auto px-4 py-6"
          >
            <AuiIf condition={(s) => s.thread.isEmpty}>
              <div className="empty-state mx-auto max-w-md text-center">
                <h1 className="text-2xl font-normal text-[var(--foreground)]">
                  How can I help?
                </h1>
                <p className="mt-2 text-sm text-[var(--muted-foreground)]">
                  Start a conversation with the AI assistant
                </p>
              </div>
            </AuiIf>

            <ThreadPrimitive.Messages>
              {({ message }) => {
                if (message.role === "user") {
                  return (
                    <MessagePrimitive.Root className="msg-row user">
                      <div className="avatar avatar--user">U</div>
                      <div className="bubble bubble--user">
                        <MessagePrimitive.Parts />
                      </div>
                    </MessagePrimitive.Root>
                  );
                }

                return (
                  <MessagePrimitive.Root className="msg-row">
                    <div className="avatar avatar--ai">AI</div>
                    <div className="bubble bubble--assistant">
                      <MessagePrimitive.Parts components={messagePartsComponents} />
                    </div>
                  </MessagePrimitive.Root>
                );
              }}
            </ThreadPrimitive.Messages>
          </ThreadPrimitive.Viewport>

          {/* Persistent status bar */}
          <div className="status-bar--persistent">
            <span
              className={`status-dot ${isConnected ? "connected" : "disconnected"} ${isRunning ? "connecting" : ""}`}
            />
            <span className="agent-text">
              {isConnected ? "Ready" : "Disconnected"}
            </span>
            <span className="agent-text ml-auto">{agentInfo || "Agent"}</span>
            {isRunning && (
              <>
                <span className="dot-pulse">●</span>
                <button
                  type="button"
                  onClick={handleCancel}
                  className="ml-auto flex items-center gap-1 rounded-md px-2 py-1 text-sm hover:bg-[var(--interactive-hover)]"
                  aria-label="Stop generation"
                >
                  <StopCircle className="h-4 w-4" />
                  Stop
                </button>
              </>
            )}
          </div>

          {/* Composer card */}
          <ThreadPrimitive.ViewportFooter>
            <div className="composer-card">
              <ComposerPrimitive.Root>
                <div className="composer-body">
                  <ComposerPrimitive.Input
                    placeholder="Ask anything..."
                    className="composer__input flex-1 resize-none rounded-xl border border-[var(--interactive-border)] bg-[var(--surface-background)] px-4 py-2.5 text-sm outline-none transition-colors focus:border-[var(--interactive-border-focus)]"
                    rows={1}
                  />
                  <ComposerPrimitive.Send className="composer__submit flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[var(--primary)] text-[var(--primary-foreground)] transition-opacity hover:opacity-85 disabled:opacity-40">
                    {isRunning ? <StopCircle className="h-4 w-4" /> : <ArrowUp className="h-4 w-4" />}
                  </ComposerPrimitive.Send>
                </div>
                <div className="composer-footer">
                  <div className="footer-left"></div>
                  <div className="footer-right">
                    <div className="model-chip">
                      <span>{agentInfo || "Model"}</span>
                    </div>
                  </div>
                </div>
              </ComposerPrimitive.Root>
            </div>
          </ThreadPrimitive.ViewportFooter>
        </ThreadPrimitive.Root>
      </div>
    </div>
  );
}
