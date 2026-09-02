"use client";

import type { ReactNode } from "react";
import { Bot, Brain, Cpu, Layers } from "lucide-react";
import {
  useAssistantTransportSendCommand,
  useAssistantTransportState,
  } from "@assistant-ui/react";
import type {
  RtaiCapabilityItem,
  RtaiCapabilitiesState,
} from "../types/rtaiAssistantState";

// PART C decision: the official Assistant UI Model Selector is intentionally NOT
// adopted here. In the pinned @assistant-ui/react@0.15.17 it would require either a
// model registry / `config.modelName` selection path or a connected selector that
// owns model state — both conflict with the single authoritative RTAI selection
// path (the rtai.selectModel / rtai.selectThinking commands). These minimal native
// <select> controls keep exactly one selection path and submit exact backend
// option IDs (never labels). Agent/mode use the same controlled pattern.
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
  const caps = useAssistantTransportState((s) => s.rtaiCapabilities);
  const pending = useAssistantTransportState((s) => s.rtaiCapabilitiesPending);
  const sendCommand = useAssistantTransportSendCommand();

  // Bootstrap: if not initialized, show loading and trigger refresh once via pendingCommand
  // The backend will project authoritative snapshot; no custom store.
  const isInitialized = caps?.initialized ?? false;

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
    if (caps?.agents === null) return null; // unsupported → hidden
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
    // Fallback single agent from `agent` field when `agents` is null but agent exists
    if (caps?.agent) {
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
        <CapabilitySelect
          key="model"
          icon={<Cpu className="h-3.5 w-3.5" />}
          label="Model"
          value={caps.selected.model}
          options={caps.models}
          onChange={(v) => handleSelect("model", v)}
          pending={pendingForKind("model")}
          testId="composer-model"
        />
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

  const renderThinking = (): ReactNode => {
    if (!isInitialized) return null;
    if (caps?.thinkingOptions === null) return null; // unsupported → hidden
    if (!caps?.thinkingOptions || caps.thinkingOptions.length === 0) {
      if (caps?.error) {
        return (
          <CapabilityUnavailable
            key="thinking"
            icon={<Bot className="h-3.5 w-3.5" />}
            label="Thinking"
            reason={caps.error}
            testId="composer-thinking"
          />
        );
      }
      return null;
    }
    return (
      <CapabilitySelect
        key="thinking"
        icon={<Bot className="h-3.5 w-3.5" />}
        label="Thinking"
        value={caps.selected.thinking}
        options={caps.thinkingOptions}
        onChange={(v) => handleSelect("thinking", v)}
        pending={pendingForKind("thinking")}
        testId="composer-thinking"
      />
    );
  };

  if (!caps) {
    // Bootstrap: show loading state, no fake defaults
    return (
      <div className="flex flex-wrap items-center gap-1" data-capabilities>
        <span className="text-xs text-muted-foreground">Loading capabilities…</span>
      </div>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-1" data-capabilities>
      {renderAgent()}
      {renderModel()}
      {renderMode()}
      {renderThinking()}
    </div>
  );
}
