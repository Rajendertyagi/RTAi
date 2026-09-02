"use client";

import { useEffect, useCallback, useRef, useState, type ReactNode } from "react";
import { Bot, Cpu, Layers } from "lucide-react";
import { useAssistantTransportSendCommand } from "@assistant-ui/react";
import {
  useRtaiCapabilities,
  useRtaiCapabilitiesPending,
  useRtaiSessionId,
} from "@/hooks/useRtaiAssistantState";
import type {
  RtaiCapabilityItem,
  RtaiCapabilitiesState,
} from "../types/rtaiAssistantState";
import {
  ModelSelectorRoot,
  ModelSelectorTrigger,
  ModelSelectorContent,
} from "@/components/ModelSelector";

// --- Capability bootstrap diagnostics (gated; enable via localStorage["rtai-debug"]="1") ---
// Logs only stage names, booleans, short ids and counts (never capability values/payloads).
const RTAI_DIAG_ENABLED =
  typeof window !== "undefined" &&
  typeof window.localStorage !== "undefined" &&
  window.localStorage.getItem("rtai-debug") === "1";
// Short correlation id (client side, pre-session) so one bootstrap run can be
// followed across stages without leaking the full backend session id.
const RTAI_SHORT_ID = (): string => {
  const buf = new Uint32Array(2);
  if (typeof crypto !== "undefined" && crypto.getRandomValues) {
    crypto.getRandomValues(buf);
  } else {
    buf[0] = Math.floor(Math.random() * 0xffffffff);
    buf[1] = Math.floor(Math.random() * 0xffffffff);
  }
  return Array.from(buf)
    .map((n) => n.toString(16).padStart(8, "0"))
    .join("")
    .slice(0, 8);
};
const RTAI_DIAG = (stage: string, meta?: Record<string, unknown>) => {
  if (!RTAI_DIAG_ENABLED) return;
  console.debug("[rtai-capability]", stage, meta ?? "");
};

// PART C: the official Assistant UI registry ModelSelectorRoot is adopted here as
// a STANDALONE, controlled component (no .aui / api.modelContext.register, no
// connected selector that owns model state). It is driven entirely by RTAI's
// authoritative capability state and submits exact backend option IDs (never
// labels) through the rtai.selectModel / rtai.selectThinking commands. The model
// list is the model selection path; the selected model's effort radios are the
// thinking selection path - exactly one selection path, no modelContext sync.
// Agent/mode keep the minimal native <select> controlled pattern below.
type CapabilityKind = "agent" | "model" | "mode" | "thinking";

const COMMAND_BY_KIND: Record<
  CapabilityKind,
  "rtai.selectAgent" | "rtai.selectModel" | "rtai.selectMode" | "rtai.selectThinking"
> = {
  agent: "rtai.selectAgent",
  model: "rtai.selectModel",
  mode: "rtai.selectMode",
  thinking: "rtai.selectThinking",
};

function CapabilitySelect({
  icon,
  label,
  value,
  options,
  onChange,
  disabled,
  pending,
  testId,
}: {
  icon: ReactNode;
  label: string;
  value: string | null;
  options: RtaiCapabilityItem[];
  onChange: (id: string) => void;
  disabled?: boolean;
  pending?: boolean;
  testId?: string;
}) {
  const selected = options.find((o) => o.id === value);
  return (
    <label
      className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-interactive-hover focus-within:bg-interactive-hover"
      title={selected?.label ?? label}
    >
      <span className="shrink-0 opacity-70" aria-hidden="true">
        {icon}
      </span>
      <select
        aria-label={label}
        data-testid={testId}
        value={value ?? ""}
        disabled={disabled || pending}
        onChange={(e) => onChange(e.target.value)}
        className="max-w-[10rem] cursor-pointer truncate bg-transparent text-xs text-foreground outline-none disabled:cursor-not-allowed disabled:opacity-50"
      >
        {value == null && <option value="">Select…</option>}
        {options.map((o) => (
          <option key={o.id} value={o.id} title={o.label}>
            {o.label}
          </option>
        ))}
      </select>
      {pending && (
        <span
          className="h-3 w-3 shrink-0 animate-spin rounded-full border-2 border-muted-foreground border-t-transparent"
          aria-label="Updating…"
        />
      )}
    </label>
  );
}

