import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useReducer,
  useRef,
  type ReactNode,
} from "react";
import {
  PROTOCOL_VERSION,
  type Capabilities,
  type ConnectionState,
  type Message,
  type ServerEvent,
  type SessionItem,
  type ToolCall,
} from "../types/protocol";
import { nextId, newSessionId } from "../lib/id";
import { toggleTheme as toggleThemePreference } from "../lib/theme";
import { useChatSocket } from "../hooks/useChatSocket";

export interface ChatState {
  connection: ConnectionState;
  cwd: string;
  sessionId: string;
  generating: boolean;
  headerTitle: string;
  messages: Message[];
  capabilities: Capabilities;
  selectedAgent: string;
  selectedModel: string;
  thinkingLevel: string;
  activeMessageId: string | null;
  sessions: SessionItem[];
  // When on, incoming permission prompts are answered automatically with the
  // option the backend marked as `kind: "allow"`.
  autoAccept: boolean;
}

const AUTO_ACCEPT_KEY = "rtai-auto-accept";

function storedAutoAccept(): boolean {
  try {
    return localStorage.getItem(AUTO_ACCEPT_KEY) === "on";
  } catch {
    return false;
  }
}

const initialState: ChatState = {
  connection: "disconnected",
  cwd: "",
  sessionId: newSessionId(),
  generating: false,
  headerTitle: "Current Session",
  messages: [],
  capabilities: { agents: [], models: [], thinkingLevels: [], commands: [], unavailable: {} },
  selectedAgent: "",
  selectedModel: "",
  thinkingLevel: "off",
  activeMessageId: null,
  sessions: [{ id: "session-1", title: "Current Session", active: true }],
  autoAccept: storedAutoAccept(),
};

type Action =
  | { type: "EVENT"; event: ServerEvent }
  | { type: "USER_TURN"; text: string; messageId: string; turnId: string }
  | { type: "SET_CONNECTION"; state: ConnectionState }
  | { type: "RESET_SESSION" }
  | { type: "TOGGLE_AUTO_ACCEPT" }
  | { type: "RESOLVE_PERMISSION"; permissionRequestId: string };

function appendTool(message: Message, tool: ToolCall): Message {
  const tools = message.tools ? [...message.tools] : [];
  const idx = tools.findIndex((t) => t.id === tool.id);
  if (idx >= 0) tools[idx] = { ...tools[idx], ...tool };
  else tools.push(tool);
  return { ...message, tools };
}

// A capability section can arrive with `available:false` and no items array at
// all. Capture the reason so the UI can explain itself instead of going blank.
function unavailableOf(event: {
  available?: boolean;
  reason_code?: string;
  reason_message?: string;
}) {
  if (event.available !== false) return undefined;
  return {
    code: event.reason_code ?? "unavailable",
    message: event.reason_message ?? "Not available.",
  };
}

function reducer(state: ChatState, action: Action): ChatState {
  switch (action.type) {
    case "USER_TURN": {
      const userMsg: Message = {
        id: action.messageId,
        role: "user",
        text: action.text,
        status: "complete",
      };
      const agentId = nextId("msg");
      const agentMsg: Message = { id: agentId, role: "agent", text: "", status: "streaming" };
      return {
        ...state,
        messages: [...state.messages, userMsg, agentMsg],
        activeMessageId: agentId,
        generating: true,
        headerTitle: action.text.slice(0, 40) + (action.text.length > 40 ? "..." : ""),
      };
    }

    case "SET_CONNECTION":
      return { ...state, connection: action.state };

    case "RESET_SESSION":
      return {
        ...state,
        sessionId: newSessionId(),
        messages: [],
        generating: false,
        activeMessageId: null,
        headerTitle: "Current Session",
        sessions: [{ id: newSessionId(), title: "Current Session", active: true }],
      };

    case "TOGGLE_AUTO_ACCEPT":
      return { ...state, autoAccept: !state.autoAccept };

    // Hide the inline permission dialog once a choice has been sent.
    case "RESOLVE_PERMISSION": {
      const messages = state.messages.map((m) =>
        m.permission && m.permission.permission_request_id === action.permissionRequestId
          ? { ...m, permission: undefined }
          : m,
      );
      return { ...state, messages };
    }

    case "EVENT":
      return reduceEvent(state, action.event);

    default:
      return state;
  }
}

