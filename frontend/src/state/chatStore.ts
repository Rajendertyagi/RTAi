import { create } from "zustand";
import { devtools } from "zustand/middleware";
import type {
  ServerEvent,
  ClientCommand,
  CapabilityItem,
  CommandItem,
  PermissionRequest,
  ToolCall,
  ToolCallStatus,
  ToolStatus,
} from "../types/protocol";

// A single chat message in our backend format (before conversion to
// assistant-ui's ThreadMessageLike). Exported so the runtime can type its
// convertMessage callback against the raw external message shape.
export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  text: string;
  tools: ToolCall[];
  timestamp: number;
}

// Data half of the store. Kept separate from the actions so `initialState`
// can be typed without the broken `Omit<ChatState, keyof ReturnType<...>>`
// trick (which failed to strip the action methods).
export interface ChatStateData {
  connected: boolean;
  connectionState: "disconnected" | "connecting" | "connected";
  agentInfo: string;

  sessionId: string;
  turnId: string;
  messageId: string;

  messages: ChatMessage[];
  activeTurnId: string | null;
  activeMessageId: string | null;

  // Capabilities (runtime-discovered, never hardcoded)
  agents: CapabilityItem[];
  models: CapabilityItem[];
  modes: CapabilityItem[];
  commands: CommandItem[];
  thinkingLevels: string[];

  selectedAgent: string | null;
  selectedModel: string | null;
  selectedMode: string | null;
  thinkingLevel: string;

  pendingPermissions: Map<string, PermissionRequest>;
}

export interface ChatStateActions {
  setConnected: (connected: boolean) => void;
  setConnectionState: (state: ChatStateData["connectionState"]) => void;
  setAgentInfo: (name: string) => void;
  handleMessage: (event: ServerEvent) => void;
  selectAgent: (agentId: string) => void;
  selectModel: (modelId: string) => void;
  selectMode: (modeId: string) => void;
  setThinkingLevel: (level: string) => void;
  respondToPermission: (requestId: string, optionId: string) => void;
  resetSession: () => void;
}

export type ChatState = ChatStateData & ChatStateActions;

