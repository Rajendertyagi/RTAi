"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { X, Copy, Check } from "lucide-react";
import { useRtaiDiagnostics } from "@/hooks/useRtaiAssistantState";
import type { RtaiDiagnosticEvent } from "@/types/rtaiAssistantState";

const LEVELS = ["all", "debug", "info", "warn", "error"] as const;

const LEVEL_STYLES: Record<string, string> = {
  debug: "text-muted-foreground",
  info: "text-foreground",
  warn: "text-yellow-600",
  error: "text-destructive",
};

// Category is derived purely from the stable event-name prefix (e.g. "session.created"
// -> "session"). No second backend category field is added; this is a client-only view grouping.
function categoryOf(event: string): string {
  const i = event.indexOf(".");
  return i === -1 ? event : event.slice(0, i);
}

// Build a searchable string from only the already-safe visible fields: event name, level,
// origin, and the safe scalar metadata (short correlation ids, counts, etc.).
function searchableText(e: RtaiDiagnosticEvent): string {
  const meta = Object.entries(e)
    .filter(([k]) => k !== "ts" && k !== "level" && k !== "event" && k !== "origin")
    .map(([, v]) => String(v))
    .join(" ");
  return [e.event, e.level, e.origin ?? "", meta].join(" ").toLowerCase();
}

/**
 * RTAI Runtime Logs — a full-page, safe diagnostics view.
 *
 * It is a dedicated, full-surface panel reachable from the app shell. It stays
 * closed/not mounted until opened (returns null when `open` is false) and never
 * interferes with chat. It reads ONLY the safe, ring-buffered events the backend
 * projects through the existing AssistantTransport external state (rtaiDiagnostics)
 * via the single `useRtaiDiagnostics()` hook — there is no second store, no
 * polling, and no separate diagnostics REST endpoint.
 *
 * Events are shown newest-first by default so the most recent lifecycle events are
 * immediately visible without scrolling. All filters/search/order/auto-follow state
 * is local React view state; the event list is always the live backend projection,
 * so pausing auto-follow never freezes or caches the stream.
 */