function reduceEvent(state: ChatState, event: ServerEvent): ChatState {
  switch (event.type) {
    case "status":
      if (event.state === "ready")
        return { ...state, connection: "connected", cwd: event.cwd ?? state.cwd };
      if (event.state === "starting") return { ...state, connection: "connecting" };
      return { ...state, connection: "disconnected" };

    case "error":
      return {
        ...state,
        messages: [
          ...state.messages,
          { id: nextId("msg"), role: "error", text: event.message, status: "error" },
        ],
      };

    case "agents_available": {
      const agents = event.agents ?? [];
      return {
        ...state,
        capabilities: {
          ...state.capabilities,
          agents,
          unavailable: { ...state.capabilities.unavailable, agents: unavailableOf(event) },
        },
        selectedAgent: state.selectedAgent || agents[0]?.id || "",
      };
    }

    case "models_available": {
      const models = event.models ?? [];
      return {
        ...state,
        capabilities: {
          ...state.capabilities,
          models,
          unavailable: { ...state.capabilities.unavailable, models: unavailableOf(event) },
        },
        selectedModel: state.selectedModel || models[0]?.id || "",
      };
    }

    case "agent_selected":
      return { ...state, selectedAgent: event.agent_id };

    case "model_selected":
      return { ...state, selectedModel: event.model_id };

    case "thinking_available": {
      const levels = event.thinking_levels ?? [];
      const level = levels.includes(state.thinkingLevel) ? state.thinkingLevel : levels[0] ?? "off";
      return {
        ...state,
        capabilities: {
          ...state.capabilities,
          thinkingLevels: levels,
          unavailable: { ...state.capabilities.unavailable, thinking: unavailableOf(event) },
        },
        thinkingLevel: level,
      };
    }

    case "thinking_selected":
      return { ...state, thinkingLevel: event.level };

    // Slash commands. The backend re-emits this after session creation via
    // available_commands_update, so it can arrive more than once.
    case "commands_available": {
      const commands = event.commands ?? [];
      return {
        ...state,
        capabilities: {
          ...state.capabilities,
          commands,
          unavailable: { ...state.capabilities.unavailable, commands: unavailableOf(event) },
        },
      };
    }

    case "user_message":
      return state;

    case "delta": {
      const id = state.activeMessageId ?? nextId("msg");
      const exists = state.messages.some((m) => m.id === id);
      const partial: Message = exists
        ? { ...(state.messages.find((m) => m.id === id) as Message), text: (state.messages.find((m) => m.id === id) as Message).text + (event.text || "") }
        : { id, role: "agent", text: event.text || "", status: "streaming" };
      const messages = exists
        ? state.messages.map((m) => (m.id === id ? partial : m))
        : [...state.messages, partial];
      return { ...state, messages, activeMessageId: id };
    }

    case "done": {
      if (!state.activeMessageId) return { ...state, generating: false };
      const messages = state.messages.map((m) =>
        m.id === state.activeMessageId ? { ...m, status: "complete" as const } : m,
      );
      return { ...state, messages, generating: false, activeMessageId: null };
    }

    case "tool_start": {
      if (!state.activeMessageId) return state;
      const messages = state.messages.map((m) =>
        m.id === state.activeMessageId
          ? appendTool(m, { id: event.tool_call_id, title: event.title, status: event.status ?? "running" })
          : m,
      );
      return { ...state, messages };
    }

    case "tool_result": {
      if (!state.activeMessageId) return state;
      const messages = state.messages.map((m) =>
        m.id === state.activeMessageId
          ? appendTool(m, { id: event.tool_call_id, status: event.status, content: event.content })
          : m,
      );
      return { ...state, messages };
    }

    case "permission_request": {
      if (!state.activeMessageId) return state;
      const messages = state.messages.map((m) =>
        m.id === state.activeMessageId
          ? { ...m, permission: { permission_request_id: event.permission_request_id, tool_call_id: event.tool_call_id, options: event.options } }
          : m,
      );
      return { ...state, messages };
    }

    // Backend echo of a resolved permission. The dialog is already cleared
    // optimistically when the response is sent; this is an idempotent backup
    // for requests resolved outside this client.
    case "permission_result": {
      const messages = state.messages.map((m) =>
        m.permission && m.permission.permission_request_id === event.permission_request_id
          ? { ...m, permission: undefined }
          : m,
      );
      return { ...state, messages };
    }

    case "raw":
    default:
      return state;
  }
}

export interface ChatContextValue {
  state: ChatState;
  connect: (folder: string) => void;
  sendPrompt: (text: string) => void;
  cancel: () => void;
  selectAgent: (agentId: string) => void;
  selectModel: (modelId: string) => void;
  setThinking: (level: string) => void;
  newSession: () => void;
  toggleTheme: () => void;
  toggleAutoAccept: () => void;
  respondPermission: (permissionRequestId: string, optionId: string) => void;
}

const Ctx = createContext<ChatContextValue | null>(null);

