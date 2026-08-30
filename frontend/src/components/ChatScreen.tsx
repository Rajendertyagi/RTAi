"use client";

import { ThreadPrimitive, AuiIf } from "@assistant-ui/react";
import { useEffect, useRef } from "react";
import { useChatStore } from "../state/chatStore";
import { MessageItem } from "./Message";
import { Composer } from "./Composer";
import { StatusBar } from "./StatusBar";

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

export function ChatScreen() {
  const scrollRef = useAutoScroll();
  const isConnected = useChatStore((s) => s.connected);
  const agentInfo = useChatStore((s) => s.agentInfo);

  return (
    // `h-full` (not `h-screen`) fills the parent <main>, and we deliberately do
    // NOT reuse the top-level `.app` row class here ╬ô├ç├╢ that collision was part of
    // the earlier broken layout.
    <div className="h-full flex flex-col overflow-hidden">
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
              {({ message }) => <MessageItem message={message} />}
            </ThreadPrimitive.Messages>
          </ThreadPrimitive.Viewport>

          {/* Persistent status bar */}
          <StatusBar />

          {/* Composer card */}
          <Composer />
        </ThreadPrimitive.Root>
      </div>
    </div>
  );
}
