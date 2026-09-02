/**
 * Minimal AssistantTransport state for RTAI.
 * Matches Python `backend/app/transport/assistant/models.py` and
 * `acp_state_projector.py` state shape.
 *
 * Official tool-call shape verified against pinned @assistant-ui/react 0.15.17
 * and @assistant-ui/core 0.15.17:
 * - ToolCallMessagePart fields: toolCallId, toolName, args, argsText, result, isError, artifact (optional)
 * - No custom status, locations, sequence, progress
 */

export type BackendTextPart = { type: "text"; text: string };
export type BackendReasoningPart = { type: "reasoning"; text: string };
export type BackendToolCallApprovalOption = {
  id: string;
  kind: string;
  label?: string;
  description?: string;
};

export type BackendToolCallApproval = {
  id: string;
  // approved is absent while pending (Assistant UI derives requires-action);
  // set to true/false once the user's choice is resolved.
  approved?: boolean;
  reason?: string;
  isAutomatic?: boolean;
  optionId?: string;
  options?: BackendToolCallApprovalOption[];
  resolution?: "cancelled" | "expired";
};

export type BackendToolCallPart = {
  type: "tool-call";
  toolCallId: string;
  toolName: string;
  args: Record<string, unknown>;
  argsText: string;
  result?: unknown;
  isError?: boolean;
  artifact?: unknown;
  approval?: BackendToolCallApproval;
};

export type BackendImagePart = {
  type: "image";
  image: string; // data URL (image/*)
  filename?: string;
};

export type BackendFilePart = {
  type: "file";
  data?: string; // base64
  uri?: string;
  mimeType?: string;
  filename?: string;
};

export type BackendMessagePart =
  | BackendTextPart
  | BackendReasoningPart
  | BackendToolCallPart
  | BackendImagePart
  | BackendFilePart;

export type BackendMessage = {
  id: string;
  role: "user" | "assistant";
  parts: BackendMessagePart[];
};

// One capability option (exact adapter id + optional display label).
export type RtaiCapabilityItem = {
  id: string;
  label: string;
};

// Minimal namespaced capability state projected by the backend into
// AssistantTransport `state`. `null` means the adapter reported the category as
// unsupported; `[]` means available but currently empty. IDs (not labels) are the
// submitted selection values. `error` carries a safe, payload-free message after
// an adapter rejects a selection.
export type RtaiCapabilitiesState = {
  initialized: boolean;
  agent: RtaiCapabilityItem | null;
  agents: RtaiCapabilityItem[] | null;
  models: RtaiCapabilityItem[] | null;
  modes: RtaiCapabilityItem[] | null;
  thinkingOptions: RtaiCapabilityItem[] | null;
  selected: {
    agent: string | null;
    model: string | null;
    mode: string | null;
    thinking: string | null;
  };
  error: { kind: string; message: string } | null;
};

// Minimal, READ-ONLY, FRONTEND-DERIVED status of in-flight capability commands.
// This is NOT authoritative and is never written by the backend; the converter
// derives it from the official `connectionMetadata.pendingCommands` so the UI can
// disable controls while a command is queued/in transit. It must not be mirrored
// into the server-projected `rtaiCapabilities` nor into any store.
export type RtaiCapabilitiesPending = {
  refresh: boolean;
  agent: boolean;
  model: boolean;
  mode: boolean;
  thinking: boolean;
};

export type RtaiAssistantState = {
  sessionId?: string;
  cwd?: string;
  messages: BackendMessage[];
  status: "ready" | "running" | "complete" | "error" | "cancelled";
  error?: string;
  rtaiCapabilities?: RtaiCapabilitiesState;
  // Read-only, converter-derived flag for in-flight capability commands
  // (see RtaiCapabilitiesPending). Sourced from official pendingCommands.
  rtaiCapabilitiesPending?: RtaiCapabilitiesPending;
};
