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
  type ClientCommand,
  type ConnectionState,
  type Message,
  type ServerEvent,
  type SessionItem,
  type ToolCall,
} from "../types/protocol";
import { nextId, newSessionId } from "../lib/id";
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
}

const initialState: ChatState = {
  connection: "disconnected",
  cwd: "",
  sessionId: newSessionId(),
  generating: false,
  headerTitle: "Current Session",
  messages: [],
  capabilities: { agents: [], models: [], thinkingLevels: [] },
  selectedAgent: "",
  selectedModel: "",
  thinkingLevel: "off",
  activeMessageId: null,
  sessions: [{ id: "session-1", title: "Current Session", active: true }],
};

type Action =
  | { type: "EVENT"; event: ServerEvent }
  | { type: "USER_TURN"; text: string; messageId: string; turnId: string }
  | { type: "SET_CONNECTION"; state: ConnectionState }
  | { type: "RESET_SESSION" }
  | { type: "TOGGLE_THEME" };

function appendTool(message: Message, tool: ToolCall): Message {
  const tools = message.tools ? [...message.tools] : [];
  const idx = tools.findIndex((t) => t.id === tool.id);
  if (idx >= 0) tools[idx] = { ...tools[idx], ...tool };
  else tools.push(tool);
  return { ...message, tools };
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

    case "TOGGLE_THEME": {
      const isDark = document.documentElement.classList.toggle("dark");
      localStorage.setItem("theme", isDark ? "dark" : "light");
      return state;
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

    case "agents_available":
      return {
        ...state,
        capabilities: { ...state.capabilities, agents: event.agents },
        selectedAgent: state.selectedAgent || event.agents[0]?.id || "",
      };

    case "models_available":
      return {
        ...state,
        capabilities: { ...state.capabilities, models: event.models },
        selectedModel: state.selectedModel || event.models[0]?.id || "",
      };

    case "agent_selected":
      return { ...state, selectedAgent: event.agent_id };

    case "model_selected":
      return { ...state, selectedModel: event.model_id };

    case "thinking_available": {
      const levels = event.thinking_levels;
      const level = levels.includes(state.thinkingLevel) ? state.thinkingLevel : levels[0] ?? "off";
      return { ...state, capabilities: { ...state.capabilities, thinkingLevels: levels }, thinkingLevel: level };
    }

    case "thinking_selected":
      return { ...state, thinkingLevel: event.level };

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
        m.id === state.activeMessageId ? { ...m, status: "complete" } : m,
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
  respondPermission: (permissionRequestId: string, optionId: string) => void;
}

const Ctx = createContext<ChatContextValue | null>(null);

export function ChatProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState);
  const { connect, send, close } = useChatSocket((e) => dispatch({ type: "EVENT", event: e }));
  const counters = useRef({ req: 0, turn: 0 });

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
    },
    [state.sessionId, send],
  );

  const newSession = useCallback(() => {
    dispatch({ type: "RESET_SESSION" });
    close();
    if (state.cwd) connect(state.cwd);
  }, [close, connect, state.cwd]);

  const toggleTheme = useCallback(() => dispatch({ type: "TOGGLE_THEME" }), []);

  useEffect(() => {
    if (localStorage.getItem("theme") === "light") document.documentElement.classList.remove("dark");
    const stored = localStorage.getItem("project-folder");
    if (stored) connect(stored);
  }, [connect]);

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
    respondPermission,
  };

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useChat(): ChatContextValue {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useChat must be used within ChatProvider");
  return ctx;
}
