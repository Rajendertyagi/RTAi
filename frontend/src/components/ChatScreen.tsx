"use client";

import { ThreadPrimitive, SuggestionPrimitive, AuiIf } from "@assistant-ui/react";
import { useRtaiAssistantState } from "@/hooks/useRtaiAssistantState";
import { useEffect, useRef, type RefObject } from "react";
import { Menu } from "lucide-react";


import { MessageItem } from "./Message";
import { Composer } from "./Composer";
import { StatusBar } from "./StatusBar";
import { SHARED_CONTENT_COLUMN } from "../lib/shellLayout";

export interface ChatScreenProps {
  drawerOpen: boolean;
  onMenuClick: () => void;
  menuButtonRef: RefObject<HTMLButtonElement | null>;
}

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

export function ChatScreen({
  drawerOpen,
  onMenuClick,
  menuButtonRef,
}: ChatScreenProps) {
  const scrollRef = useAutoScroll();
  // Transport-derived status indicator (not WebSocket connected)
  const status = useRtaiAssistantState((s) => s.status, "ready");
  const agentInfo = "OpenCode";

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      {/* Header */}
      <header className="flex h-12 shrink-0 items-center border-b border-interactive bg-surface-background px-4">
        <button
          type="button"
          ref={menuButtonRef}
          onClick={onMenuClick}
          aria-expanded={drawerOpen}
          aria-controls="app-sidebar"
          aria-label="Open navigation menu"
          className="md:hidden mr-2 flex items-center justify-center w-8 h-8 max-md:h-11 max-md:w-11 rounded-lg border border-border bg-transparent text-foreground cursor-pointer transition-colors hover:bg-interactive-hover"
        >
          <Menu className="w-4 h-4" />
        </button>
        <div className="flex items-center gap-2">
          <span className="text-lg font-medium text-foreground">RTAI</span>
          <span
            className={`h-2 w-2 rounded-full ${
              status === "running"
                ? "bg-status-warning animate-pulse"
                : status === "error"
                  ? "bg-status-error"
                  : status === "complete"
                    ? "bg-status-success"
                    : status === "cancelled"
                      ? "bg-muted-foreground"
                      : "bg-border"
            }`}
            aria-label={
              status === "running"
                ? "Running"
                : status === "error"
                  ? "Error"
                  : status === "complete"
                    ? "Complete"
                    : status === "cancelled"
                      ? "Cancelled"
                      : "Ready"
            }
          />
        </div>
        <div className="ml-auto flex items-center gap-2 text-sm text-muted-foreground">
          <span>{agentInfo}</span>
        </div>
      </header>

      {/* Main chat area */}
      <ThreadPrimitive.Root className="flex min-h-0 min-w-0 w-full flex-1 flex-col">
        <ThreadPrimitive.Viewport
          ref={scrollRef}
          className="flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto"
        >
          <AuiIf condition={(s) => s.thread.isEmpty}>
            <div
              className={`${SHARED_CONTENT_COLUMN} flex min-h-0 flex-1 flex-col items-center justify-center text-center py-8`}
            >
              <h1 className="text-2xl font-normal text-foreground">
                What are we working on?
              </h1>
              <p className="mt-2 text-sm text-muted-foreground">
                Start a conversation with the AI assistant
              </p>
              {/* Suggestion cards */}
              <div className="mt-6 grid w-full max-w-lg grid-cols-2 gap-2">
                <ThreadPrimitive.Suggestions>
                  {() => (
                    <SuggestionPrimitive.Trigger
                      send={false}
                      clearComposer={true}
                      className="flex flex-col items-start gap-1 rounded-xl border border-interactive bg-surface-elevated px-4 py-3 text-left transition-colors hover:bg-interactive-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-interactive-focus-ring"
                    >
                      <span className="font-medium text-sm text-foreground">
                        <SuggestionPrimitive.Title />
                      </span>
                      <span className="text-xs text-muted-foreground">
                        <SuggestionPrimitive.Description />
                      </span>
                    </SuggestionPrimitive.Trigger>
                  )}
                </ThreadPrimitive.Suggestions>
              </div>
            </div>
          </AuiIf>

          <div className={`${SHARED_CONTENT_COLUMN} min-w-0`}>
            <ThreadPrimitive.Messages>
              {({ message }) => <MessageItem message={message} />}
            </ThreadPrimitive.Messages>
          </div>

          <ThreadPrimitive.ViewportFooter
            className="sticky bottom-0 z-10 mt-auto w-full min-w-0 bg-background"
            data-testid="thread-viewport-footer"
          >
            <div className={`${SHARED_CONTENT_COLUMN} min-w-0`}>
              {/* Persistent status bar */}
              <StatusBar />

              {/* Composer card */}
              <Composer />
            </div>
          </ThreadPrimitive.ViewportFooter>
        </ThreadPrimitive.Viewport>
      </ThreadPrimitive.Root>
    </div>
  );
}
