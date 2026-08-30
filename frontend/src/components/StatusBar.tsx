"use client";

import { useAui } from "@assistant-ui/react";
import { StopCircle } from "lucide-react";
import { useChatStore } from "../state/chatStore";

export function StatusBar() {
  const aui = useAui();
  const isRunning = useChatStore((s) => s.activeTurnId !== null);
  const isConnected = useChatStore((s) => s.connected);
  const agentInfo = useChatStore((s) => s.agentInfo);
  const handleCancel = () => aui.thread().cancelRun();

  return (
    <div className="flex items-center gap-2 h-8 px-4 text-xs text-muted-foreground shrink-0 border-t border-interactive bg-surface-background">
      <span
        className={`w-2 h-2 rounded-full shrink-0 ${isConnected ? "bg-status-success" : "bg-status-error"} ${isRunning ? "bg-status-warning animate-[busy-pulse_1.2s_ease-in-out_infinite]" : ""}`}
        aria-hidden="true"
      />
      <span className="text-xs text-muted-foreground">{isConnected ? "Ready" : "Disconnected"}</span>
      <span className="ml-auto text-xs text-muted-foreground">{agentInfo || "Agent"}</span>
      {isRunning && (
        <>
          <span className="animate-[busy-pulse_1.2s_ease-in-out_infinite]">●</span>
          <button
            type="button"
            onClick={handleCancel}
            className="ml-auto flex items-center gap-1 rounded-md px-2 py-1 text-sm transition-colors hover:bg-interactive-hover"
            aria-label="Stop generation"
          >
            <StopCircle className="w-4 h-4" />
            Stop
          </button>
        </>
      )}
    </div>
  );
}