export function ChatProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState);
  const { connect, send, close } = useChatSocket((e) => dispatch({ type: "EVENT", event: e }));
  const counters = useRef({ req: 0, turn: 0 });
  // Guards against answering the same prompt twice, since this effect re-runs
  // on every message update while auto-accept is on.
  const autoAnswered = useRef<Set<string>>(new Set());

  const connectTo = useCallback(
    (folder: string) => {
      dispatch({ type: "RESET_SESSION" });
      localStorage.setItem("project-folder", folder);
      connect(folder);
    },
    [connect],
  );

  const sendPrompt = useCallback(
    (text: string) => {
      if (state.generating || !text.trim()) return;
      counters.current.turn += 1;
      counters.current.req += 1;
      const turnId = `turn-${counters.current.turn}`;
      const messageId = nextId("msg");
      dispatch({ type: "USER_TURN", text: text.trim(), messageId, turnId });
      send({
        protocol_version: PROTOCOL_VERSION,
        type: "prompt",
        request_id: `req-${counters.current.req}`,
        session_id: state.sessionId,
        turn_id: turnId,
        message_id: messageId,
        text: text.trim(),
      });
    },
    [state.generating, state.sessionId, send],
  );

  const cancel = useCallback(() => {
    if (!state.generating) return;
    counters.current.req += 1;
    send({
      protocol_version: PROTOCOL_VERSION,
      type: "cancel",
      request_id: `req-${counters.current.req}`,
      session_id: state.sessionId,
      turn_id: `turn-${counters.current.turn}`,
    });
  }, [state.generating, state.sessionId, send]);

  const selectAgent = useCallback(
    (agentId: string) => {
      counters.current.req += 1;
      send({
        protocol_version: PROTOCOL_VERSION,
        type: "select_agent",
        request_id: `req-${counters.current.req}`,
        session_id: state.sessionId,
        agent_id: agentId,
      });
    },
    [state.sessionId, send],
  );

  const selectModel = useCallback(
    (modelId: string) => {
      counters.current.req += 1;
      send({
        protocol_version: PROTOCOL_VERSION,
        type: "select_model",
        request_id: `req-${counters.current.req}`,
        session_id: state.sessionId,
        model_id: modelId,
      });
    },
    [state.sessionId, send],
  );

  const setThinking = useCallback(
    (level: string) => {
      counters.current.req += 1;
      send({
        protocol_version: PROTOCOL_VERSION,
        type: "set_thinking",
        request_id: `req-${counters.current.req}`,
        session_id: state.sessionId,
        level,
      });
    },
    [state.sessionId, send],
  );

  const respondPermission = useCallback(
    (permissionRequestId: string, optionId: string) => {
      counters.current.req += 1;
      send({
        protocol_version: PROTOCOL_VERSION,
        type: "permission_response",
        request_id: `req-${counters.current.req}`,
        session_id: state.sessionId,
        turn_id: `turn-${counters.current.turn}`,
        permission_request_id: permissionRequestId,
        option_id: optionId,
      });
      dispatch({ type: "RESOLVE_PERMISSION", permissionRequestId });
    },
    [state.sessionId, send],
  );

  const newSession = useCallback(() => {
    dispatch({ type: "RESET_SESSION" });
    close();
    if (state.cwd) connect(state.cwd);
  }, [close, connect, state.cwd]);

  // The theme lives in its own store (src/lib/theme.ts) so the document, React
  // and Shiki all read one value. Keeping it out of the reducer also keeps the
  // reducer pure under StrictMode double-invocation.
  const toggleTheme = useCallback(() => toggleThemePreference(), []);

  const toggleAutoAccept = useCallback(() => dispatch({ type: "TOGGLE_AUTO_ACCEPT" }), []);

  useEffect(() => {
    // Theme initialisation lives in src/lib/theme.ts (initTheme is called once
    // in main.tsx); this effect only restores the project folder.
    const stored = localStorage.getItem("project-folder");
    if (stored) connect(stored);
  }, [connect]);

  useEffect(() => {
    try {
      localStorage.setItem(AUTO_ACCEPT_KEY, state.autoAccept ? "on" : "off");
    } catch {
      // Storage unavailable (private mode); the in-memory toggle still works.
    }
  }, [state.autoAccept]);

  // Answer pending permission prompts automatically. The backend forwards the
  // ACP option kind verbatim ("allow_once" | "allow_always" | "reject_once" |
  // "reject_always"); fall back to a label match for adapters that omit kind.
  useEffect(() => {
    if (!state.autoAccept) return;
    for (const message of state.messages) {
      const pending = message.permission;
      if (!pending) continue;
      if (autoAnswered.current.has(pending.permission_request_id)) continue;
      const allow =
        pending.options.find((o) => o.kind?.startsWith("allow")) ??
        pending.options.find((o) => /allow/i.test(o.label));
      if (!allow) continue;
      autoAnswered.current.add(pending.permission_request_id);
      respondPermission(pending.permission_request_id, allow.id);
    }
  }, [state.autoAccept, state.messages, respondPermission]);

  const value: ChatContextValue = {
    state,
    connect: connectTo,
    sendPrompt,
    cancel,
    selectAgent,
    selectModel,
    setThinking,
    newSession,
    toggleTheme,
    toggleAutoAccept,
    respondPermission,
  };

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useChat(): ChatContextValue {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useChat must be used within ChatProvider");
  return ctx;
}