const generateId = () => `id-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;

const initialState: ChatStateData = {
  connected: false,
  connectionState: "disconnected",
  agentInfo: "",
  sessionId: generateId(),
  turnId: generateId(),
  messageId: generateId(),
  messages: [],
  activeTurnId: null,
  activeMessageId: null,
  agents: [],
  models: [],
  modes: [],
  commands: [],
  thinkingLevels: [],
  selectedAgent: null,
  selectedModel: null,
  selectedMode: null,
  thinkingLevel: "off",
  pendingPermissions: new Map(),
};

// Index of the assistant message the current turn is streaming into, or -1.
// The turn's assistant message is created on the first delta/tool_start and
// then tracked by activeMessageId, so later deltas append to it instead of
// leaking into a previous turn's message.
function findActiveAssistantIndex(
  messages: ChatMessage[],
  activeMessageId: string | null,
): number {
  if (!activeMessageId) return -1;
  return messages.findIndex(
    (m) => m.id === activeMessageId && m.role === "assistant",
  );
}

export const useChatStore = create<ChatState>()(
  devtools(
    (set, get) => ({
      ...initialState,

      setConnected: (connected) => set({ connected }),
      setConnectionState: (connectionState) => set({ connectionState }),
      setAgentInfo: (agentInfo) => set({ agentInfo }),

      handleMessage: (event: ServerEvent) => {
        const state = get();

        switch (event.type) {
          case "status": {
            // Protocol states are starting|ready|disconnected; map them onto
            // the store's connectionState union.
            if (event.state === "ready") {
              set({ connectionState: "connected", connected: true });
            } else if (event.state === "starting") {
              set({ connectionState: "connecting" });
            } else {
              set({ connectionState: "disconnected", connected: false });
            }
            break;
          }

          case "agent_info":
            set({ agentInfo: event.name });
            break;

          case "agents_available": {
            if (event.available !== false && event.agents.length > 0) {
              set({ agents: event.agents });
              const first = event.agents[0];
              if (!state.selectedAgent && first) {
                set({ selectedAgent: first.id });
              }
            }
            break;
          }

          case "agent_selected":
            if (event.session_id === state.sessionId) {
              set({ selectedAgent: event.agent_id });
            }
            break;

          case "models_available": {
            if (event.available !== false && event.models.length > 0) {
              set({ models: event.models });
              const first = event.models[0];
              if (!state.selectedModel && first) {
                set({ selectedModel: first.id });
              }
            }
            break;
          }

          case "model_selected":
            set({ selectedModel: event.model_id });
            break;

          case "modes_available":
            if (event.available !== false && event.modes.length > 0) {
              set({ modes: event.modes });
            }
            break;

          case "mode_selected":
            set({ selectedMode: event.mode_id });
            break;

          case "thinking_available":
            if (event.available !== false) {
              set({ thinkingLevels: event.thinking_levels });
            }
            break;

          case "thinking_selected":
            set({ thinkingLevel: event.level });
            break;

          case "commands_available":
            if (event.available !== false) {
              set({ commands: event.commands });
            }
            break;

          case "user_message": {
            if (event.session_id !== state.sessionId) break;
            const newMessage: ChatMessage = {
              id: event.message_id,
              role: "user",
              text: event.text,
              tools: [],
              timestamp: Date.now(),
            };
            set({
              messages: [...state.messages, newMessage],
              activeTurnId: event.turn_id,
              activeMessageId: event.message_id,
            });
            break;
          }

          case "delta": {
            if (
              event.session_id !== state.sessionId ||
              event.turn_id !== state.activeTurnId
            ) {
              break;
            }
            // delta carries no message_id (per protocol v1), so the streaming
            // target is tracked by activeMessageId: the first delta creates
            // the assistant message, later ones append to it.
            const idx = findActiveAssistantIndex(
              state.messages,
              state.activeMessageId,
            );
            if (idx >= 0) {
              set({
                messages: state.messages.map((m, i) =>
                  i === idx ? { ...m, text: m.text + event.text } : m,
                ),
              });
            } else {
              const newMessage: ChatMessage = {
                id: `msg-${Date.now()}`,
                role: "assistant",
                text: event.text,
                tools: [],
                timestamp: Date.now(),
              };
              set({
                messages: [...state.messages, newMessage],
                activeMessageId: newMessage.id,
              });
            }
            break;
          }

          case "done":
            if (event.session_id === state.sessionId) {
              set({ activeTurnId: null });
            }
            break;

          case "tool_start": {
            if (
              event.session_id !== state.sessionId ||
              event.turn_id !== state.activeTurnId
            ) {
              break;
            }
            const toolCall: ToolCall = {
              id: event.tool_call_id,
              title: event.title,
              kind: event.kind,
              status: "running",
              locations: event.locations,
              rawInput: event.raw_input,
            };
            const idx = findActiveAssistantIndex(
              state.messages,
              state.activeMessageId,
            );
            if (idx >= 0) {
              set({
                messages: state.messages.map((m, i) =>
                  i === idx ? { ...m, tools: [...m.tools, toolCall] } : m,
                ),
              });
            } else {
              const newMessage: ChatMessage = {
                id: `msg-${Date.now()}`,
                role: "assistant",
                text: "",
                tools: [toolCall],
                timestamp: Date.now(),
              };
              set({
                messages: [...state.messages, newMessage],
                activeMessageId: newMessage.id,
              });
            }
            break;
          }

          case "tool_update": {
            if (
              event.session_id !== state.sessionId ||
              event.turn_id !== state.activeTurnId
            ) {
              break;
            }
            set({
              messages: state.messages.map((m) => ({
                ...m,
                tools: m.tools.map((t) =>
                  t.id === event.tool_call_id
                    ? {
                        ...t,
                        status: (event.status ?? t.status) as ToolCallStatus,
                        content: event.content ?? t.content,
                        locations: event.locations ?? t.locations,
                      }
                    : t,
                ),
              })),
            });
            break;
          }

          case "tool_result": {
            if (
              event.session_id !== state.sessionId ||
              event.turn_id !== state.activeTurnId
            ) {
              break;
            }
            set({
              messages: state.messages.map((m) => ({
                ...m,
                tools: m.tools.map((t) =>
                  t.id === event.tool_call_id
                    ? {
                        ...t,
                        status: event.status as ToolStatus,
                        content: event.content ?? t.content,
                        locations: event.locations ?? t.locations,
                      }
                    : t,
                ),
              })),
            });
            break;
          }

          case "permission_request": {
            if (event.session_id !== state.sessionId) break;
            const request: PermissionRequest = {
              permission_request_id: event.permission_request_id,
              tool_call_id: event.tool_call_id,
              options: event.options,
              title: event.title,
              kind: event.kind,
              raw_input: event.raw_input,
              content: event.content,
              locations: event.locations,
            };
            const newMap = new Map(state.pendingPermissions);
            newMap.set(event.permission_request_id, request);
            set({ pendingPermissions: newMap });
            break;
          }

          case "permission_result": {
            if (event.session_id !== state.sessionId) break;
            const newMap = new Map(state.pendingPermissions);
            newMap.delete(event.permission_request_id);
            set({ pendingPermissions: newMap });
            break;
          }

          case "cancelled":
            if (event.session_id === state.sessionId) {
              set({ activeTurnId: null });
            }
            break;

          case "warning":
          case "error":
            // Diagnostics only — surfaced by toast/error UI elsewhere.
            console.warn("[RTAI]", event.type, event.message);
            break;
        }
      },

      selectAgent: (agentId) => set({ selectedAgent: agentId }),
      selectModel: (modelId) => set({ selectedModel: modelId }),
      selectMode: (modeId) => set({ selectedMode: modeId }),
      setThinkingLevel: (level) => set({ thinkingLevel: level }),

      respondToPermission: (requestId) => {
        // The actual permission_response is sent over the socket by the UI;
        // the store only clears the pending prompt.
        const newMap = new Map(get().pendingPermissions);
        newMap.delete(requestId);
        set({ pendingPermissions: newMap });
      },

      resetSession: () =>
        set({
          sessionId: generateId(),
          turnId: generateId(),
          messageId: generateId(),
          messages: [],
          activeTurnId: null,
          activeMessageId: null,
        }),
    }),
    { name: "RTAI Chat Store" },
  ),
);
