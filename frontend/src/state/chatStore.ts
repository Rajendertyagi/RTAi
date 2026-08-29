import { create } from "zustand";
import { devtools } from "zustand/middleware";
import type {
  ServerEvent,
  ClientCommand,
  CapabilityItem,
  CommandItem,
  PermissionOption,
  PermissionRequest,
  ToolCall,
  ToolLocation,
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

export interface ChatState {
  // Connection
  connected: boolean;
  connectionState: "disconnected" | "connecting" | "connected";
  agentInfo: string;

  // Session
  sessionId: string;
  turnId: string;
  messageId: string;

  // Messages
  messages: ChatMessage[];
  activeTurnId: string | null;
  activeMessageId: string | null;

  // Capabilities (runtime-discovered, never hardcoded)
  agents: CapabilityItem[];
  models: CapabilityItem[];
  modes: CapabilityItem[];
  commands: CommandItem[];
  thinkingLevels: string[];

  // Selections
  selectedAgent: string | null;
  selectedModel: string | null;
  selectedMode: string | null;
  thinkingLevel: string;

  // Tool activity
  pendingPermissions: Map<string, PermissionRequest>;

  // Actions
  setConnected: (state: ChatState["connected"]) => void;
  setConnectionState: (state: ChatState["connectionState"]) => void;
  setAgentInfo: (name: string) => void;
  handleMessage: (event: ServerEvent) => void;
  sendCommand: (command: ClientCommand) => void;
  selectAgent: (agentId: string) => void;
  selectModel: (modelId: string) => void;
  selectMode: (modeId: string) => void;
  setThinkingLevel: (level: string) => void;
  respondToPermission: (requestId: string, optionId: string) => void;
  resetSession: () => void;
}

const generateId = () => `id-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;

const initialState: Omit<ChatState, keyof ReturnType<typeof create>> = {
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
          case "status":
            if (event.state === "ready") {
              set({ connectionState: "connected", connected: true });
            } else if (event.state === "starting") {
              set({ connectionState: "connecting" });
            } else {
              set({ connectionState: "disconnected", connected: false });
            }
            break;

          case "agent_info":
            set({ agentInfo: event.name });
            break;

          case "agents_available":
            if (event.available !== false && event.agents.length > 0) {
              set({ agents: event.agents });
              // Auto-select first agent if none selected
              if (!state.selectedAgent) {
                set({ selectedAgent: event.agents[0].id });
              }
            }
            break;

          case "agent_selected":
            if (event.session_id === state.sessionId) {
              set({ selectedAgent: event.agent_id });
            }
            break;

          case "models_available":
            if (event.available !== false && event.models.length > 0) {
              set({ models: event.models });
              if (!state.selectedModel) {
                set({ selectedModel: event.models[0].id });
              }
            }
            break;

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

          case "user_message":
            if (event.session_id === state.sessionId) {
              const newMessage = {
                id: event.message_id,
                role: "user" as const,
                text: event.text,
                tools: [],
                timestamp: Date.now(),
              };
              set({
                messages: [...state.messages, newMessage],
                activeTurnId: event.turn_id,
                activeMessageId: event.message_id,
              });
            }
            break;

          case "delta":
            if (event.session_id === state.sessionId && event.turn_id === state.activeTurnId) {
              // Find or create assistant message for this turn
              const assistantMsgIdx = state.messages.findLastIndex(
                (m) => m.role === "assistant" && m.id === event.message_id
              );
              if (assistantMsgIdx >= 0) {
                set({
                  messages: state.messages.map((m, i) =>
                    i === assistantMsgIdx
                      ? { ...m, text: m.text + event.text }
                      : m
                  ),
                });
              } else {
                const newMessage = {
                  id: `msg-${Date.now()}`,
                  role: "assistant" as const,
                  text: event.text,
                  tools: [],
                  timestamp: Date.now(),
                };
                set({
                  messages: [...state.messages, newMessage],
                  activeMessageId: newMessage.id,
                });
              }
            }
            break;

          case "done":
            if (event.session_id === state.sessionId) {
              set({ activeTurnId: null });
            }
            break;

          case "tool_start":
            if (event.session_id === state.sessionId && event.turn_id === state.activeTurnId) {
              const toolCall: ToolCall = {
                id: event.tool_call_id,
                title: event.title,
                kind: event.kind,
                status: "running" as ToolStatus,
                locations: event.locations,
                rawInput: event.raw_input,
              };
              // Add to last assistant message or create new one
              set({
                messages: state.messages.map((m, i) => {
                  if (i === state.messages.length - 1 && m.role === "assistant") {
                    return { ...m, tools: [...m.tools, toolCall] };
                  }
                  return m;
                }).concat(state.messages[state.messages.length - 1]?.role !== "assistant"
                  ? [{ id: `msg-${Date.now()}`, role: "assistant" as const, text: "", tools: [toolCall], timestamp: Date.now() }]
                  : []
                ),
              });
            }
            break;

          case "tool_update":
            if (event.session_id === state.sessionId && event.turn_id === state.activeTurnId) {
              set({
                messages: state.messages.map((m) => ({
                  ...m,
                  tools: m.tools.map((t) =>
                    t.id === event.tool_call_id
                      ? {
                          ...t,
                          status: (event.status ?? t.status) as ToolStatus,
                          content: event.content ?? t.content,
                          locations: event.locations ?? t.locations,
                        }
                      : t
                  ),
                })),
              });
            }
            break;

          case "tool_result":
            if (event.session_id === state.sessionId && event.turn_id === state.activeTurnId) {
              set({
                messages: state.messages.map((m) => ({
                  ...m,
                  tools: m.tools.map((t) =>
                    t.id === event.tool_call_id
                      ? { ...t, status: event.status as ToolStatus, content: event.content }
                      : t
                  ),
                })),
              });
            }
            break;

          case "permission_request":
            if (event.session_id === state.sessionId) {
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
            }
            break;

          case "permission_result":
            if (event.session_id === state.sessionId) {
              const newMap = new Map(state.pendingPermissions);
              newMap.delete(event.permission_request_id);
              set({ pendingPermissions: newMap });
            }
            break;

          case "cancelled":
            if (event.session_id === state.sessionId) {
              set({ activeTurnId: null });
            }
            break;

          case "warning":
          case "error":
            // Log diagnostics — handled by toast/error components elsewhere
            console.warn("[RTAI]", event.type, event.message);
            break;
        }
      },

      sendCommand: (command: ClientCommand) => {
        // Command sending is handled by the socket hook, not the store
        // This is a placeholder for potential future direct command usage
      },

      selectAgent: (agentId: string) => {
        set({ selectedAgent: agentId });
      },

      selectModel: (modelId: string) => {
        set({ selectedModel: modelId });
      },

      selectMode: (modeId: string) => {
        set({ selectedMode: modeId });
      },

      setThinkingLevel: (level: string) => {
        set({ thinkingLevel: level });
      },

      respondToPermission: (requestId: string, optionId: string) => {
        const { sessionId, turnId } = get();
        // Permission response is sent via socket — store just updates UI state
        const newMap = new Map(get().pendingPermissions);
        newMap.delete(requestId);
        set({ pendingPermissions: newMap });
      },

      resetSession: () => {
        set({
          sessionId: generateId(),
          turnId: generateId(),
          messageId: generateId(),
          messages: [],
          activeTurnId: null,
          activeMessageId: null,
        });
      },
    }),
    { name: "RTAI Chat Store" }
  )
);
