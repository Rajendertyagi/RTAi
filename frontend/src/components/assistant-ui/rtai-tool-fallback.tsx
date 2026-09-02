"use client";

import { useCallback } from "react";
import {
  useAssistantTransportState,
  type ToolCallMessagePartProps,
} from "@assistant-ui/react";
import { ToolFallback } from "./tool-fallback";

// Thin RTAI transport bridge for tool approvals.
//
// The official pinned AssistantTransport runtime only knows its configured
// `/assistant` API and CANNOT invent or discover RTAI's custom permission REST
// URL. The concurrent backend endpoint
//   POST /assistant/sessions/{sessionId}/permissions/{permissionId}
// exists specifically to resolve an in-flight ACP permission while the active
// `/assistant` POST is blocked on the ACP permission future. Submitting an
// approval through the runtime's normal queued command would deadlock: the
// active request waits for the permission response, and the permission command
// waits for the active request to finish. Hence this explicit REST bridge.
//
// Everything visible is the official ToolFallback; only `respondToApproval` is
// overridden. No AddToolResult / queued AssistantTransport approval command is
// emitted — there is exactly one permission-response path.
export function RtaiToolFallback(props: ToolCallMessagePartProps) {
  // sessionId is projected into the AssistantTransport external state by the
  // RtaiRuntimeProvider converter (state.rtai.sessionId).
  const sessionId = useAssistantTransportState((s) => s.sessionId);

  const restResponder = useCallback(
    (args: { optionId?: string; approved?: boolean }) => {
      const approvalId = props.approval?.id;
      if (!sessionId || !approvalId) return;

      // Resolve the exact optionId to send, preserving backend IDs byte-for-byte.
      let optionId: string | undefined = args.optionId;
      if (optionId === undefined && typeof args.approved === "boolean") {
        // Official boolean allow/deny fallback (used when no declared options).
        // Map it to the matching real ACP option if one exists; otherwise do NOT
        // fabricate an optionId for an unsupported permission.
        const options = props.approval?.options ?? [];
        const wanted = args.approved
          ? ["allow-once", "allow-always"]
          : ["reject-once", "reject-always"];
        optionId = options.find((o) => wanted.includes(o.kind))?.id;
      }
      if (!optionId) {
        // Unsupported permission (options=[]): the backend already supplied a safe
        // reason; do not POST a fabricated option. The official run-cancellation
        // action remains available through the runtime.
        return;
      }

      const url = `/assistant/sessions/${encodeURIComponent(
        sessionId,
      )}/permissions/${encodeURIComponent(approvalId)}`;
      fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ optionId }),
      })
        .then((res) => {
          if (res.status === 204) return; // accepted — await streamed authoritative state
          if (res.status === 409) return; // expired/terminal — do not auto-retry
          if (!res.ok) {
            // network/5xx: leave safely retryable and visible
            console.error("RTAI permission response failed", res.status);
          }
        })
        .catch((err) => console.error("RTAI permission response error", err));
    },
    [sessionId, props.approval],
  );

  return <ToolFallback {...props} respondToApproval={restResponder} />;
}
