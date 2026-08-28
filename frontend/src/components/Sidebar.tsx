import { useState } from "react";
import { useChat } from "../state/ChatContext";
import { ThemeIcon, ReconnectIcon, NewSessionIcon } from "./Icons";

export function Sidebar() {
  const { state, connect, newSession, toggleTheme } = useChat();
  const [folder, setFolder] = useState(state.cwd);

  const onConnect = () => {
    const value = folder.trim();
    localStorage.setItem("project-folder", value);
    connect(value);
  };

  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <h1>RTAI</h1>
        <button className="icon-btn" onClick={toggleTheme} title="Toggle theme" type="button">
          <ThemeIcon />
        </button>
      </div>

      <div className="project-folder">
        <label>Project Folder:</label>
        <input
          id="projectFolder"
          value={folder}
          placeholder="Enter project path..."
          onChange={(e) => setFolder(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") onConnect();
          }}
        />
      </div>

      <div className="session-list" id="sessionList">
        {state.sessions.map((s) => (
          <div key={s.id} className={`session-item ${s.active ? "active" : ""}`}>
            <span className="session-title">{s.title}</span>
          </div>
        ))}
      </div>

      <div className="sidebar-footer">
        <button className="icon-btn" onClick={onConnect} title="Reconnect" type="button">
          <ReconnectIcon />
        </button>
        <button className="icon-btn" onClick={newSession} title="New Session" type="button">
          <NewSessionIcon />
        </button>
      </div>
    </aside>
  );
}
