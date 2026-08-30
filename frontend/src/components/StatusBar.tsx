"use client";

import { useAui } from "@assistant-ui/react";
import { StopCircle } from "lucide-react";
import { useChatStore } from "../state/chatStore";

export function StatusBar() {
  const aui = useAui();
  // Source running state from our own store (activeTurnId) so the Stop
  // affordance tracks the real stream. assistant-ui's external runtime does
  // not reflect this back through thread.isRunning.
  const isRunning = useChatStore((s) => s.activeTurnId !== null);
  const isConnected = useChatStore((s) => s.connected);
  const agentInfo = useChatStore((s) => s.agentInfo);
  const handleCancel = () => aui.thread().cancelRun();

  return (
    <div className="status-bar--persistent">
      <span
        className={`status-dot ${isConnected ? "connected" : "disconnected"} ${isRunning ? "connecting" : ""}`}
      />
      <span className="agent-text">{isConnected ? "Ready" : "Disconnected"}</span>
      <span className="agent-text ml-auto">{agentInfo || "Agent"}</span>
      {isRunning && (
        <>
          <span className="dot-pulse">╬ô├╣├à</span>
          <button
            type="button"
            onClick={handleCancel}
            className="ml-auto flex items-center gap-1 rounded-md px-2 py-1 text-sm hover:bg-[var(--interactive-hover)]"
            aria-label="Stop generation"
          >
            <StopCircle className="h-4 w-4" />
            Stop
          </button>
        </>
      )}
    </div>
  );
}
