"use client";

import { generateId } from "../state/chatStore";
import { useChatStore } from "../state/chatStore";
import type { PermissionOption, PermissionRequest } from "../types/protocol";

// Determine which option to use for "allow" vs "deny" based on the ACP
// SDK's `kind` field (allow-once, allow-always, reject-once, reject-always).
// Falls back to first-option-is-allow / last-option-is-deny when kinds are
// absent, which matches the common ACP pattern of { allow, deny }.
function pickAllowOption(options: PermissionOption[]): string | null {
  const allow = options.find(
    (o) => o.kind === "allow-once" || o.kind === "allow-always",
  );
  if (allow) return allow.id;
  return options.length > 0 ? options[0]!.id : null;
}

function pickDenyOption(options: PermissionOption[]): string | null {
  const deny = options.find(
    (o) => o.kind === "reject-once" || o.kind === "reject-always",
  );
  if (deny) return deny.id;
  return options.length > 1 ? options[options.length - 1]!.id : null;
}

// A single permission request card. Renders one or two buttons depending on
// whether both allow and deny options are available.
function PermissionCard({ request }: { request: PermissionRequest }) {
  const sendCommand = useChatStore((s) => s.sendCommand);
  const sessionId = useChatStore((s) => s.sessionId);
  const turnId = useChatStore((s) => s.turnId);
  const respondToPermission = useChatStore((s) => s.respondToPermission);

  const allowId = pickAllowOption(request.options);
  const denyId = pickDenyOption(request.options);
  const hasBoth = allowId !== null && denyId !== null && allowId !== denyId;

  const handleAllow = () => {
    if (!sendCommand || !allowId) return;
    sendCommand({
      protocol_version: 1,
      request_id: generateId(),
      type: "permission_response",
      session_id: sessionId,
      turn_id: turnId,
      permission_request_id: request.permission_request_id,
      option_id: allowId,
    });
    respondToPermission(request.permission_request_id, allowId);
  };

  const handleDeny = () => {
    if (!sendCommand || !denyId) return;
    sendCommand({
      protocol_version: 1,
      request_id: generateId(),
      type: "permission_response",
      session_id: sessionId,
      turn_id: turnId,
      permission_request_id: request.permission_request_id,
      option_id: denyId,
    });
    respondToPermission(request.permission_request_id, denyId);
  };

  const toolTitle = request.title ?? request.kind ?? "Tool permission";
  const allowLabel =
    allowId !== null
      ? request.options.find((o) => o.id === allowId)?.label ?? "Allow"
      : "Allow";
  const denyLabel =
    denyId !== null
      ? request.options.find((o) => o.id === denyId)?.label ?? "Deny"
      : "Deny";

  return (
    <div
      className="rounded-xl border border-interactive bg-surface-elevated p-3"
      role="region"
      aria-label="Permission request"
    >
      {/* Header */}
      <div className="mb-2 flex items-center gap-2">
        <span
          className="inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-status-warning text-status-warning-foreground text-xs font-bold"
          aria-hidden="true"
        >
          !
        </span>
        <p className="text-sm font-medium text-foreground">{toolTitle}</p>
      </div>

      {/* Description / raw input preview */}
      {request.raw_input && Object.keys(request.raw_input).length > 0 && (
        <pre className="mb-2 max-h-20 overflow-y-auto rounded-lg bg-surface-muted px-2 py-1.5 text-xs text-muted-foreground font-mono">
          {JSON.stringify(request.raw_input, null, 2)}
        </pre>
      )}

      {/* Options */}
      <div className="flex flex-wrap gap-2">
        {allowId && (
          <button
            type="button"
            onClick={handleAllow}
            aria-label={`Allow ${allowLabel.toLowerCase()} for ${toolTitle}`}
            data-testid="permission-allow"
            className="flex h-8 items-center rounded-lg bg-status-success px-3 text-xs font-medium text-status-success-foreground transition-opacity hover:opacity-85 focus-visible:ring-2 focus-visible:ring-interactive-focus-ring focus-visible:ring-offset-2"
          >
            {allowLabel}
          </button>
        )}
        {hasBoth && (
          <button
            type="button"
            onClick={handleDeny}
            aria-label={`Deny ${denyLabel.toLowerCase()} for ${toolTitle}`}
            data-testid="permission-deny"
            className="flex h-8 items-center rounded-lg bg-status-error px-3 text-xs font-medium text-status-error-foreground transition-opacity hover:opacity-85 focus-visible:ring-2 focus-visible:ring-interactive-focus-ring focus-visible:ring-offset-2"
          >
            {denyLabel}
          </button>
        )}
      </div>
    </div>
  );
}

// PermissionDialog renders all pending permission requests as stacked cards
// above the composer. Hidden when autoApprove is on or no permissions pending.
export function PermissionDialog() {
  const pendingPermissions = useChatStore((s) => s.pendingPermissions);
  const autoApprove = useChatStore((s) => s.autoApprove);

  if (pendingPermissions.size === 0) return null;
  if (autoApprove) return null;

  const entries = Array.from(pendingPermissions.entries());

  return (
    <div
      className="flex flex-col gap-2 py-2"
      role="region"
      aria-label="Permission requests"
      aria-live="polite"
    >
      {entries.map(([id, request]) => (
        <PermissionCard key={id} request={request} />
      ))}
    </div>
  );
}
