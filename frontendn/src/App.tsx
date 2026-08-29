import type { ReactNode } from "react";
import { AssistantRuntimeProvider } from "@assistant-ui/react";
import { ChatProvider } from "./state/ChatContext";
import { useAssistantRuntime } from "./lib/assistantAdapter";
import { Sidebar } from "./components/Sidebar";
import { ChatPanel } from "./components/ChatPanel";

// The assistant-ui runtime is built from ChatContext state, so it must live
// inside the ChatProvider.
function RuntimeProvider({ children }: { children: ReactNode }) {
  const runtime = useAssistantRuntime();
  return (
    <AssistantRuntimeProvider runtime={runtime}>{children}</AssistantRuntimeProvider>
  );
}

export function App() {
  return (
    <ChatProvider>
      <RuntimeProvider>
        <div className="app">
          <Sidebar />
          <ChatPanel />
        </div>
      </RuntimeProvider>
    </ChatProvider>
  );
}