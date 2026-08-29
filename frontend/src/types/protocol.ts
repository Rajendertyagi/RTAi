// RTAI Protocol v1 — Client-side type definitions.
// Mirror of backend/app/api/protocol_v1.py + docs/EVENT_PROTOCOL.md
// Add new event/command variants here; the reducer stays open to them.

export const PROTOCOL_VERSION = 1 as const;

// === Envelope ===

export interface ProtocolEnvelope {
  protocol_version: typeof PROTOCOL_VERSION;
  session_id?: string;
  turn_id?: string;
  message_id?: string;
  sequence?: number;
  timestamp?: number;
  request_id?: string;
}

// === Backend → UI Events ===

export type ServerEvent =
  // Connection lifecycle
  | { type: "status"; state: "starting" | "ready" | "disconnected"; cwd?: string }
  | { type: "agent_info"; name: string }
  // Capabilities
  | { type: "agents_available"; agents: CapabilityItem[]; available?: boolean }
  | { type: "agent_selected"; session_id: string; agent_id: string }
  | { type: "models_available"; models: CapabilityItem[]; available?: boolean }
  | { type: "model_selected"; model_id: string }
  | { type: "modes_available"; modes: CapabilityItem[]; available?: boolean }
  | { type: "mode_selected"; mode_id: string }
  | { type: "thinking_available"; thinking_levels: string[]; model_id?: string; available?: boolean }
  | { type: "thinking_selected"; level: string; model_id?: string }
  | { type: "commands_available"; commands: CommandItem[]; available?: boolean }
  // Messages
  | { type: "user_message"; session_id: string; turn_id: string; message_id: string; text: string }
  | { type: "delta"; session_id: string; turn_id: string; sequence: number; text: string }
  | { type: "done"; session_id: string; turn_id: string; reason?: "completed" | "cancelled" | "error" }
  // Tool calls
  | { type: "tool_start"; session_id: string; turn_id: string; tool_call_id: string; title: string; kind?: string; status?: string; locations?: ToolLocation[]; raw_input?: Record<string, unknown> }
  | { type: "tool_update"; session_id: string; turn_id: string; tool_call_id: string; status?: string; content?: ToolContentBlock[]; locations?: ToolLocation[] }
  | { type: "tool_result"; session_id: string; turn_id: string; tool_call_id: string; status: ToolStatus; content?: ToolContentBlock[]; locations?: ToolLocation[]; error_message?: string }
  // Permissions
  | { type: "permission_request"; session_id: string; turn_id: string; permission_request_id: string; tool_call_id: string; title?: string; kind?: string; raw_input?: Record<string, unknown>; content?: ToolContentBlock[]; locations?: ToolLocation[]; options: PermissionOption[] }
  | { type: "permission_result"; session_id: string; turn_id: string; permission_request_id: string; option_id?: string }
  // Commands
  | { type: "command_result"; request_id: string; command: string; success: boolean; code?: string; message?: string; effective_value?: unknown }
  // Diagnostics
  | { type: "usage"; input_tokens?: number; output_tokens?: number }
  | { type: "queue_state"; pending: number }
  | { type: "timing"; total_ms?: number }
  | { type: "cancelled"; session_id: string; turn_id: string }
  | { type: "warning"; message: string }
  | { type: "error"; message: string; code?: string; recoverable?: boolean; request_id?: string; turn_id?: string; session_id?: string }
  | { type: "raw"; event: string; data: unknown };

// === UI → Backend Commands ===

export type ClientCommand =
  | { protocol_version: typeof PROTOCOL_VERSION; request_id: string; type: "prompt"; session_id: string; turn_id: string; message_id: string; text: string; attachments?: AttachmentRef[] }
  | { protocol_version: typeof PROTOCOL_VERSION; request_id: string; type: "cancel"; session_id: string; turn_id: string }
  | { protocol_version: typeof PROTOCOL_VERSION; request_id: string; type: "select_agent"; session_id: string; agent_id: string }
  | { protocol_version: typeof PROTOCOL_VERSION; request_id: string; type: "select_model"; session_id: string; model_id: string }
  | { protocol_version: typeof PROTOCOL_VERSION; request_id: string; type: "select_mode"; session_id: string; mode_id: string }
  | { protocol_version: typeof PROTOCOL_VERSION; request_id: string; type: "set_thinking"; session_id: string; level: string }
  | { protocol_version: typeof PROTOCOL_VERSION; request_id: string; type: "permission_response"; session_id: string; turn_id: string; permission_request_id: string; option_id: string };

// === Shared Types ===

export type ToolStatus = "success" | "error" | "cancelled" | "aborted" | "timeout";

export interface ToolLocation {
  path: string;
  line?: number;
}

export type ToolContentBlock =
  | { type: "content"; text?: string }
  | { type: "diff"; path: string; oldText?: string; newText: string }
  | { type: "terminal"; terminalId: string };

export interface CapabilityItem {
  id: string;
  label: string;
  description?: string;
  capabilities?: ModelCapabilities;
}

export interface ModelCapabilities {
  tools?: boolean;
  attachments?: boolean;
  vision?: boolean;
  thinking_levels?: string[];
}

export interface CommandItem {
  id: string;
  label: string;
  description?: string;
  input_hint?: string;
}

export interface PermissionOption {
  id: string;
  label: string;
  description?: string;
  kind?: string;
}

export interface AttachmentRef {
  id: string;
  name: string;
  mime_type: string;
  size_bytes: number;
  kind?: string;
}

// === Type Guards ===

export function isServerEvent(data: unknown): data is ServerEvent {
  if (typeof data !== "object" || data === null) return false;
  const evt = data as Record<string, unknown>;
  if (typeof evt.type !== "string") return false;
  if (evt.protocol_version !== PROTOCOL_VERSION) return false;
  // Known event types — reject unknown ones safely
  const knownTypes = new Set([
    "status", "agent_info",
    "agents_available", "agent_selected",
    "models_available", "model_selected",
    "modes_available", "mode_selected",
    "thinking_available", "thinking_selected",
    "commands_available",
    "user_message", "delta", "done",
    "tool_start", "tool_update", "tool_result",
    "permission_request", "permission_result",
    "command_result",
    "usage", "queue_state", "timing",
    "cancelled", "warning", "error", "raw",
  ]);
  return knownTypes.has(evt.type);
}

export function isClientCommand(data: unknown): data is ClientCommand {
  if (typeof data !== "object" || data === null) return false;
  const cmd = data as Record<string, unknown>;
  if (cmd.protocol_version !== PROTOCOL_VERSION) return false;
  if (typeof cmd.type !== "string") return false;
  const knownCommands = new Set(["prompt", "cancel", "select_agent", "select_model", "select_mode", "set_thinking", "permission_response"]);
  return knownCommands.has(cmd.type);
}