function CapabilityChip({
  icon,
  label,
  title,
  testId,
}: {
  icon: ReactNode;
  label: string;
  title?: string;
  testId?: string;
}) {
  return (
    <span
      data-testid={testId}
      className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs text-muted-foreground"
      title={title ?? label}
    >
      <span className="shrink-0 opacity-70" aria-hidden="true">
        {icon}
      </span>
      <span className="max-w-[10rem] truncate">{label}</span>
    </span>
  );
}

function CapabilityUnavailable({
  icon,
  label,
  reason,
  testId,
}: {
  icon: ReactNode;
  label: string;
  reason: { reason_code: string; reason_message: string };
  testId?: string;
}) {
  return (
    <span
      data-testid={testId}
      className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs text-muted-foreground opacity-60"
      title={`${label}: ${reason.reason_message}`}
    >
      <span className="shrink-0 opacity-70" aria-hidden="true">
        {icon}
      </span>
      <span className="max-w-[10rem] truncate">{reason.reason_message}</span>
    </span>
  );
}

function CapabilityEmpty({
  icon,
  label,
  message,
  testId,
}: {
  icon: ReactNode;
  label: string;
  message: string;
  testId?: string;
}) {
  return (
    <span
      data-testid={testId}
      className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs text-muted-foreground opacity-60"
      title={`${label}: ${message}`}
    >
      <span className="shrink-0 opacity-70" aria-hidden="true">
        {icon}
      </span>
      <span className="max-w-[10rem] truncate">{message}</span>
    </span>
  );
}

