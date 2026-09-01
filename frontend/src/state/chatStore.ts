import { create } from "zustand";
import { devtools } from "zustand/middleware";
import type {
  ThreadMessageLike,
  ThreadAssistantMessagePart,
  ThreadUserMessagePart,
  MessageStatus,
} from "@assistant-ui/react";
import type {
  ServerEvent,
  ClientCommand,
  CapabilityItem,
  CommandItem,
  PermissionRequest,
  UnavailableReason,
} from "../types/protocol";

// Discriminated union of store message types derived from ThreadMessageLike.
// User messages preserve ThreadUserMessagePart[] content and attachments;
// assistant messages use ThreadAssistantMessagePart[] content for streaming.
// The `role` discriminant lets TypeScript narrow content automatically.
export type UserChatMessage = ThreadMessageLike & {
  readonly role: "user";
  readonly id: string;
  readonly content: readonly ThreadUserMessagePart[];
};

export type AssistantChatMessage = ThreadMessageLike & {
  readonly role: "assistant";
  readonly id: string;
  readonly content: readonly ThreadAssistantMessagePart[];
};

export type ChatMessage = UserChatMessage | AssistantChatMessage;

// Tool-call part extracted from the official ThreadAssistantMessagePart union.
type ToolPart = Extract<
  ThreadAssistantMessagePart,
  { type: "tool-call" }
>;

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
  // Auto-approve all pending permissions without showing the dialog.
  // Per-session only (resets on resetSession); not persisted to localStorage.
  autoApprove: boolean;

  // Content-part correlation: `${turn_id}:${part_id}` → contentIndex.
  // Populated by part_start, used by part_delta/part_done, cleared on
  // turn terminal / disconnect / reset. Preserves duplicate-start
  // idempotence and permits late deltas.
  partCorrelations: Map<string, number>;
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
  setAutoApprove: (on: boolean) => void;
  setMessages: (messages: readonly ChatMessage[]) => void;
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
  autoApprove: false,
  partCorrelations: new Map(),
};

