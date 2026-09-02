"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  useAssistantTransportState,
  useAui,
  useAuiState,
  type ToolCallMessagePartProps,
} from "@assistant-ui/react";
import {
  ToolFallback,
  ToolFallbackRoot,
  ToolFallbackTrigger,
  ToolFallbackContent,
  ToolFallbackArgs,
  ToolFallbackError,
  ToolFallbackResult,
} from "./tool-fallback";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type BridgeError = { kind: "alert" | "info"; message: string };

/**
 * Thin RTAI transport bridge for tool approvals.
 *
 * The official pinned AssistantTransport runtime only knows its configured
 * `/assistant` API and CANNOT invent or discover RTAI's custom permission REST
 * URL. The concurrent backend endpoint
 *   POST /assistant/sessions/{sessionId}/permissions/{permissionId}
 * exists specifically to resolve an in-flight ACP permission while the active
 * `/assistant` POST is blocked on the ACP permission future. Submitting an
 * approval through the runtime's normal queued command would deadlock: the
 * active request waits for the permission response, and the permission command
 * would wait for the active request to finish. Hence this explicit REST bridge.
 *
 * Everything visible is the official ToolFallback; only `respondToApproval` is
 * overridden. There is exactly one permission-response path — no AddToolResult,
 * no resume, no AssistantTransport approval command, no WebSocket command, no
 * optimistic approval mutation.
 *
 * Important pinned limitation (verified against @assistant-ui/react@0.15.17):
 * `respondToApproval` returns `void`. The official ToolFallbackApproval marks its
 * controls submitted (disabled) immediately after invoking it and does NOT await
 * the asynchronous REST result. Therefore the bridge itself owns the truthful
 * async handling below: in-flight guarding, exact-option validation, and
 * re-enabling the official controls (by remounting them with a local attempt
 * key) when a retryable failure occurs.
 */
export function RtaiToolFallback(props: ToolCallMessagePartProps) {
  // sessionId is projected into the AssistantTransport external state by the
  // RtaiRuntimeProvider converter (state.sessionId).
  const sessionId = useAssistantTransportState((s) => s.sessionId);
  const aui = useAui();
  const isRunning = useAuiState((s) => s.thread.isRunning);

  const approval = props.approval;
  const options = approval?.options ?? [];

  // Local attempt key: bumping it remounts the official ToolFallback, which
  // resets its internal `submitted` flag and re-enables its controls so the
  // user can retry after a retryable failure.
  const [attemptKey, setAttemptKey] = useState(0);
  const [bridgeError, setBridgeError] = useState<BridgeError | null>(null);
  const inflightRef = useRef(false);
  // Always reflects the currently-rendered approval id so a stale async
  // completion from a previous approval cannot mutate this one's state.
  const latestApprovalIdRef = useRef(approval?.id);
  latestApprovalIdRef.current = approval?.id;

  // Reset all local bridge state when the approval identity changes.
  useEffect(() => {
    setBridgeError(null);
    setAttemptKey(0);
    inflightRef.current = false;
  }, [approval?.id]);

  const restResponder = useCallback(
    (args: { optionId?: string; approved?: boolean }) => {
      const approvalId = approval?.id;
      const validOptionIds = (approval?.options ?? []).map((o) => o.id);
      const optionId = args.optionId;

      // Exact option id only. No boolean → kind inference, no fabrication, no
      // generation, no lowercasing. The declared-options path always supplies a
      // real optionId; a boolean-only call is not a valid ACP response path.
      if (!sessionId || !approvalId || !optionId) {
        setBridgeError({
          kind: "info",
          message:
            "This approval could not be sent.",
        });
        return;
      }
      if (!validOptionIds.includes(optionId)) {
        setBridgeError({
          kind: "info",
          message: "This option is no longer valid for the current approval.",
        });
        return;
      }

      // Duplicate / in-flight click protection.
      if (inflightRef.current) return;
      inflightRef.current = true;
      // Clear any prior retryable error before a fresh attempt.
      setBridgeError(null);

      const capturedApprovalId = approvalId;
      const url = `/assistant/sessions/${encodeURIComponent(
        sessionId,
      )}/permissions/${encodeURIComponent(approvalId)}`;

      fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ optionId }),
      })
        .then((res) => {
          inflightRef.current = false;
          // Stale completion for a different approval: do not touch this state.
          if (capturedApprovalId !== latestApprovalIdRef.current) return;

          if (res.status === 204) {
            // Accepted. Keep controls disabled and await the authoritative
            // assistant stream to project optionId / approved / resolution /
            // the tool result. No optimistic mutation.
            return;
          }
          if (res.status === 409) {
            setBridgeError({
              kind: "info",
              message: "This approval is no longer active.",
            });
            return;
          }
          if (res.status >= 500) {
            // Retryable infrastructure failure: surface an alert and re-enable
            // the official controls by remounting them (reset submitted flag).
            // No auto-retry.
            setBridgeError({
              kind: "alert",
              message:
                "The approval service could not be reached. Please try again.",
            });
            setAttemptKey((k) => k + 1);
            return;
          }
          // Other 4xx: terminal, non-retryable.
          setBridgeError({
            kind: "info",
            message: "This approval could not be completed.",
          });
        })
        .catch(() => {
          inflightRef.current = false;
          if (capturedApprovalId !== latestApprovalIdRef.current) return;
          setBridgeError({
            kind: "alert",
            message:
              "Network error while responding to the approval. Please try again.",
          });
          setAttemptKey((k) => k + 1);
        });
    },
    [sessionId, approval],
  );

  // No approval at all: render the official ToolFallback completely unchanged.
  if (!approval) {
    return <ToolFallback {...props} />;
  }

  // Unsupported permission (no real options): never fabricate Allow/Deny.
  // Reuse the official tool header/body and surface the backend-projected safe
  // reason plus the official thread cancellation action only.
  if (options.length === 0) {
    const isCancelled =
      props.status?.type === "incomplete" && props.status.reason === "cancelled";
    return (
      <ToolFallbackRoot defaultOpen>
        <ToolFallbackTrigger toolName={props.toolName} status={props.status} />
        <ToolFallbackContent>
          <ToolFallbackError status={props.status} />
          <ToolFallbackArgs argsText={props.argsText} />
          <div className="aui-tool-fallback-unsupported flex flex-col gap-2 pt-1">
            <p className="text-muted-foreground text-sm">
              {approval.reason ??
                "This action requires approval that is not currently available."}
            </p>
            {isRunning && (
              <Button
                size="sm"
                variant="outline"
                className="active:scale-[0.98] w-fit"
                onClick={() => {
                  try {
                    aui.thread.cancelRun();
                  } catch {
                    /* no-op: nothing to cancel */
                  }
                }}
              >
                Cancel run
              </Button>
            )}
          </div>
          {!isCancelled && <ToolFallbackResult result={props.result} />}
        </ToolFallbackContent>
      </ToolFallbackRoot>
    );
  }

  // Declared-options path: official ToolFallback presentation + thin REST bridge.
  // The attempt key remounts the official component (resetting its internal
  // submitted flag) after a retryable REST failure so its controls re-enable.
  return (
    <>
      <ToolFallback key={attemptKey} {...props} respondToApproval={restResponder} />
      {bridgeError && (
        <div
          role={bridgeError.kind === "alert" ? "alert" : "status"}
          className={cn(
            "mt-1 text-xs",
            bridgeError.kind === "alert"
              ? "text-destructive font-medium"
              : "text-muted-foreground",
          )}
        >
          {bridgeError.message}
        </div>
      )}
    </>
  );
}
