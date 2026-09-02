"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  useAssistantTransportState,
  useAui,
  useAuiState,
  type ToolCallMessagePartComponent,
  type ToolApprovalResponse,
} from "@assistant-ui/react";
import { ToolFallback } from "./tool-fallback";

/**
 * Minimal RTAI-specific REST bridge around the official pinned ToolFallback.
 *
 * The ONLY RTAI-specific behavior is routing an exact, server-provided approval
 * optionId to the concurrent REST permission endpoint (the AssistantTransport
 * prompt POST is blocked, so the response must reach the parallel REST route).
 *
 * No custom approval UI, no invented options, no status/resolution inference.
 * The official ToolFallback renders the exact `approval.options[].id` buttons and
 * calls `respondToApproval({ optionId })`; this bridge forwards that exact id.
 */
export const RtaiToolFallback: ToolCallMessagePartComponent = (props) => {
  const sessionId = useAssistantTransportState((s) => s.sessionId);

  // Derive the single earliest actionable approval across the whole thread from the
  // official Assistant UI runtime state. No permission store, mirror, polling, timer,
  // listener, or manual advancement: when the first approval resolves/expires/completes
  // or its message becomes terminal, official state changes and the next one becomes
  // earliest automatically. Returns a stable primitive (approval id) or null, so the
  // component re-renders only when the earliest actionable approval actually changes.
  const earliestActionableApprovalId = useAuiState((s) => {
    const messages = s.thread?.messages ?? [];
    for (const m of messages) {
      if (m.role !== "assistant") continue;
      const status = m.status;
      if (status && (status.type === "complete" || status.type === "incomplete")) {
        continue; // terminal message → its approvals are no longer actionable
      }
      for (const part of m.content) {
        if (part.type !== "tool-call") continue;
        const a = part.approval;
        if (!a) continue;
        if (
          a.approved !== undefined ||
          a.optionId !== undefined ||
          a.resolution !== undefined
        ) {
          continue;
        }
        if (part.result !== undefined) continue;
        return a.id;
      }
    }
    return null;
  });
  const approval = props.approval;
  const aui = useAui();

  const inFlightRef = useRef(false);
  const [transportError, setTransportError] = useState<string | null>(null);

  // Clear transient transport state when the authoritative approval/part changes.
  useEffect(() => {
    inFlightRef.current = false;
    setTransportError(null);
  }, [
    approval?.id,
    approval?.optionId,
    approval?.approved,
    approval?.resolution,
    props.result,
    props.status,
  ]);

  const respondToApproval = useCallback(
    async (response: ToolApprovalResponse) => {
      if (inFlightRef.current) return; // prevent duplicate permission POSTs

      // Accept ONLY an explicit, server-provided optionId. Never infer an option
      // from kind prefixes, labels, order, or a boolean approval. Never collapse
      // reject-once/reject-always or allow-once/allow-always.
      if (!("optionId" in response)) return;
      const optionId = response.optionId;
      const approvalId = approval?.id;
      const validOptionIds = (approval?.options ?? []).map((o) => o.id);

      if (
        !approvalId ||
        !sessionId ||
        typeof optionId !== "string" ||
        optionId.length === 0
      ) {
        return;
      }
      // Must exactly match one of the server-provided option ids (byte-for-byte).
      if (!validOptionIds.includes(optionId)) return;

      inFlightRef.current = true;
      setTransportError(null);
      try {
        const res = await fetch(
          `/assistant/sessions/${encodeURIComponent(sessionId)}/permissions/${encodeURIComponent(approvalId)}`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ optionId }),
          },
        );
        if (res.status === 204) {
          // Resolved: wait for authoritative streamed state. No optimistic mutate.
          return;
        }
        if (res.status === 409) {
          // Already resolved/expired: no retry, wait for terminal streamed state.
          return;
        }
        // 5xx / unexpected: keep options retryable, surface a minimal safe message.
        setTransportError(
          "Could not submit the permission response. Please try again.",
        );
      } catch {
        setTransportError(
          "Could not submit the permission response. Please try again.",
        );
      } finally {
        inFlightRef.current = false;
      }
    },
    [approval, sessionId],
  );

  const isEarliestActionable =
    earliestActionableApprovalId !== null &&
    approval?.id === earliestActionableApprovalId;

  // A different approval is the earliest actionable one: show this part read-only
  // (tool information only) and never expose clickable approval options yet.
  if (!isEarliestActionable && earliestActionableApprovalId !== null) {
    const toolName = props.part?.toolName;
    return (
      <div className="flex items-center gap-3 rounded-lg border border-interactive bg-surface-elevated p-3 text-sm text-muted-foreground">
        <span>
          {toolName ? `Tool: ${toolName}` : "Tool call"} — awaiting an earlier approval.
        </span>
      </div>
    );
  }

  // No pending actionable approval anywhere: this part is resolved/complete. Render
  // the official ToolFallback presentation (no RTAI REST responder needed).
  if (earliestActionableApprovalId === null) {
    return <ToolFallback {...props} />;
  }

  // Earliest actionable approval with zero options: show the safe reason and only the
  // official Cancel run action. Do not send a permission response.
  const hasOptions = !!approval?.options && approval.options.length > 0;
  if (!hasOptions) {
    return (
      <div className="flex items-center gap-3 rounded-lg border border-interactive bg-surface-elevated p-3 text-sm text-muted-foreground">
        <span>{approval?.reason ?? "This action cannot be approved in this session."}</span>
        <button
          type="button"
          onClick={() => aui.thread().cancelRun()}
          className="shrink-0 rounded-md px-2 py-1 text-xs text-status-error transition-colors hover:bg-interactive-hover"
        >
          Cancel
        </button>
      </div>
    );
  }

  return (
    <>
      <ToolFallback {...props} respondToApproval={respondToApproval} />
      {transportError && (
        <p className="mt-1 text-xs text-status-error">{transportError}</p>
      )}
    </>
  );
};
