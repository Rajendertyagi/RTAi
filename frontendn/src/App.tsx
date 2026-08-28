import { ChatProvider } from "./state/ChatContext";
import { Sidebar } from "./components/Sidebar";
import { ChatPanel } from "./components/ChatPanel";

export function App() {
  return (
    <ChatProvider>
      <div className="app">
        <Sidebar />
        <ChatPanel />
      </div>
    </ChatProvider>
  );
}