// Find the assistant message for a turn by its deterministic ID.
// Returns the message and its index, or null if not found.
function findByTurnId(
  messages: ChatMessage[],
  turnId: string,
): { msg: AssistantChatMessage; index: number } | null {
  const index = messages.findIndex(
    (m) => m.id === `asst-${turnId}` && m.role === "assistant",
  );
  if (index < 0) return null;
  return { msg: messages[index] as AssistantChatMessage, index };
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
              if (state.pendingPermissions.size > 0) {
                set({ pendingPermissions: new Map() });
              }
              if (state.activeTurnId !== null || state.promptRequestId !== null) {
                set(clearTurnState);
              }
              // Clear all part correlations — no partial streaming state
              // survives a disconnect.
              set({ partCorrelations: new Map() });
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
            // Skip if already exists (optimistic creation in onNew).
            const exists = state.messages.some(
              (m) => m.id === event.message_id,
            );
            if (exists) break;
            const userMsg: ChatMessage = {
              role: "user",
              id: event.message_id,
              content: [{ type: "text", text: event.text }],
              createdAt: new Date(),
            };
            set({
              messages: [...state.messages, userMsg],
              activeTurnId: event.turn_id,
              activeMessageId: event.message_id,
            });
            break;
          }

          case "done": {
            // Match the stable current turn (pending/active) by turn_id, not
            // only activeTurnId: cancellation must clear state before a
            // user_message establishes activeTurnId. A late terminal event
            // from an older turn is ignored.
            if (
              event.session_id !== state.sessionId ||
              event.turn_id !== state.turnId
            ) {
              break;
            }

            // Determine official terminal MessageStatus.
            let terminalStatus: MessageStatus;
            if (event.reason === "cancelled") {
              terminalStatus = { type: "incomplete", reason: "cancelled" };
            } else if (event.reason === "error") {
              terminalStatus = { type: "incomplete", reason: "error" };
            } else {
              terminalStatus = { type: "complete", reason: "stop" };
            }

            // Mark assistant message status immutably.
            const found = findByTurnId(state.messages, event.turn_id);
            let nextMessages = state.messages;
            if (found) {
              nextMessages = state.messages.map((m, i) =>
                i === found.index ? { ...m, status: terminalStatus } : m,
              );
            }

            // Clear correlations for this turn.
            const nextCorr = new Map(state.partCorrelations);
            const turnPrefix = `${event.turn_id}:`;
            for (const key of nextCorr.keys()) {
              if (key.startsWith(turnPrefix)) nextCorr.delete(key);
            }

            set({
              messages: nextMessages,
              partCorrelations: nextCorr,
              ...clearTurnState,
            });
            break;
          }

          case "tool_start": {
            if (
              event.session_id !== state.sessionId ||
              event.turn_id !== state.activeTurnId
            ) {
              break;
            }
            const toolPart: ToolPart = {
              type: "tool-call",
              toolCallId: event.tool_call_id,
              toolName: event.title ?? event.kind ?? "tool",
              args: (event.raw_input ?? {}) as ToolPart["args"],
              argsText: event.raw_input
                ? JSON.stringify(event.raw_input)
                : "",
            };
            const found = findByTurnId(state.messages, event.turn_id);
            if (found) {
              const updatedMsg: AssistantChatMessage = {
                ...found.msg,
                content: [...found.msg.content, toolPart],
              };
              set({
                messages: state.messages.map((m, i) =>
                  i === found.index ? updatedMsg : m,
                ),
              });
            } else {
              const asstMsg: ChatMessage = {
                role: "assistant",
                id: `asst-${event.turn_id}`,
                content: [toolPart],
                status: { type: "running" },
                createdAt: new Date(),
              };
              set({
                messages: [...state.messages, asstMsg],
                activeMessageId: asstMsg.id,
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
            const found = findByTurnId(state.messages, event.turn_id);
            if (!found) break;
            const msg = found.msg;
            let toolIdx = -1;
            for (let i = msg.content.length - 1; i >= 0; i--) {
              const p = msg.content[i];
              if (!p) continue;
              if (
                p.type === "tool-call" &&
                p.toolCallId === event.tool_call_id
              ) {
                toolIdx = i;
                break;
              }
            }
            if (toolIdx < 0) break;
            // tool_update is by definition non-terminal (ACP: in_progress/pending,
            // server: pending/running) and is emitted separately from tool_result
            // (TERMINAL_STATUSES = success/error). Assistant UI derives a tool
            // part as complete when `result !== undefined`, so setting `result`
            // on a running update would prematurely complete the tool UI. No
            // custom progress field exists on the official ToolCallMessagePart
            // shape (core 0.3.16), so running updates intentionally do not mutate
            // the part.
            break;
          }

          case "tool_result": {
            if (
              event.session_id !== state.sessionId ||
              event.turn_id !== state.activeTurnId
            ) {
              break;
            }
            const found = findByTurnId(state.messages, event.turn_id);
            if (!found) break;
            const msg = found.msg;
            let toolIdx = -1;
            for (let i = msg.content.length - 1; i >= 0; i--) {
              const p = msg.content[i];
              if (!p) continue;
              if (
                p.type === "tool-call" &&
                p.toolCallId === event.tool_call_id
              ) {
                toolIdx = i;
                break;
              }
            }
            if (toolIdx < 0) break;
            const existingPart = msg.content[toolIdx] as ToolPart;
            const contentText = event.content
              ?.map((c) => (c.type === "content" ? c.text ?? "" : ""))
              .filter(Boolean)[0];
            const existingText =
              typeof existingPart.result === "string" && existingPart.result
                ? existingPart.result
                : undefined;
            const definedResult =
              contentText ??
              existingText ??
              (event.status === "success"
                ? "<no result>"
                : `Tool ${event.status}`);
            const updatedPart: ToolPart = {
              ...existingPart,
              result: definedResult,
              isError:
                event.status === "error" ||
                event.status === "cancelled" ||
                event.status === "aborted" ||
                event.status === "timeout" ||
                undefined,
            };
            const content = [...msg.content];
            content[toolIdx] = updatedPart;
            const updatedMsg: AssistantChatMessage = { ...msg, content };
            set({
              messages: state.messages.map((m, i) =>
                i === found.index ? updatedMsg : m,
              ),
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

          case "cancelled": {
            // Defensive handler: the backend now emits a single
            // `done {reason: "cancelled"}` instead of a separate `cancelled`
            // event, but mark assistant and clear matching state if one still
            // arrives.
            if (
              event.session_id !== state.sessionId ||
              event.turn_id !== state.turnId
            ) {
              break;
            }
            const cancelledStatus: MessageStatus = {
              type: "incomplete",
              reason: "cancelled",
            };
            const found = findByTurnId(state.messages, event.turn_id);
            let nextMessages = state.messages;
            if (found) {
              nextMessages = state.messages.map((m, i) =>
                i === found.index ? { ...m, status: cancelledStatus } : m,
              );
            }
            const nextCorr = new Map(state.partCorrelations);
            const turnPrefix = `${event.turn_id}:`;
            for (const key of nextCorr.keys()) {
              if (key.startsWith(turnPrefix)) nextCorr.delete(key);
            }
            set({
              messages: nextMessages,
              partCorrelations: nextCorr,
              ...clearTurnState,
            });
            break;
          }

          case "part_start": {
            // Signal the start of a new reasoning/text part. Clone
            // correlations, check for duplicate start (idempotent no-op),
            // append exactly once, and record the exact content index.
            if (
              event.session_id !== state.sessionId ||
              event.turn_id !== state.activeTurnId
            ) {
              break;
            }
            const corrKey = `${event.turn_id}:${event.part_id}`;
            const nextCorr = new Map(state.partCorrelations);
            // Duplicate part_start with same key → idempotent no-op.
            if (nextCorr.has(corrKey)) break;

            // Create the official part from event.part_type.
            const newPart: ThreadAssistantMessagePart =
              event.part_type === "reasoning"
                ? { type: "reasoning", text: "" }
                : { type: "text", text: "" };

            const found = findByTurnId(state.messages, event.turn_id);
            let contentIndex: number;
            let nextMessages: ChatMessage[];

            if (found) {
              contentIndex = found.msg.content.length;
              const updatedMsg: AssistantChatMessage = {
                ...found.msg,
                content: [...found.msg.content, newPart],
              };
              nextMessages = state.messages.map((m, i) =>
                i === found.index ? updatedMsg : m,
              );
            } else {
              const asstMsg: ChatMessage = {
                role: "assistant",
                id: `asst-${event.turn_id}`,
                content: [newPart],
                status: { type: "running" },
                createdAt: new Date(),
              };
              contentIndex = 0;
              nextMessages = [...state.messages, asstMsg];
            }

            nextCorr.set(corrKey, contentIndex);
            set({
              messages: nextMessages,
              partCorrelations: nextCorr,
              activeMessageId: `asst-${event.turn_id}`,
            });
            break;
          }

          case "part_delta": {
            // Append streamed text into the matching content part.
            // Resolves by (event.turn_id, event.part_id) via correlation map.
            if (
              event.session_id !== state.sessionId ||
              event.turn_id !== state.activeTurnId
            ) {
              break;
            }
            const corrKey = `${event.turn_id}:${event.part_id}`;
            const contentIndex = state.partCorrelations.get(corrKey);
            if (contentIndex === undefined) break;

            const found = findByTurnId(state.messages, event.turn_id);
            if (!found) break;

            const part = found.msg.content[contentIndex];
            if (!part) break;
            // Narrow to text or reasoning before reading/updating .text.
            if (part.type !== "text" && part.type !== "reasoning") break;

            const content = [...found.msg.content];
            if (part.type === "text") {
              content[contentIndex] = {
                ...part,
                text: part.text + event.text,
              };
            } else if (part.type === "reasoning") {
              content[contentIndex] = {
                ...part,
                text: part.text + event.text,
              };
            } else {
              break;
            }
            const updatedMsg: AssistantChatMessage = { ...found.msg, content };
            set({
              messages: state.messages.map((m, i) =>
                i === found.index ? updatedMsg : m,
              ),
            });
            break;
          }

          case "part_done": {
            // Validate correlation and content part exist. Content and
            // correlation are left unchanged — correlations persist until
            // the turn reaches done/error/cancel/disconnect/reset.
            if (
              event.session_id !== state.sessionId ||
              event.turn_id !== state.activeTurnId
            ) {
              break;
            }
            const corrKey = `${event.turn_id}:${event.part_id}`;
            const contentIndex = state.partCorrelations.get(corrKey);
            if (contentIndex === undefined) break;

            // Validate content part exists at the stored index.
            const found = findByTurnId(state.messages, event.turn_id);
            if (!found) break;
            const part = found.msg.content[contentIndex];
            if (!part) break;

            // No state mutation. Content retains accumulated text.
            // Correlation entry is retained for late deltas.
            break;
          }

          case "warning":
            // Diagnostics only — surfaced by toast/error UI elsewhere.
            console.warn("[RTAI]", event.type, event.message);
            break;

          case "error": {
            console.warn("[RTAI]", event.type, event.message);
            // Turn-correlated error: finalize assistant, clear turn state.
            if (
              event.session_id === state.sessionId &&
              event.turn_id === state.turnId
            ) {
              const errorStatus: MessageStatus = {
                type: "incomplete",
                reason: "error",
              };
              const found = findByTurnId(state.messages, event.turn_id);
              let nextMessages = state.messages;
              if (found) {
                nextMessages = state.messages.map((m, i) =>
                  i === found.index ? { ...m, status: errorStatus } : m,
                );
              }
              const nextCorr = new Map(state.partCorrelations);
              const turnPrefix = `${event.turn_id}:`;
              for (const key of nextCorr.keys()) {
                if (key.startsWith(turnPrefix)) nextCorr.delete(key);
              }
              set({
                messages: nextMessages,
                partCorrelations: nextCorr,
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

      respondToPermission: (requestId, optionId) => {
        const newMap = new Map(get().pendingPermissions);
        newMap.delete(requestId);
        set({ pendingPermissions: newMap });
      },

      setAutoApprove: (on) => set({ autoApprove: on }),

      setMessages: (messages) => set({ messages: Array.from(messages) }),

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
          pendingPermissions: new Map(),
          autoApprove: false,
          partCorrelations: new Map(),
        }),
    }),
    { name: "RTAI Chat Store" },
  ),
);
