"use client";

import {
  ComposerPrimitive,
  useAui,
} from "@assistant-ui/react";
import { ArrowUp, Square } from "lucide-react";
import { useChatStore } from "../state/chatStore";
import { CapabilityControls } from "./CapabilitySelectors";

export function Composer() {
  const aui = useAui();
  // Show Stop as soon as a dispatch is in flight — whether the turn has
  // started streaming (activeTurnId) or we're still waiting for the backend
  // to acknowledge (promptRequestId or cancelPending). This avoids the
  // previous race where a hang before the user_message echo left the user
  // with no way to stop the request.
  const isRunning = useChatStore(
    (s) =>
      s.activeTurnId !== null ||
      s.promptRequestId !== null ||
      s.cancelPending,
  );
  const handleCancel = () => aui.thread().cancelRun();

  return (
    <div
      className="w-full min-w-0 overflow-visible rounded-xl border border-interactive bg-surface-elevated focus-within:ring-2 focus-within:ring-interactive-focus-ring"
      data-testid="composer"
    >
      <ComposerPrimitive.Root>
        <div className="flex items-end gap-2 p-3">
          <ComposerPrimitive.Input
            placeholder="Ask anything…"
            rows={1}
            onInput={(e) => {
              const el = e.currentTarget as HTMLTextAreaElement;
              el.style.height = "auto";
              el.style.height = `${Math.min(el.scrollHeight, 200)}px`;
            }}
            className="max-h-[200px] flex-1 resize-none overflow-y-auto border-0 bg-transparent px-1 py-1.5 text-sm text-foreground outline-none placeholder:text-muted-foreground"
            data-testid="composer-input"
          />
          {isRunning ? (
            <button
              type="button"
              onClick={handleCancel}
              aria-label="Stop generation"
              data-testid="composer-stop"
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-status-error text-status-error-foreground transition-opacity hover:opacity-85"
            >
              <Square className="h-4 w-4" fill="currentColor" />
            </button>
          ) : (
            <ComposerPrimitive.Send
              data-testid="composer-send"
              aria-label="Send message"
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground transition-opacity hover:opacity-85 disabled:cursor-not-allowed disabled:opacity-40"
            >
              <ArrowUp className="h-4 w-4" />
            </ComposerPrimitive.Send>
          )}
        </div>
        <div className="flex items-center justify-between gap-2 px-3 pb-2">
          {/* Runtime-only actions (attachment / command) render here only
              when the backend exposes a working interaction — no stubs. */}
          <CapabilityControls />
        </div>
      </ComposerPrimitive.Root>
    </div>
  );
}
