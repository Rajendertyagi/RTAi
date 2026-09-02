"use client";

import { useMemo, useState } from "react";
import { useAssistantTransportState } from "@assistant-ui/react";
import type { RtaiDiagnosticEvent } from "@/types/rtaiAssistantState";

const LEVELS = ["all", "debug", "info", "warn", "error"] as const;

const LEVEL_STYLES: Record<string, string> = {
  debug: "text-muted-foreground",
  info: "text-foreground",
  warn: "text-yellow-600",
  error: "text-destructive",
};

/**
 * Minimal, RTAI-specific safe-event log. It is the only diagnostics UI and is
 * closed by default. It never sends anything to the backend and only displays
 * the safe, ring-buffered events the backend projects through the existing
 * AssistantTransport external state (no second store, polling, or console dump).
 */
export function DiagnosticsPanel({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const events = useAssistantTransportState((s) => s.rtaiDiagnostics) ?? [];
  const [level, setLevel] = useState<string>("all");
  const [corr, setCorr] = useState("");

  const filtered = useMemo(() => {
    const list = events as RtaiDiagnosticEvent[];
    return list.filter((e) => {
      if (level !== "all" && e.level !== level) return false;
      if (corr.trim()) {
        const hay = JSON.stringify(e).toLowerCase();
        if (!hay.includes(corr.trim().toLowerCase())) return false;
      }
      return true;
    });
  }, [events, level, corr]);

  if (!open) return null;

  return (
    <div className="fixed bottom-12 right-3 z-50 w-[min(92vw,28rem)] rounded-lg border border-border bg-popover text-popover-foreground shadow-xl">
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <span className="text-sm font-medium">Diagnostics</span>
        <button
          type="button"
          className="text-xs text-muted-foreground hover:text-foreground"
          onClick={onClose}
        >
          Close
        </button>
      </div>
      <div className="flex flex-wrap items-center gap-2 px-3 py-2 text-xs">
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
          placeholder="filter id / text"
          className="ml-auto w-36 rounded border border-border bg-background px-2 py-1 text-xs"
        />
      </div>
      <p className="px-3 pb-1 text-[11px] text-muted-foreground">
        Sensitive conversation and tool content is intentionally excluded.
      </p>
      <div className="max-h-[50vh] overflow-auto px-3 pb-3 font-mono text-[11px]">
        {filtered.length === 0 ? (
          <p className="text-muted-foreground">No diagnostic events.</p>
        ) : (
          filtered.map((e, i) => (
            <div key={i} className="border-b border-border/50 py-1">
              <div className="flex gap-2">
                <span className="text-muted-foreground">{e.ts}</span>
                <span className={LEVEL_STYLES[e.level] ?? "text-foreground"}>
                  {e.level}
                </span>
                <span className="font-semibold">{e.event}</span>
              </div>
              <div className="text-muted-foreground">
                {Object.entries(e)
                  .filter(([k]) => k !== "ts" && k !== "level" && k !== "event")
                  .map(([k, v]) => `${k}=${String(v)}`)
                  .join("  ")}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
