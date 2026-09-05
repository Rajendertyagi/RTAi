"use client";

import { useRtaiAssistantState } from "@/hooks/useRtaiAssistantState";


// Error-only bar sourced from official AssistantTransport state.
// No longer references any legacy store or WebSocket status.
export function StatusBar() {
  const status = useRtaiAssistantState((s) => s.status, "ready");
  const error = useRtaiAssistantState((s) => s.error, undefined);

  if (status !== "error" || !error) return null;

  return (
    <div
      className="flex h-8 shrink-0 items-center gap-2 border-t border-status-error/30 bg-status-error/5 px-4 text-xs text-status-error"
      role="alert"
      aria-live="polite"
    >
      <span className="truncate" title={error}>
        {error}
      </span>
    </div>
  );
}
