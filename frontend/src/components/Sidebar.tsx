"use client";

import { useState, useEffect } from "react";
import { Moon, Sun, RefreshCw, Plus } from "lucide-react";

const THEME_KEY = "theme";
const FOLDER_KEY = "project-folder";

interface SidebarProps {
  open: boolean;
  onClose: () => void;
}

export function Sidebar({ open, onClose }: SidebarProps) {
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
    }
  };

  const handleNewSession = () => {
    window.location.reload();
  };

  return (
    <>
      <aside
        id="app-sidebar"
        className={`w-[clamp(14rem,18vw,18rem)] bg-sidebar text-sidebar-foreground border-r border-border flex flex-col shrink-0 overflow-hidden max-md:fixed max-md:inset-y-0 max-md:left-0 max-md:z-40 max-md:w-[min(85vw,20rem)] max-md:transition-[transform,visibility] max-md:duration-200 motion-reduce:transition-none max-md:shadow-xl ${
          open
            ? "max-md:translate-x-0 max-md:visible"
            : "max-md:-translate-x-full max-md:invisible"
        }`}
      >
      {/* Header */}
      <div className="flex items-center justify-between p-4 border-b border-border shrink-0">
        <h1 className="text-xl font-semibold m-0 p-0">RTAI</h1>
        <button
          type="button"
          onClick={toggleTheme}
          className="flex items-center justify-center w-8 h-8 max-md:h-11 max-md:w-11 p-0 border-none rounded-lg bg-transparent text-inherit cursor-pointer transition-colors hover:bg-interactive-hover"
          title={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
        >
          {theme === "dark" ? (
            <Sun className="w-4 h-4" />
          ) : (
            <Moon className="w-4 h-4" />
          )}
        </button>
      </div>

      {/* Project Folder */}
      <div className="p-4 border-b border-border shrink-0">
        <label htmlFor="projectFolder" className="block text-xs font-medium uppercase tracking-widest opacity-70 mb-2">
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
          className="w-full px-3 py-2 border border-border rounded-lg bg-background text-foreground text-sm outline-none transition-colors focus:border-ring placeholder:text-muted-foreground"
        />
      </div>

      {/* Session List */}
      <div className="flex-1 overflow-y-auto p-4">
        <div className="flex items-center justify-center h-full min-h-[200px]">
          <span className="text-sm text-muted-foreground text-center">No sessions</span>
        </div>
      </div>

      {/* Footer */}
      <div className="flex items-center justify-center gap-2 p-4 border-t border-border shrink-0">
        <button type="button" className="flex items-center justify-center w-8 h-8 max-md:h-11 max-md:w-11 p-0 border-none rounded-lg bg-transparent text-inherit cursor-pointer transition-colors hover:bg-interactive-hover" title="Reconnect" onClick={handleFolderSubmit}>
          <RefreshCw className="w-4 h-4" />
        </button>
        <button type="button" className="flex items-center justify-center w-8 h-8 max-md:h-11 max-md:w-11 p-0 border-none rounded-lg bg-transparent text-inherit cursor-pointer transition-colors hover:bg-interactive-hover" title="New Session" onClick={handleNewSession}>
          <Plus className="w-4 h-4" />
        </button>
      </div>
    </aside>

      {open && (
        <div
          className="fixed inset-0 z-30 bg-foreground/50 md:hidden"
          onClick={onClose}
          aria-hidden="true"
        />
      )}
    </>
  );
}
