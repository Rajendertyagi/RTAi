import { useChat } from "../state/ChatContext";

export function StatusBar() {
  const { state } = useChat();
  const label =
    state.connection === "connected"
      ? "Ready"
      : state.connection === "connecting"
        ? "Connecting..."
        : state.connection === "error"
          ? "Connection error"
          : "Disconnected";

  return (
    <div className="status-bar">
      <div className={`status-dot ${state.connection}`} />
      <span id="statusText">{label}</span>
      {state.agentInfo && <span id="agentText" className="agent-text">{state.agentInfo}</span>}
      {state.cwd && <span id="cwdText" className="cwd-text">{state.cwd}</span>}
    </div>
  );
}
