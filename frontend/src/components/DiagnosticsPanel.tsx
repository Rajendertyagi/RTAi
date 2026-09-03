"use client";

import { useMemo, useState } from "react";
import { X } from "lucide-react";
import { useRtaiDiagnostics } from "@/hooks/useRtaiAssistantState";
import type { RtaiDiagnosticEvent } from "@/types/rtaiAssistantState";

const LEVELS = ["all", "debug", "info", "warn", "error"] as const;

const LEVEL_STYLES: Record<string, string> = {
  debug: "text-muted-foreground",
  info: "text-foreground",
  warn: "text-yellow-600",
  error: "text-destructive",
};

/**
 * RTAI-safe diagnostics page.
 *
 * It is a dedicated, full-surface panel reachable from the app shell. It stays
 * closed/not mounted until opened (returns null when `open` is false) and never
 * interferes with chat. It only displays the safe, ring-buffered events the
 * backend projects through the existing AssistantTransport external state — there
 * is no second store, no polling, and no separate diagnostics REST endpoint.
 *
 * Events are shown newest-first so the most recent lifecycle events are always
 * immediately visible without scrolling.
 */
export function DiagnosticsPanel({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  // Single source of truth: the safe diagnostics the backend projects through
  // the existing AssistantTransport external state (rtaiDiagnostics). Client events
  // arrive via the rtai.clientDiagnostic command and are recorded server-side with
  // origin:"client", so they are already present in this one stream - there is no
  // second client store and no merge at render time.
  const events = useRtaiDiagnostics();
  const [level, setLevel] = useState<string>("all");
  const [corr, setCorr] = useState("");

  const filtered = useMemo(() => {
    const list = events as RtaiDiagnosticEvent[];
    const matched = list.filter((e) => {
      if (level !== "all" && e.level !== level) return false;
      if (corr.trim()) {
        const hay = JSON.stringify(e).toLowerCase();
        if (!hay.includes(corr.trim().toLowerCase())) return false;
      }
      return true;
    });
    // Newest first.
    return [...matched].reverse();
  }, [events, level, corr]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-background">
      <header className="flex items-center justify-between border-b border-border px-4 py-3">
        <div className="flex items-baseline gap-2">
          <h2 className="text-sm font-semibold">Diagnostics</h2>
          <span className="text-xs text-muted-foreground">
            {filtered.length} event{filtered.length === 1 ? "" : "s"}
          </span>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close diagnostics"
          className="rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
        >
          <X className="size-4" />
        </button>
      </header>

      <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-2 text-xs">
        <div className="flex gap-1">
          {LEVELS.map((lv) => (
            <button
              key={lv}
              type="button"
              onClick={() => setLevel(lv)}
              className={
                "rounded px-2 py-0.5 " +
                (level === lv
                  ? "bg-accent text-accent-foreground"
                  : "text-muted-foreground")
              }
            >
              {lv}
            </button>
          ))}
        </div>
        <input
          value={corr}
          onChange={(e) => setCorr(e.target.value)}
          placeholder="filter by correlation id / text"
          className="ml-auto w-56 rounded border border-border bg-background px-2 py-1 text-xs"
        />
      </div>

      <p className="px-4 py-2 text-[11px] text-muted-foreground">
        Sensitive conversation content, file paths, tool args/results, credentials,
        and secrets are intentionally excluded. Events contain only timestamps,
        stable event names, levels, short correlation ids, and safe scalar counts.
      </p>

      <div className="flex-1 overflow-auto px-4 pb-6 font-mono text-[11px]">
        {filtered.length === 0 ? (
          <p className="text-muted-foreground">No diagnostic events.</p>
        ) : (
          <ul className="flex flex-col gap-1">
            {filtered.map((e, i) => (
              <li key={i} className="border-b border-border/50 py-1">
                <div className="flex gap-2">
                  <span className="text-muted-foreground">{e.ts}</span>
                  <span className={LEVEL_STYLES[e.level] ?? "text-foreground"}>
                    {e.level}
                  </span>
                  <span className="font-semibold">{e.event}</span>
                  {e.origin === "client" && (
                    <span className="ml-1 rounded bg-muted px-1 text-[10px] text-muted-foreground">
                      client
                    </span>
                  )}
                </div>
                <div className="text-muted-foreground">
                  {Object.entries(e)
                    .filter(([k]) => k !== "ts" && k !== "level" && k !== "event")
                    .map(([k, v]) => `${k}=${String(v)}`)
                    .join("  ")}
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
