"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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

// Safe scalar shape of GET /api/diagnostics. Mirrors backend/app/api/health.py:
// app status token, safe counts (ints), bounded recent events (safe fields only).
type SystemDiagnostics = {
  app?: { status?: string };
  counts?: {
    liveSessions?: number;
    creatingSessions?: number;
    closingSessions?: number;
    liveAdapters?: number;
  };
  events?: RtaiDiagnosticEvent[];
};

// System status header state (panel-local React view state only — no store,
// no polling loop, no WebSocket).
type SysState = "fetching" | "ok" | "api-error";

const COUNT_LABELS: Array<[keyof NonNullable<SystemDiagnostics["counts"]>, string]> = [
  ["liveSessions", "live sessions"],
  ["creatingSessions", "creating"],
  ["closingSessions", "closing"],
  ["liveAdapters", "live adapters"],
];

// Category is derived purely from the stable event-name prefix (e.g. "session.created"
// -> "session"). No second backend category field is added; this is a client-only view grouping.
// Defensive: an event name is always a non-empty string from the hub, but a malformed
// event (e.g. from an older served bundle or a buggy producer) must never crash this
// panel inside a useMemo — return a safe "unknown" token instead.
function categoryOf(event: string): string {
  if (typeof event !== "string" || event.length === 0) return "unknown";
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

// Stable dedupe key for ONE hub observed through TWO views. The hub assigns a
// monotonic integer `seq` to every event; global snapshot and active-session
// transport projection therefore dedupe by seq alone. Fallbacks cover hub events
// that predate seq stamping or a missing field, without ever treating the same
// hub event twice.
function dedupeKey(e: RtaiDiagnosticEvent): string {
  const seq = (e as { seq?: unknown }).seq;
  if (typeof seq === "number") return `seq:${seq}`;
  const session = typeof e.session === "string" ? e.session : "";
  return `${e.ts}|${e.event}|${session}|${e.level}|${e.origin ?? ""}`;
}

/**
 * RTAI Runtime Logs — a full-page, safe diagnostics view.
 *
 * It is a dedicated, full-surface panel reachable from the app shell. It stays
 * closed/not mounted until opened (returns null when `open` is false) and never
 * interferes with chat.
 *
 * Sources (ONE backend hub, two views — never a second recorder or store):
 * 1. Global system snapshot: GET /api/diagnostics, fetched ONCE when the panel
 *    opens and only again via the manual Refresh button. No polling, no event
 *    cache/store, no WebSocket. This works with zero sessions/adapters and
 *    while AssistantTransport is unavailable — the Logs page shows whether the
 *    app is alive, current session/adapter counts, and safe lifecycle events.
 * 2. Active-session projection: the same central hub filtered per session and
 *    streamed through AssistantTransport external state (rtaiDiagnostics) via
 *    useRtaiDiagnostics(). It is merged into the list only as a view of the
 *    same hub, deduped by the stable hub event id (seq).
 *
 * System status and current counts are labeled at the top. If /api/diagnostics
 * fails, the page shows a safe "System diagnostics unavailable" state — it
 * never blanks the whole app.
 */
export function DiagnosticsPanel({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  // View 2: safe diagnostics the backend projects through the existing
  // AssistantTransport external state (a filtered view of the ONE central hub).
  const sessionEvents = useRtaiDiagnostics() as RtaiDiagnosticEvent[];

  const [level, setLevel] = useState<string>("all");
  const [category, setCategory] = useState<string>("all");
  const [search, setSearch] = useState("");
  const [order, setOrder] = useState<"newest" | "oldest">("newest");
  const [autoFollow, setAutoFollow] = useState(true);
  const [copiedKey, setCopiedKey] = useState<string | null>(null);
  const [copyError, setCopyError] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  // View 1: global system snapshot — fetched once on open + manual Refresh only.
  const [system, setSystem] = useState<SystemDiagnostics | null>(null);
  const [sysState, setSysState] = useState<SysState>("fetching");
  const staleRef = useRef(false);
  const fetchInFlightRef = useRef(false);

  const fetchSystem = useCallback(async () => {
    if (fetchInFlightRef.current) return;
    fetchInFlightRef.current = true;
    setSysState("fetching");
    try {
      const res = await fetch("/api/diagnostics");
      if (!res.ok) throw new Error(`status ${res.status}`);
      const body = (await res.json()) as SystemDiagnostics;
      if (staleRef.current) return;
      setSystem(body);
      setSysState("ok");
    } catch {
      if (staleRef.current) return;
      // Keep any previous snapshot for context, but honestly label the
      // system status as unavailable. Never blank the whole app.
      setSysState("api-error");
    } finally {
      fetchInFlightRef.current = false;
    }
  }, []);

  // Fetch ONCE when the panel opens; again only on manual Refresh. No polling.
  useEffect(() => {
    if (!open) return;
    staleRef.current = false;
    void fetchSystem();
    return () => {
      staleRef.current = true;
    };
  }, [open, fetchSystem]);

  // ONE merged event list: the global hub snapshot plus the active-session
  // transport view of the SAME hub, deduped by the stable hub event id. No
  // frontend event cache/store — both inputs are recomputed on each render.
  const events = useMemo(() => {
    const globalEvents = system?.events ?? [];
    const merged = new Map<string, RtaiDiagnosticEvent>();
    for (const e of globalEvents) merged.set(dedupeKey(e), e);
    for (const e of sessionEvents) {
      const key = dedupeKey(e);
      if (!merged.has(key)) merged.set(key, e);
    }
    return Array.from(merged.values());
  }, [system, sessionEvents]);

  const counts = system?.counts ?? {};
  const appStatus = system?.app?.status;

  // Categories derived from the current event-name prefixes (client-only view grouping).
  const categories = useMemo(() => {
    const set = new Set<string>();
    for (const e of events) set.add(categoryOf(e.event));
    return Array.from(set).sort();
  }, [events]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    const matched = events.filter((e) => {
      if (level !== "all" && e.level !== level) return false;
      if (category !== "all" && categoryOf(e.event) !== category) return false;
      if (q && !searchableText(e).includes(q)) return false;
      return true;
    });
    // Newest-first = reverse of insertion order; oldest-first = insertion order.
    return order === "newest" ? [...matched].reverse() : matched;
  }, [events, level, category, search, order]);

  // Auto-follow: when enabled, scroll to the newest end (top for newest-first,
  // bottom for oldest-first). Paused => never scroll.
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
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void fetchSystem()}
            className="rounded-md border border-border px-2 py-1 text-xs text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            Refresh
          </button>
          <button
            type="button"
            onClick={onClose}
            aria-label="Back to chat"
            className="rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            <X className="size-4" />
          </button>
        </div>
      </header>

      {/* System status + current counts — labeled at the top of the page. */}
      <div className="border-b border-border px-4 py-2 text-xs">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <span className="font-semibold text-foreground/80">System status:</span>
          {sysState === "fetching" && (
            <span className="text-muted-foreground">checking…</span>
          )}
          {sysState === "ok" && (
            <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <span
                className={
                  "rounded px-1 " +
                  (appStatus === "ready"
                    ? "bg-accent text-accent-foreground"
                    : "bg-muted text-muted-foreground")
                }
              >
                {appStatus ?? "unknown"}
              </span>
              {COUNT_LABELS.map(([key, label]) => (
                <span key={key} className="text-muted-foreground">
                  {label}{" "}
                  <span className="text-foreground/80">
                    {typeof counts[key] === "number" ? counts[key] : 0}
                  </span>
                </span>
              ))}
            </span>
          )}
          {sysState === "api-error" && (
            <span className="text-destructive">System diagnostics unavailable</span>
          )}
        </div>
      </div>

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
        event names, levels, safe booleans, fixed status values, and bounded counts.
        The backend retains the most recent 200 events; the system snapshot is fetched
        once when this page opens and only via Refresh after that.
      </p>

      <div ref={scrollRef} className="flex-1 overflow-auto px-4 pb-6 font-mono text-[13px]">
        {filtered.length === 0 ? (
          <p className="py-8 text-muted-foreground">
            No runtime events yet. Safe diagnostics appear here once the app starts, a
            session starts, or you send a prompt.
          </p>
        ) : (
          <ul className="flex flex-col">
            {filtered.map((e, i) => {
              const key = String((e as { seq?: unknown }).seq ?? i);
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
