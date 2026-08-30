import { RtaiRuntimeProvider } from "./runtime/RtaiRuntimeProvider";
import { Sidebar } from "./components/Sidebar";
import { ChatPanel } from "./components/ChatPanel";

export function App() {
  return (
    <RtaiRuntimeProvider>
      <div className="h-full w-full flex flex-row">
        <Sidebar />
        <ChatPanel />
      </div>
    </RtaiRuntimeProvider>
  );
}
