"use client";

import type { ReactNode } from "react";
import { Bot, Brain, Cpu, Layers } from "lucide-react";
import { useChatStore, type PendingSelection } from "../state/chatStore";
import type { CapabilityItem, UnavailableReason } from "../types/protocol";

// Compact, theme-driven capability controls for the composer footer.
// Every control is driven entirely by runtime state — never hardcoded —
// and follows the tri-state contract:
//   • available-with-items  → enabled dropdown (authoritative value shown)
//   • available-but-empty   → disabled control + accessible explanation
//   • unavailable           → disabled control showing the runtime reason
// No control auto-selects a first item, and unavailable states are never
// turned into fake empty lists or invented defaults.

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
  options: CapabilityItem[];
  onChange: (id: string) => void;
  disabled?: boolean;
  pending?: boolean;
  testId?: string;
}) {
  const selected = options.find((o) => o.id === value);
  return (
    <label
      className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-interactive-hover focus-within:bg-interactive-hover"
      title={selected?.description ?? selected?.label ?? label}
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
          <option key={o.id} value={o.id} title={o.description ?? o.label}>
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

// Noninteractive chip — used for a fixed identity (single agent, or the
// backend-provided agent label when no selectable list exists).
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

// Disabled control carrying a runtime reason (unavailable section).
function CapabilityUnavailable({
  icon,
  label,
  reason,
  testId,
}: {
  icon: ReactNode;
  label: string;
  reason: UnavailableReason;
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

// Available-but-empty: disabled control with a neutral explanation.
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
  const agents = useChatStore((s) => s.agents);
  const models = useChatStore((s) => s.models);
  const modes = useChatStore((s) => s.modes);
  const thinkingLevels = useChatStore((s) => s.thinkingLevels);
  const selectedAgent = useChatStore((s) => s.selectedAgent);
  const selectedModel = useChatStore((s) => s.selectedModel);
  const selectedMode = useChatStore((s) => s.selectedMode);
  const thinkingLevel = useChatStore((s) => s.thinkingLevel);
  const agentsReason = useChatStore((s) => s.agentsReason);
  const modelsReason = useChatStore((s) => s.modelsReason);
  const modesReason = useChatStore((s) => s.modesReason);
  const thinkingReason = useChatStore((s) => s.thinkingReason);
  const pendingSelections = useChatStore((s) => s.pendingSelections);
  const agentInfo = useChatStore((s) => s.agentInfo);
  const selectAgent = useChatStore((s) => s.selectAgent);
  const selectModel = useChatStore((s) => s.selectModel);
  const selectMode = useChatStore((s) => s.selectMode);
  const setThinkingLevel = useChatStore((s) => s.setThinkingLevel);

  const isPending = (type: PendingSelection["type"]) =>
    Array.from(pendingSelections.values()).some((p) => p.type === type);

  // --- Agent -------------------------------------------------------------
  // Multiple selectable agents → dropdown. One fixed identity → chip.
  // No identity at all → omitted (no OpenCode/Agent fallback).
  const renderAgent = (): ReactNode => {
    if (agents.length > 1) {
      return (
        <CapabilitySelect
          key="agent"
          icon={<Bot className="h-3.5 w-3.5" />}
          label="Agent"
          value={selectedAgent}
          options={agents}
          onChange={selectAgent}
          pending={isPending("agent")}
          testId="composer-agent"
        />
      );
    }
    if (agents.length === 1) {
      const a = agents[0]!;
      return (
        <CapabilityChip
          key="agent"
          icon={<Bot className="h-3.5 w-3.5" />}
          label={a.label}
          title={a.description ?? a.label}
          testId="composer-agent"
        />
      );
    }
    if (agentsReason) {
      return (
        <CapabilityUnavailable
          key="agent"
          icon={<Bot className="h-3.5 w-3.5" />}
          label="Agent"
          reason={agentsReason}
          testId="composer-agent"
        />
      );
    }
    if (agentInfo) {
      return (
        <CapabilityChip
          key="agent"
          icon={<Bot className="h-3.5 w-3.5" />}
          label={agentInfo}
          title={agentInfo}
        />
      );
    }
    return null;
  };

  // --- Model -------------------------------------------------------------
  const renderModel = (): ReactNode => {
    if (modelsReason) {
      return (
        <CapabilityUnavailable
          key="model"
          icon={<Cpu className="h-3.5 w-3.5" />}
          label="Model"
          reason={modelsReason}
          testId="composer-model"
        />
      );
    }
    if (models.length === 0) {
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
    return (
      <CapabilitySelect
        key="model"
        icon={<Cpu className="h-3.5 w-3.5" />}
        label="Model"
        value={selectedModel}
        options={models}
        onChange={selectModel}
        pending={isPending("model")}
        testId="composer-model"
      />
    );
  };

  // --- Mode --------------------------------------------------------------
  // Runtime-dynamic: enabled dropdown when selectable, disabled-with-reason
  // when the adapter reports it unavailable. NOT hardcoded to any adapter.
  const renderMode = (): ReactNode => {
    if (modesReason) {
      return (
        <CapabilityUnavailable
          key="mode"
          icon={<Layers className="h-3.5 w-3.5" />}
          label="Mode"
          reason={modesReason}
          testId="composer-mode"
        />
      );
    }
    if (modes.length === 0) {
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
    return (
      <CapabilitySelect
        key="mode"
        icon={<Layers className="h-3.5 w-3.5" />}
        label="Mode"
        value={selectedMode}
        options={modes}
        onChange={selectMode}
        pending={isPending("mode")}
        testId="composer-mode"
      />
    );
  };

  // --- Thinking ----------------------------------------------------------
  // Only render when runtime supplies levels. Never manufacture off/low/etc.
  // Unavailable → show reason; genuinely absent → omit the control.
  const renderThinking = (): ReactNode => {
    if (thinkingLevels.length === 0) {
      if (thinkingReason) {
        return (
          <CapabilityUnavailable
            key="thinking"
            icon={<Brain className="h-3.5 w-3.5" />}
            label="Thinking"
            reason={thinkingReason}
            testId="composer-thinking"
          />
        );
      }
      return null;
    }
    return (
      <CapabilitySelect
        key="thinking"
        icon={<Brain className="h-3.5 w-3.5" />}
        label="Thinking"
        value={thinkingLevel || null}
        options={thinkingLevels.map((lvl) => ({ id: lvl, label: lvl }))}
        onChange={setThinkingLevel}
        pending={isPending("thinking")}
        testId="composer-thinking"
      />
    );
  };

  return (
    <div className="flex flex-wrap items-center gap-1" data-capabilities>
      {renderAgent()}
      {renderModel()}
      {renderMode()}
      {renderThinking()}
    </div>
  );
}
