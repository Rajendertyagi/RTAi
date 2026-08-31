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
  UnavailableReason,
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

// A selection request awaiting authoritative confirmation from the backend.
// Keyed in the store by the Protocol v1 `request_id` so multiple, distinct
// pending selections (e.g. model + thinking) can coexist without a single
// global "pending" boolean.
export interface PendingSelection {
  type: "agent" | "model" | "mode" | "thinking";
  option: string;
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
  promptRequestId: string | null;
  cancelRequestId: string | null;
  cancelPending: boolean;
  cancelError: { code?: string; message: string } | null;

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

  // Unavailability reasons (runtime-provided, never invented client-side).
  // Captured from `*_available` events carrying `available: false` so the
  // composer can render an honest, disabled control with the real reason.
  agentsReason: UnavailableReason | null;
  modelsReason: UnavailableReason | null;
  modesReason: UnavailableReason | null;
  thinkingReason: UnavailableReason | null;
  commandsReason: UnavailableReason | null;

  // Selection pending correlation: request_id -> { type, option }.
  pendingSelections: Map<string, PendingSelection>;
  // Last normalized selection failure (cleared on success / new turn).
  lastError: { code?: string; message: string } | null;

  // Transport dispatch, registered by the runtime provider. The store never
  // talks to the WebSocket directly — it calls this callback so the
  // established transport boundary stays the single owner of the socket.
  sendCommand: ((cmd: ClientCommand) => void) | null;

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
  registerSend: (send: (cmd: ClientCommand) => void) => void;
  respondToPermission: (requestId: string, optionId: string) => void;
  resetSession: () => void;
}

export type ChatState = ChatStateData & ChatStateActions;

// Centralized identifier generator. Every RTAI identity (session, turn,
// message, request) is a UUID v4 from the Web Crypto API. Never build
// identifiers from Date.now() and never embed one identity inside another.
export const generateId = () => crypto.randomUUID();

// The set of turn-scoped fields cleared when the current turn terminates
// (done/error/cancel) or when dispatch fails. Only the matching turn is
// cleared; a late terminal event from an older turn is ignored.
const clearTurnState = {
  activeTurnId: null,
  activeMessageId: null,
  promptRequestId: null,
  cancelRequestId: null,
  cancelPending: false,
  cancelError: null,
} as const;

// Derive a stored reason object from a backend `available: false` frame.
// Falls back to a neutral code/message only when the backend omitted both,
// never to a fabricated "default" capability value.
const reasonFrom = (ev: {
  reason_code?: string;
  reason_message?: string;
}): UnavailableReason => ({
  reason_code: ev.reason_code ?? "not_exposed_by_provider",
  reason_message: ev.reason_message ?? "Not available",
});

