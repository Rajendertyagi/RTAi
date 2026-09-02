"use client";

import { useAuiState } from "@assistant-ui/react";
import type { RtaiAssistantState, RtaiCapabilitiesState, RtaiCapabilitiesPending } from "../types/rtaiAssistantState";

/**
 * Safe wrapper around the official `useAssistantTransportState`.
 *
 * The official hook throws when `s.thread.extras` lacks the internal
 * `symbolAssistantTransportExtras` — which is the case on the **first render**
 * before the assistant-transport main thread runtime is mounted (the empty
 * placeholder thread has no `extras.state`).  This wrapper returns `fallback`
 * during that pre-load window, so the UI never crashes.
 *
 * After the transport thread mounts, `s.thread.extras.state` reflects the
 * server-projected `RtaiAssistantState` and the selector receives the real value.
 *
 * @example
 * ```tsx
 * const status = useRtaiTransportState("status", "ready");
 * const sessionId = useRtaiTransportState("sessionId", null);
 * const caps = useRtaiTransportState("rtaiCapabilities", null);
 * ```
 */
export function useRtaiTransportState(
  key: "sessionId",
  fallback: string | null,
): string | null;
export function useRtaiTransportState(
  key: "cwd",
  fallback: string | null,
): string | null;
export function useRtaiTransportState(
  key: "status",
  fallback: RtaiAssistantState["status"],
): RtaiAssistantState["status"];
export function useRtaiTransportState(
  key: "error",
  fallback: string | null,
): string | null;
export function useRtaiTransportState(
  key: "rtaiCapabilities",
  fallback: RtaiCapabilitiesState | null,
): RtaiCapabilitiesState | null;
export function useRtaiTransportState(
  key: "rtaiCapabilitiesPending",
  fallback: RtaiCapabilitiesPending | null,
): RtaiCapabilitiesPending | null;
export function useRtaiTransportState(
  key: keyof RtaiAssistantState,
  fallback: unknown,
): unknown {
  return useAuiState((s) => {
    try {
      const extras = s.thread.extras as Record<string, unknown>;
      if (!extras || typeof extras.state !== "object" || extras.state === null)
        return fallback;
      return (extras.state as RtaiAssistantState)[key];
    } catch {
      return fallback;
    }
  });
}