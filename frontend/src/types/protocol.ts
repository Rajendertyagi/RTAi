// RTAI chat protocol — client side types (protocol v1).
// Fresh, forward-compatible definitions. Add new event/command variants here;
// the reducer and transport stay open to them.

export const PROTOCOL_VERSION = 1 as const;

export type Role = "user" | "agent" | "error";

export type MessageStatus = "complete" | "streaming" | "error";

export type ConnectionState = "disconnected" | "connecting" | "connected" | "error";

export type ToolStatus = "pending" | "running" | "success" | "error" | "cancelled";

export interface CapabilityItem {
  id: string;
  label: string;
  description?: string;
  // Permission options carry a kind ("allow" | "deny" | ...) so the UI can
  // auto-pick the allow option when auto-accept is enabled.
  kind?: string;
  // Slash commands may advertise the argument they expect.
  input_hint?: string;
}

export interface ModelCapabilities {
  tools?: boolean;
  attachments?: boolean;
  vision?: boolean;
  thinking_levels?: string[];
}

export interface AttachmentRef {
  id: string;
  name: string;
  mime_type: string;
  size_bytes: number;
  kind?: string;
}

export interface ToolCall {
  id: string;
  title?: string;
  status: ToolStatus;
  content?: unknown;
}

export interface PermissionRequest {
  permission_request_id: string;
  tool_call_id: string;
  options: CapabilityItem[];
}

export interface Message {
  id: string;
  role: Role;
  text: string;
  status: MessageStatus;
  tools?: ToolCall[];
  attachments?: AttachmentRef[];
  permission?: PermissionRequest;
}

export interface Unavailable {
  code: string;
  message: string;
}

export interface Capabilities {
  agents: CapabilityItem[];
  models: CapabilityItem[];
  thinkingLevels: string[];
  commands: CapabilityItem[];
  // Why a section could not be discovered. Backend omits the items array
  // entirely when a section is unavailable, so the reason is the only signal.
  unavailable: {
    agents?: Unavailable;
    models?: Unavailable;
    thinking?: Unavailable;
    commands?: Unavailable;
  };
}

export interface SessionItem {
  id: string;
  title: string;
  active: boolean;
}

// ===== Server -> client events (extensible) =====
export type ServerEvent =
  | { type: "status"; state: "starting" | "ready" | "disconnected"; cwd?: string }
  | { type: "error"; message: string; code?: string }
  | { type: "agent_info"; name: string }
  | { type: "agents_available"; agents?: CapabilityItem[]; available?: boolean; reason_code?: string; reason_message?: string }
  | { type: "models_available"; models?: CapabilityItem[]; available?: boolean; reason_code?: string; reason_message?: string }
  | { type: "agent_selected"; agent_id: string }
  | { type: "model_selected"; model_id: string }
  | { type: "thinking_available"; thinking_levels?: string[]; available?: boolean; reason_code?: string; reason_message?: string }
  | { type: "thinking_selected"; level: string }
  | { type: "commands_available"; commands?: CapabilityItem[]; available?: boolean; reason_code?: string; reason_message?: string }
  | { type: "user_message"; text: string }
  | { type: "delta"; text: string; sequence?: number }
  | { type: "done"; reason?: "completed" | "cancelled" | "error" }
  | { type: "tool_start"; tool_call_id: string; title: string; status?: ToolStatus }
  | { type: "tool_result"; tool_call_id: string; status: ToolStatus; content?: unknown }
  | { type: "permission_request"; permission_request_id: string; tool_call_id: string; options: CapabilityItem[] }
  | { type: "permission_result"; permission_request_id: string; option_id?: string }
  | { type: "raw"; event: string; data: unknown };

export function isServerEvent(value: unknown): value is ServerEvent {
  return (
    typeof value === "object" &&
    value !== null &&
    typeof (value as { type?: unknown }).type === "string"
  );
}

// ===== Client -> server commands =====
interface BaseCommand {
  protocol_version: typeof PROTOCOL_VERSION;
  request_id: string;
  session_id: string;
}

export type ClientCommand =
  | (BaseCommand & {
      type: "prompt";
      turn_id: string;
      message_id: string;
      text: string;
      attachments?: AttachmentRef[];
    })
  | (BaseCommand & { type: "cancel"; turn_id: string })
  | (BaseCommand & { type: "select_agent"; agent_id: string })
  | (BaseCommand & { type: "select_model"; model_id: string })
  | (BaseCommand & { type: "set_thinking"; level: string })
  | (BaseCommand & { type: "permission_response"; turn_id: string; permission_request_id: string; option_id: string });
