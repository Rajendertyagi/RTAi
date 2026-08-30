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
    <div className="h-full flex flex-col overflow-hidden">
      {/* Header */}
      <header className="flex h-14 shrink-0 items-center border-b border-interactive bg-surface-background px-4">
        <div className="flex items-center gap-2">
          <span className="text-lg font-medium text-foreground">RTAI</span>
          <span
            className={`h-2 w-2 rounded-full ${isConnected ? "bg-status-success" : "bg-status-error"}`}
            aria-label={isConnected ? "Connected" : "Disconnected"}
          />
        </div>
        <div className="ml-auto flex items-center gap-2 text-sm text-muted-foreground">
          <span>{agentInfo || "Agent"}</span>
        </div>
      </header>

      {/* Main chat area */}
      <div className="flex min-h-0 flex-1 overflow-hidden">
        <ThreadPrimitive.Root className="flex h-full min-h-0 flex-col">
          <ThreadPrimitive.Viewport
            ref={scrollRef}
            className="flex-1 min-h-0 overflow-y-auto px-4 py-6"
          >
            <AuiIf condition={(s) => s.thread.isEmpty}>
              <div className="mx-auto max-w-md text-center">
                <h1 className="text-2xl font-normal text-foreground">
                  How can I help?
                </h1>
                <p className="mt-2 text-sm text-muted-foreground">
                  Start a conversation with the AI assistant
                </p>
              </div>
            </AuiIf>

            <ThreadPrimitive.Messages>
              {({ message }) => <MessageItem message={message} />}
            </ThreadPrimitive.Messages>

            <ThreadPrimitive.ViewportFooter
              className="sticky bottom-0 z-5 flex flex-col bg-background"
              data-testid="thread-viewport-footer"
            >
              {/* Persistent status bar */}
              <StatusBar />

              {/* Composer card */}
              <Composer />
            </ThreadPrimitive.ViewportFooter>
          </ThreadPrimitive.Viewport>
        </ThreadPrimitive.Root>
      </div>
    </div>
  );
}
