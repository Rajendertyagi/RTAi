"use client";

import { useState, useEffect } from "react";
import { Moon, Sun, RefreshCw, Plus } from "lucide-react";

const THEME_KEY = "theme";
const FOLDER_KEY = "project-folder";

export function Sidebar() {
  const [theme, setTheme] = useState<"dark" | "light">("dark");
  const [folder, setFolder] = useState("");

  // Load persisted state on mount
  useEffect(() => {
    const storedTheme = localStorage.getItem(THEME_KEY);
    if (storedTheme === "light" || storedTheme === "dark") {
      setTheme(storedTheme);
      document.documentElement.dataset.theme = storedTheme;
      document.documentElement.style.colorScheme = storedTheme;
    }

    const storedFolder = localStorage.getItem(FOLDER_KEY);
    if (storedFolder) {
      setFolder(storedFolder);
    }
  }, []);

  const toggleTheme = () => {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    localStorage.setItem(THEME_KEY, next);
    document.documentElement.dataset.theme = next;
    document.documentElement.style.colorScheme = next;
  };

  const handleFolderChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setFolder(e.target.value);
  };

  const handleFolderSubmit = () => {
    const value = folder.trim();
    if (value) {
      localStorage.setItem(FOLDER_KEY, value);
      // Reconnect will be handled by the parent via socket context (Phase 2)
    }
  };

  const handleNewSession = () => {
    // Clear in-memory state (Phase 2 will implement proper reset)
    window.location.reload();
  };

  return (
    <aside className="sidebar">
      {/* Header */}
      <div className="sidebar-header">
        <h1 className="sidebar-title">RTAI</h1>
        <button
          type="button"
          onClick={toggleTheme}
          className="icon-btn"
          title={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
        >
          {theme === "dark" ? (
            <Sun className="icon" />
          ) : (
            <Moon className="icon" />
          )}
        </button>
      </div>

      {/* Project Folder */}
      <div className="project-folder">
        <label htmlFor="projectFolder" className="folder-label">
          Project Folder:
        </label>
        <input
          id="projectFolder"
          type="text"
          value={folder}
          onChange={handleFolderChange}
          onKeyDown={(e) => {
            if (e.key === "Enter") handleFolderSubmit();
          }}
          placeholder="Enter project path..."
          className="folder-input"
        />
      </div>

      {/* Session List — empty for Phase 5 */}
      <div className="session-list">
        <div className="session-list-placeholder">
          <span className="placeholder-text">No sessions</span>
        </div>
      </div>

      {/* Footer */}
      <div className="sidebar-footer">
        <button type="button" className="icon-btn" title="Reconnect" onClick={handleFolderSubmit}>
          <RefreshCw className="icon" />
        </button>
        <button type="button" className="icon-btn" title="New Session" onClick={handleNewSession}>
          <Plus className="icon" />
        </button>
      </div>
    </aside>
  );
}