const initialState: ChatStateData = {
  connected: false,
  connectionState: "disconnected",
  agentInfo: "",
  sessionId: generateId(),
  turnId: generateId(),
  messageId: generateId(),
  promptRequestId: null,
  cancelRequestId: null,
  cancelPending: false,
  cancelError: null,
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
  thinkingLevel: "",
  agentsReason: null,
  modelsReason: null,
  modesReason: null,
  thinkingReason: null,
  commandsReason: null,
  pendingSelections: new Map(),
  lastError: null,
  sendCommand: null,
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
              // Connection lost — in-flight selections and the active turn can
              // no longer resolve, so clear their pending state.
              if (state.pendingSelections.size > 0) {
                set({ pendingSelections: new Map() });
              }
              if (state.activeTurnId !== null || state.promptRequestId !== null) {
                set(clearTurnState);
              }
            }
            break;
          }

          case "agent_info":
            set({ agentInfo: event.name });
            break;

          case "agents_available": {
            if (event.available === false) {
              // Unavailable: store the runtime reason, drop any stale items,
              // and do NOT invent a fake list or auto-select.
              set({ agents: [], agentsReason: reasonFrom(event) });
            } else {
              set({ agents: event.agents, agentsReason: null });
            }
            // Never auto-select first: the authoritative value arrives via
            // `agent_selected`. Keep `selectedAgent` untouched.
            break;
          }

          case "agent_selected":
            if (event.session_id === state.sessionId) {
              set({ selectedAgent: event.agent_id });
            }
            break;

          case "models_available": {
            if (event.available === false) {
              set({ models: [], modelsReason: reasonFrom(event) });
            } else {
              set({ models: event.models, modelsReason: null });
            }
            break;
          }

          case "model_selected":
            set({ selectedModel: event.model_id });
            break;

          case "modes_available": {
            if (event.available === false) {
              set({ modes: [], modesReason: reasonFrom(event) });
            } else {
              set({ modes: event.modes, modesReason: null });
            }
            break;
          }

          case "mode_selected":
            set({ selectedMode: event.mode_id });
            break;

          case "thinking_available": {
            if (event.available === false) {
              set({ thinkingLevels: [], thinkingReason: reasonFrom(event) });
            } else {
              set({
                thinkingLevels: event.thinking_levels,
                thinkingReason: null,
              });
            }
            break;
          }

          case "thinking_selected":
            set({ thinkingLevel: event.level });
            break;

          case "commands_available": {
            if (event.available === false) {
              set({ commands: [], commandsReason: reasonFrom(event) });
            } else {
              set({ commands: event.commands, commandsReason: null });
            }
            break;
          }

          case "command_result": {
            // Cancel acknowledgements are correlated by the cancel command's
            // own request_id. On failure, clear the pending cancel flag and
            // surface the backend error while retaining the active prompt
            // state. On success, keep the turn correlated until its matching
            // terminal `done` arrives (cleared there).
            if (event.command === "cancel") {
              if (!event.success) {
                set({
                  cancelPending: false,
                  cancelError: {
                    code: event.code,
                    message: event.message ?? "Cancel failed",
                  },
                });
              } else {
                set({ cancelPending: false, cancelError: null });
              }
              break;
            }
            // Correlate by request_id. A matching pending entry means this
            // result resolves a selection we initiated.
            const pending = state.pendingSelections.get(event.request_id);
            if (!pending) break; // foreign / unknown result — ignore.
            const next = new Map(state.pendingSelections);
            next.delete(event.request_id);
            if (!event.success) {
              // Failure: drop the pending flag but KEEP the previous
              // authoritative selection; surface the normalized error.
              set({
                pendingSelections: next,
                lastError: {
                  code: event.code,
                  message: event.message ?? "Selection failed",
                },
              });
            } else {
              set({ pendingSelections: next, lastError: null });
            }
            break;
          }

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
            // Match the stable current turn (pending/active) by turn_id, not
            // only activeTurnId: cancellation must clear state before a
            // user_message establishes activeTurnId. A late terminal event
            // from an older turn is ignored.
            if (
              event.session_id === state.sessionId &&
              event.turn_id === state.turnId
            ) {
              set(clearTurnState);
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
            // Legacy defensive handler: the backend now emits a single
            // `done {reason: "cancelled"}` instead of a separate `cancelled`
            // event, but clear matching state if one still arrives.
            if (
              event.session_id === state.sessionId &&
              event.turn_id === state.turnId
            ) {
              set(clearTurnState);
            }
            break;

          case "warning":
            // Diagnostics only — surfaced by toast/error UI elsewhere.
            console.warn("[RTAI]", event.type, event.message);
            break;

          case "error":
            // A terminal error for the current turn clears its pending state
            // and surfaces the message as `lastError` so the StatusBar can
            // display it. Diagnostic errors without turn correlation are
            // logged; errors that carry a known backend code but no turn
            // (e.g. `history_degraded`) are surfaced so the user sees why.
            console.warn("[RTAI]", event.type, event.message);
            if (
              event.session_id === state.sessionId &&
              event.turn_id === state.turnId
            ) {
              set({
                activeTurnId: null,
                activeMessageId: null,
                promptRequestId: null,
                cancelRequestId: null,
                cancelPending: false,
                cancelError: null,
                lastError: { code: event.code, message: event.message },
              });
            } else if (!event.code) {
              // No turn correlation and no code — surface it as a standalone
              // error rather than silently swallowing it.
              set({ lastError: { code: event.code, message: event.message } });
            }
            break;
        }
      },

      selectAgent: (agentId) => {
        const { sendCommand, sessionId, selectedAgent, pendingSelections } =
          get();
        if (!sendCommand || agentId === selectedAgent) return;
        const requestId = generateId();
        const next = new Map(pendingSelections);
        next.set(requestId, { type: "agent", option: agentId });
        set({ pendingSelections: next });
        sendCommand({
          protocol_version: 1,
          request_id: requestId,
          type: "select_agent",
          session_id: sessionId,
          agent_id: agentId,
        });
      },

      selectModel: (modelId) => {
        const { sendCommand, sessionId, selectedModel, pendingSelections } =
          get();
        if (!sendCommand || modelId === selectedModel) return;
        const requestId = generateId();
        const next = new Map(pendingSelections);
        next.set(requestId, { type: "model", option: modelId });
        set({ pendingSelections: next });
        sendCommand({
          protocol_version: 1,
          request_id: requestId,
          type: "select_model",
          session_id: sessionId,
          model_id: modelId,
        });
      },

      selectMode: (modeId) => {
        const { sendCommand, sessionId, selectedMode, pendingSelections } =
          get();
        if (!sendCommand || modeId === selectedMode) return;
        const requestId = generateId();
        const next = new Map(pendingSelections);
        next.set(requestId, { type: "mode", option: modeId });
        set({ pendingSelections: next });
        sendCommand({
          protocol_version: 1,
          request_id: requestId,
          type: "select_mode",
          session_id: sessionId,
          mode_id: modeId,
        });
      },

      setThinkingLevel: (level) => {
        const { sendCommand, sessionId, thinkingLevel, pendingSelections } =
          get();
        if (!sendCommand || level === thinkingLevel) return;
        const requestId = generateId();
        const next = new Map(pendingSelections);
        next.set(requestId, { type: "thinking", option: level });
        set({ pendingSelections: next });
        sendCommand({
          protocol_version: 1,
          request_id: requestId,
          type: "set_thinking",
          session_id: sessionId,
          level,
        });
      },

      // The runtime provider registers its socket dispatch here. The store
      // then routes selection commands through this callback rather than
      // holding a WebSocket reference itself.
      registerSend: (send) => set({ sendCommand: send }),

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
          turnId: "",
          messageId: "",
          promptRequestId: null,
          cancelRequestId: null,
          cancelPending: false,
          cancelError: null,
          messages: [],
          activeTurnId: null,
          activeMessageId: null,
          pendingSelections: new Map(),
          lastError: null,
        }),
    }),
    { name: "RTAI Chat Store" },
  ),
);
