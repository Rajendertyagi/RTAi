"use client";

import { useAssistantTransportState } from "@assistant-ui/react";
import type { RtaiAssistantState } from "@/types/rtaiAssistantState";

/**
 * Single, lifecycle-safe, typed access path for RTAI AssistantTransport external
 * state.
 *
 * Every RTAI UI reader must render inside <RtaiRuntimeProvider>, which gates on
 * transport readiness (the AssistantTransport thread is not mounted until after
 * the placeholder thread), so this hook is only ever called once the external
 * state exists. This hook centralises selection + safe defaults so no component
 * spreads its own try/catch or duplicate readiness logic — there is exactly one
 * access path.
 *
 * The selector receives the full RtaiAssistantState (the augmentation declares
 * `ExternalState { rtai: RtaiAssistantState }`, so the projected external state
 * value type is RtaiAssistantState and the converter projects those flat fields).
 */
export function useRtaiAssistantState<T>(
  selector: (s: RtaiAssistantState) => T,
  fallback: T,
): T {
  const value = useAssistantTransportState(selector);
  return value === undefined ? fallback : value;
}

export function useRtaiCapabilities() {
  return useRtaiAssistantState((s) => s.rtaiCapabilities, undefined);
}

export function useRtaiCapabilitiesPending() {
  return useRtaiAssistantState((s) => s.rtaiCapabilitiesPending, undefined);
}

export function useRtaiDiagnostics() {
  return useRtaiAssistantState((s) => s.rtaiDiagnostics, []);
}

export function useRtaiSessionId() {
  return useRtaiAssistantState((s) => s.sessionId, null);
}
