"use client";

import { useChatStore } from "../state/chatStore";

// Informational-only status bar. The Stop control now lives exclusively in
// the composer (composer-stop); this bar surfaces connection state, the
// active agent label, and the last normalized selection error.
export function StatusBar() {
  const isConnected = useChatStore((s) => s.connected);
  const isRunning = useChatStore((s) => s.activeTurnId !== null);
  const agentInfo = useChatStore((s) => s.agentInfo);
  const lastError = useChatStore((s) => s.lastError);

  return (
    <div className="flex h-8 shrink-0 items-center gap-2 border-t border-interactive bg-surface-background px-4 text-xs text-muted-foreground">
      <span
        className={`h-2 w-2 shrink-0 rounded-full ${isConnected ? "bg-status-success" : "bg-status-error"} ${isRunning ? "animate-[busy-pulse_1.2s_ease-in-out_infinite] bg-status-warning" : ""}`}
        aria-hidden="true"
      />
      <span className="text-xs text-muted-foreground">
        {isConnected ? "Ready" : "Disconnected"}
      </span>
      {lastError && (
        <span
          className="max-w-[40%] truncate text-status-error"
          title={lastError.message}
        >
          {lastError.message}
        </span>
      )}
      <span className="ml-auto text-xs text-muted-foreground">
        {agentInfo || "Agent"}
      </span>
    </div>
  );
}
