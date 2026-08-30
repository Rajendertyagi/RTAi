"use client";

import {
  ComposerPrimitive,
  useAui,
} from "@assistant-ui/react";
import { ArrowUp, StopCircle } from "lucide-react";
import { useChatStore } from "../state/chatStore";

export function Composer() {
  const aui = useAui();
  // Running state is sourced from our own store (activeTurnId). The backend
  // sets activeTurnId on user_message and clears it on done/cancelled, so this
  // flips reliably during a live stream. assistant-ui's external runtime does
  // not surface that back through thread.isRunning, which previously left the
  // Stop affordance permanently hidden.
  const isRunning = useChatStore((s) => s.activeTurnId !== null);
  const agentInfo = useChatStore((s) => s.agentInfo);
  const handleCancel = () => aui.thread().cancelRun();

  return (
    <div className="composer-card">
      <ComposerPrimitive.Root>
        <div className="composer-body">
          <ComposerPrimitive.Input
            placeholder="Ask anything..."
            className="composer__input flex-1 resize-none rounded-xl border border-[var(--interactive-border)] bg-[var(--surface-background)] px-4 py-2.5 text-sm outline-none transition-colors focus:border-[var(--interactive-border-focus)]"
            rows={1}
          />
          {isRunning ? (
            <button
              type="button"
              onClick={handleCancel}
              aria-label="Stop generation"
              className="composer__submit flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[var(--primary)] text-[var(--primary-foreground)] transition-opacity hover:opacity-85"
            >
              <StopCircle className="h-4 w-4" />
            </button>
          ) : (
            <ComposerPrimitive.Send className="composer__submit flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-[var(--primary)] text-[var(--primary-foreground)] transition-opacity hover:opacity-85 disabled:opacity-40">
              <ArrowUp className="h-4 w-4" />
            </ComposerPrimitive.Send>
          )}
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
  );
}
