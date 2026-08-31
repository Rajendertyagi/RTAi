"use client";

import { useChatStore } from "../state/chatStore";

// Error-only bar. Connection state and the active agent label live in the
// header (ChatScreen), so this bar exists solely to surface the last
// normalized error (`lastError`). Returns null when there is no error so it
// occupies zero height and never competes with the header.
export function StatusBar() {
  const lastError = useChatStore((s) => s.lastError);

  if (!lastError) return null;

  return (
    <div
      className="flex h-8 shrink-0 items-center gap-2 border-t border-status-error/30 bg-status-error/5 px-4 text-xs text-status-error"
      role="alert"
      aria-live="polite"
    >
      <span className="truncate" title={lastError.message}>
        {lastError.message}
      </span>
    </div>
  );
}