export function DiagnosticsPanel({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  // Single source of truth: the safe diagnostics the backend projects through the
  // existing AssistantTransport external state. Client events arrive via the
  // rtai.clientDiagnostic command and are recorded server-side with origin:"client",
  // so they are already present in this one stream - there is no second client store.
  const events = useRtaiDiagnostics() as RtaiDiagnosticEvent[];

  const [level, setLevel] = useState<string>("all");
  const [category, setCategory] = useState<string>("all");
  const [search, setSearch] = useState("");
  const [order, setOrder] = useState<"newest" | "oldest">("newest");
  const [autoFollow, setAutoFollow] = useState(true);
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const [copyError, setCopyError] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Categories derived from the current event-name prefixes (client-only view grouping).
  const categories = useMemo(() => {
    const set = new Set<string>();
    for (const e of events) set.add(categoryOf(e.event));
    return Array.from(set).sort();
  }, [events]);

  const filtered = useMemo(() => {
    const list = events;
    const q = search.trim().toLowerCase();
    const matched = list.filter((e) => {
      if (level !== "all" && e.level !== level) return false;
      if (category !== "all" && categoryOf(e.event) !== category) return false;
      if (q && !searchableText(e).includes(q)) return false;
      return true;
    });
    // Newest-first = reverse of insertion order; oldest-first = insertion order.
    return order === "newest" ? [...matched].reverse() : matched;
  }, [events, level, category, search, order]);

  // Auto-follow: when enabled, scroll to the newest end (top for newest-first,
  // bottom for oldest-first). Paused => never scroll, but the list still reflects
  // the live backend projection (no freeze, no local cache).
  useEffect(() => {
    if (!autoFollow) return;
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTop = order === "newest" ? 0 : el.scrollHeight;
  }, [filtered, order, autoFollow]);

  const copyEvent = async (e: RtaiDiagnosticEvent, key: string) => {
    const text = JSON.stringify(e, null, 2);
    setCopyError(false);
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
        setCopiedKey(key);
        window.setTimeout(() => setCopiedKey(null), 1200);
      } else {
        setCopyError(true);
      }
    } catch {
      setCopyError(true);
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-background text-foreground">
      <header className="flex items-center justify-between gap-2 border-b border-border px-4 py-3">
        <div className="flex items-baseline gap-2">
          <h2 className="text-sm font-semibold">Runtime Logs</h2>
          <span className="text-xs text-muted-foreground">
            {filtered.length} of {events.length} event{events.length === 1 ? "" : "s"}
          </span>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Back to chat"
          className="rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
        >
          <X className="size-4" />
        </button>
      </header>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-border px-4 py-2 text-xs">
        <label className="flex items-center gap-1">
          <span className="text-muted-foreground">Search</span>
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="event, level, origin, id, metadata"
            className="w-56 rounded border border-border bg-background px-2 py-1 text-xs"
          />
        </label>

        <label className="flex items-center gap-1">
          <span className="text-muted-foreground">Level</span>
          <div className="flex gap-1">
            {LEVELS.map((lv) => (
              <button
                key={lv}
                type="button"
                onClick={() => setLevel(lv)}
                aria-pressed={level === lv}
                className={
                  "rounded px-2 py-0.5 " +
                  (level === lv ? "bg-accent text-accent-foreground" : "text-muted-foreground")
                }
              >
                {lv}
              </button>
            ))}
          </div>
        </label>

        <label className="flex items-center gap-1">
          <span className="text-muted-foreground">Category</span>
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            className="rounded border border-border bg-background px-2 py-1 text-xs"
          >
            <option value="all">all</option>
            {categories.map((c) => (
              <option key={c} value={c}>
                {c}
              </option>
            ))}
          </select>
        </label>

        <label className="flex items-center gap-1">
          <span className="text-muted-foreground">Order</span>
          <select
            value={order}
            onChange={(e) => setOrder(e.target.value as "newest" | "oldest")}
            className="rounded border border-border bg-background px-2 py-1 text-xs"
          >
            <option value="newest">newest-first</option>
            <option value="oldest">oldest-first</option>
          </select>
        </label>

        <button
          type="button"
          onClick={() => setAutoFollow((v) => !v)}
          aria-pressed={autoFollow}
          className={
            "ml-auto rounded border border-border px-2 py-1 " +
            (autoFollow ? "bg-accent text-accent-foreground" : "text-muted-foreground")
          }
        >
          Auto-follow: {autoFollow ? "On" : "Paused"}
        </button>
      </div>

      <p className="px-4 py-2 text-[11px] text-muted-foreground">
        Sensitive conversation content, file paths, tool args/results, credentials,
        and secrets are intentionally excluded. Events contain only timestamps, stable
        event names, levels, short correlation ids, and safe scalar counts. The backend
        retains the most recent 200 events.
      </p>

      <div ref={scrollRef} className="flex-1 overflow-auto px-4 pb-6 font-mono text-[13px]">
        {filtered.length === 0 ? (
          <p className="py-8 text-muted-foreground">
            No runtime events yet. Safe diagnostics appear here once a session starts or
            you send a prompt.
          </p>
        ) : (
          <ul className="flex flex-col">
            {filtered.map((e, i) => {
              const key = String(i);
              const isCopied = copiedKey === key;
              return (
                <li key={key} className="border-b border-border/50">
                  <details className="group">
                    <summary className="flex cursor-pointer list-none items-center gap-2 py-1.5 pr-2 hover:bg-accent/40">
                      <span className="text-muted-foreground">{e.ts}</span>
                      <span className={LEVEL_STYLES[e.level] ?? "text-foreground"}>
                        {e.level}
                      </span>
                      <span className="font-semibold">{e.event}</span>
                      {e.origin === "client" && (
                        <span className="rounded bg-muted px-1 text-[11px] text-muted-foreground">
                          client
                        </span>
                      )}
                      <span className="ml-auto text-[11px] text-muted-foreground group-open:hidden">
                        expand
                      </span>
                    </summary>
                    <div className="flex flex-wrap items-center gap-2 px-2 pb-2">
                      <button
                        type="button"
                        onClick={() => copyEvent(e, key)}
                        className="inline-flex items-center gap-1 rounded border border-border px-2 py-0.5 text-[11px] text-muted-foreground hover:bg-accent hover:text-foreground"
                      >
                        {isCopied ? <Check className="size-3" /> : <Copy className="size-3" />}
                        {isCopied ? "Copied" : "Copy"}
                      </button>
                      {copyError && (
                        <span className="text-[11px] text-destructive">Copy unavailable</span>
                      )}
                      <div className="flex flex-wrap gap-x-4 gap-y-1">
                        {Object.entries(e)
                          .filter(
                            ([k]) => k !== "ts" && k !== "level" && k !== "event" && k !== "origin",
                          )
                          .map(([k, v]) => (
                            <span key={k} className="text-muted-foreground">
                              <span className="text-foreground/70">{k}</span>={String(v)}
                            </span>
                          ))}
                      </div>
                    </div>
                  </details>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
