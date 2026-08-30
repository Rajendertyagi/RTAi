"use client";

import {
  ComposerPrimitive,
  ThreadPrimitive,
  useAui,
  useAuiState,
} from "@assistant-ui/react";
import { ArrowUp, StopCircle } from "lucide-react";
import { useChatStore } from "../state/chatStore";

export function Composer() {
  const aui = useAui();
  const isRunning = useAuiState((s) => s.thread.isRunning);
  const agentInfo = useChatStore((s) => s.agentInfo);
  const handleCancel = () => aui.thread().cancelRun();

  return (
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
  );
}
