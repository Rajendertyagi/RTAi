"use client";

import {
  ComposerPrimitive,
  useAui,
} from "@assistant-ui/react";
import { ArrowUp, StopCircle } from "lucide-react";
import { useChatStore } from "../state/chatStore";

export function Composer() {
  const aui = useAui();
  const isRunning = useChatStore((s) => s.activeTurnId !== null);
  const agentInfo = useChatStore((s) => s.agentInfo);
  const handleCancel = () => aui.thread().cancelRun();

  return (
    <div className="border-t border-interactive pt-3 pb-[calc(0.75rem+env(safe-area-inset-bottom))] px-4 flex-shrink-0 bg-background">
      <ComposerPrimitive.Root>
        <div className="flex items-end gap-2">
          <ComposerPrimitive.Input
            placeholder="Ask anything..."
            className="flex-1 resize-none rounded-xl border border-interactive bg-surface-background px-4 py-2.5 text-sm outline-none transition-colors focus:border-interactive-focus-ring"
            rows={1}
          />
          {isRunning ? (
            <button
              type="button"
              onClick={handleCancel}
              aria-label="Stop generation"
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground transition-opacity hover:opacity-85"
            >
              <StopCircle className="h-4 w-4" />
            </button>
          ) : (
            <ComposerPrimitive.Send className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground transition-opacity hover:opacity-85 disabled:opacity-40">
              <ArrowUp className="h-4 w-4" />
            </ComposerPrimitive.Send>
          )}
        </div>
        <div className="flex items-center justify-between py-1.5 flex-wrap gap-1.5">
          <div className="flex-1" />
          <div>
            <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-primary/12 border border-primary/25 text-primary text-xs">
              <span>{agentInfo || "Model"}</span>
            </div>
          </div>
        </div>
      </ComposerPrimitive.Root>
    </div>
  );
}