export function CapabilityControls() {
  const caps = useRtaiCapabilities();
  const pending = useRtaiCapabilitiesPending();
  const sessionId = useRtaiSessionId();
  const sendCommand = useAssistantTransportSendCommand();

  const isInitialized = caps?.initialized ?? false;
  const refreshPending = pending?.refresh ?? false;
  const corrRef = useRef<string>(RTAI_SHORT_ID());

  // Bootstrap lifecycle over the official AssistantTransport command queue only:
  //   not-requested -> pending -> initialized | failed
  // A single rtai.refreshCapabilities is queued on mount; the backend projects the
  // authoritative snapshot into rtaiCapabilities. Without this the Composer is
  // permanently stuck on "Loading capabilities…" (boundary A: the refresh command
  // was never sent). No client session id is synthesized; the backend owns the id.
  const requestedRef = useRef(false);
  const sawPendingRef = useRef(false);
  const [failed, setFailed] = useState(false);
  const [retryNonce, setRetryNonce] = useState(0);

  useEffect(() => {
    const corr = corrRef.current;
    const sidShort = sessionId ? sessionId.slice(-8) : null;
    const pendingTypes: string[] = [];
    if (pending) {
      if (pending.refresh) pendingTypes.push("rtai.refreshCapabilities");
      if (pending.agent) pendingTypes.push("rtai.selectAgent");
      if (pending.model) pendingTypes.push("rtai.selectModel");
      if (pending.mode) pendingTypes.push("rtai.selectMode");
      if (pending.thinking) pendingTypes.push("rtai.selectThinking");
    }
    RTAI_DIAG("bootstrap-considered", {
      corr,
      hasCaps: !!caps,
      initialized: caps?.initialized ?? null,
      refreshPending,
      failed,
      sessionId: sidShort,
      error: caps?.error ? caps.error.reason_code : null,
      pendingTypes,
      pendingCount: pendingTypes.length,
    });
    if (caps) {
      RTAI_DIAG("inFlightDiscovery-removed", { corr, sessionId: sidShort });
      setFailed(false);
      return;
    }
    if (refreshPending) {
      sawPendingRef.current = true;
      setFailed(false);
      RTAI_DIAG("refresh-skipped", { corr, reason: "refreshPending" });
      return;
    }
    if (requestedRef.current) {
      RTAI_DIAG("refresh-skipped", { corr, reason: "alreadyRequested" });
      // Queued a refresh, saw it go pending, and now it is neither pending nor
      // resolved: the request failed or was dropped. Surface Retry instead of a
      // permanent spinner. sawPendingRef avoids a StrictMode false positive.
      if (sawPendingRef.current) setFailed(true);
      return;
    }
    // Not initialized, not pending, never requested: queue exactly one refresh.
    requestedRef.current = true;
    try {
      RTAI_DIAG("refresh-queued", { corr, reason: "bootstrap-mount" });
      sendCommand({ type: "rtai.refreshCapabilities" } as Parameters<typeof sendCommand>[0]);
      setFailed(false);
    } catch {
      requestedRef.current = false; // allow a retry
      setFailed(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [caps, refreshPending, sendCommand, retryNonce]);

  const handleRetry = useCallback(() => {
    RTAI_DIAG("retry");
    requestedRef.current = false;
    sawPendingRef.current = false;
    setFailed(false);
    setRetryNonce((n) => n + 1);
  }, []);

  const pendingForKind = (kind: CapabilityKind): boolean => {
    if (!pending) return false;
    return pending[kind] ?? false;
  };

  const handleSelect = (kind: CapabilityKind, value: string) => {
    // Send the exact adapter ID (never the label); validated strictly server-side.
    // rtai.* commands are declared in assistantTransportAugmentation.ts
    // (Assistant.Commands augmentation), so a single precise cast to the exact
    // command parameter type is sufficient — no `as unknown as` / wide cast.
    sendCommand({ type: COMMAND_BY_KIND[kind], value } as Parameters<typeof sendCommand>[0]);
  };

  // Agent: tri-state — available with items → dropdown, available empty → disabled, null → unsupported hidden
  const renderAgent = (): ReactNode => {
    if (!isInitialized) {
      return (
        <CapabilityUnavailable
          key="agent"
          icon={<Bot className="h-3.5 w-3.5" />}
          label="Agent"
          reason={{ reason_code: "not_initialized", reason_message: "Loading…" }}
          testId="composer-agent"
        />
      );
    }
    if (caps?.agents === null) {
      // No real agent list exists (ACP exposes one identity, no switching):
      // show the active identity chip only when it is genuinely available.
      // Never mirror ACP modes here — that duplicated the Mode selector.
      if (!caps?.agent) return null;
      return (
        <CapabilityChip
          key="agent"
          icon={<Bot className="h-3.5 w-3.5" />}
          label={caps.agent.label}
          title={caps.agent.label}
          testId="composer-agent"
        />
      );
    }
    if (caps?.agents && caps.agents.length > 1) {
      return (
        <CapabilitySelect
          key="agent"
          icon={<Bot className="h-3.5 w-3.5" />}
          label="Agent"
          value={caps.selected.agent}
          options={caps.agents}
          onChange={(v) => handleSelect("agent", v)}
          pending={pendingForKind("agent")}
          testId="composer-agent"
        />
      );
    }
    if (caps?.agents && caps.agents.length === 1) {
      const a = caps.agents[0]!;
      return (
        <CapabilityChip
          key="agent"
          icon={<Bot className="h-3.5 w-3.5" />}
          label={a.label}
          title={a.label}
          testId="composer-agent"
        />
      );
    }
    if (caps?.agents && caps.agents.length === 0) {
      return (
        <CapabilityEmpty
          key="agent"
          icon={<Bot className="h-3.5 w-3.5" />}
          label="Agent"
          message="No agents"
          testId="composer-agent"
        />
      );
    }
    return null;
  };

  const renderModel = (): ReactNode => {
    if (!isInitialized) {
      return (
        <CapabilityUnavailable
          key="model"
          icon={<Cpu className="h-3.5 w-3.5" />}
          label="Model"
          reason={{ reason_code: "not_initialized", reason_message: "Loading…" }}
          testId="composer-model"
        />
      );
    }
    if (caps?.models === null) {
      return (
        <CapabilityUnavailable
          key="model"
          icon={<Cpu className="h-3.5 w-3.5" />}
          label="Model"
          reason={caps.error ?? { reason_code: "not_exposed", reason_message: "Not available" }}
          testId="composer-model"
        />
      );
    }
    if (caps?.models && caps.models.length === 0) {
      return (
        <CapabilityEmpty
          key="model"
          icon={<Cpu className="h-3.5 w-3.5" />}
          label="Model"
          message="No models available"
          testId="composer-model"
        />
      );
    }
    if (caps?.models) {
      return (
        <span key="model" className="inline-flex items-center gap-1.5">
          <ModelSelectorRoot
            models={caps.models.map((m) => ({
              id: m.id,
              name: m.label,
              efforts: caps.thinkingOptions
                ? caps.thinkingOptions.map((t) => ({
                    id: t.id,
                    name: t.label,
                  }))
                : undefined,
            }))}
            value={caps.selected.model ?? undefined}
            onValueChange={(id) => handleSelect("model", id)}
            effort={caps.selected.thinking ?? undefined}
            onEffortChange={(id) => handleSelect("thinking", id)}
          >
            <ModelSelectorTrigger
              variant="ghost"
              size="sm"
              className="px-2 py-1"
              disabled={pendingForKind("model")}
            />
            <ModelSelectorContent align="start" searchable={false} />
          </ModelSelectorRoot>
          {caps.error?.reason_code === "model" && (
            <span
              data-testid="composer-model-error"
              className="text-xs text-destructive"
              title={caps.error.reason_message}
            >
              {caps.error.reason_message}
            </span>
          )}
        </span>
      );
    }
    return null;
  };

  const renderMode = (): ReactNode => {
    if (!isInitialized) {
      return (
        <CapabilityUnavailable
          key="mode"
          icon={<Layers className="h-3.5 w-3.5" />}
          label="Mode"
          reason={{ reason_code: "not_initialized", reason_message: "Loading…" }}
          testId="composer-mode"
        />
      );
    }
    if (caps?.modes === null) {
      return (
        <CapabilityUnavailable
          key="mode"
          icon={<Layers className="h-3.5 w-3.5" />}
          label="Mode"
          reason={caps.error ?? { reason_code: "not_exposed", reason_message: "Not available" }}
          testId="composer-mode"
        />
      );
    }
    if (caps?.modes && caps.modes.length === 0) {
      return (
        <CapabilityEmpty
          key="mode"
          icon={<Layers className="h-3.5 w-3.5" />}
          label="Mode"
          message="No modes"
          testId="composer-mode"
        />
      );
    }
    if (caps?.modes) {
      return (
        <CapabilitySelect
          key="mode"
          icon={<Layers className="h-3.5 w-3.5" />}
          label="Mode"
          value={caps.selected.mode}
          options={caps.modes}
          onChange={(v) => handleSelect("mode", v)}
          pending={pendingForKind("mode")}
          testId="composer-mode"
        />
      );
    }
    return null;
  };


  if (!caps) {
    if (failed) {
      // Discovery failed/dropped: offer one Retry, never a permanent spinner.
      RTAI_DIAG("render-failed");
      return (
        <div className="flex flex-wrap items-center gap-1" data-capabilities>
          <span className="text-xs text-muted-foreground">Capabilities unavailable</span>
          <button
            type="button"
            onClick={handleRetry}
            className="rounded-lg px-2 py-1 text-xs text-muted-foreground underline hover:text-foreground"
            data-testid="composer-capabilities-retry"
          >
            Retry
          </button>
        </div>
      );
    }
    // Bootstrap: show loading state while the single refresh is in flight.
    RTAI_DIAG("render-loading");
    return (
      <div className="flex flex-wrap items-center gap-1" data-capabilities>
        <span className="text-xs text-muted-foreground">Loading capabilities…</span>
      </div>
    );
  }

  RTAI_DIAG("render-ready", {
    corr: corrRef.current,
    sessionId: sessionId ? sessionId.slice(-8) : null,
  });
  return (
    <div className="flex flex-wrap items-center gap-1" data-capabilities>
      {renderAgent()}
      {renderModel()}
      {renderMode()}
    </div>
  );
}
