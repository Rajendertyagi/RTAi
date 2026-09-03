import { useState, useEffect, useRef } from "react";
import { RtaiRuntimeProvider } from "./runtime/RtaiRuntimeProvider";
import { Sidebar } from "./components/Sidebar";
import { ChatScreen } from "./components/ChatScreen";
import { DiagnosticsPanel } from "./components/DiagnosticsPanel";

export function App() {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [diagOpen, setDiagOpen] = useState(false);
  const menuButtonRef = useRef<HTMLButtonElement>(null);

  // Close the mobile drawer on Escape and restore focus to the menu button.
  useEffect(() => {
    if (!drawerOpen) return;
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setDrawerOpen(false);
        menuButtonRef.current?.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [drawerOpen]);

  const closeDrawer = () => {
    setDrawerOpen(false);
    menuButtonRef.current?.focus();
  };

  return (
    <RtaiRuntimeProvider>
      <div className="flex h-dvh min-h-0 w-full min-w-0 overflow-hidden">
        <Sidebar open={drawerOpen} onClose={closeDrawer} />
        <ChatScreen
          drawerOpen={drawerOpen}
          onMenuClick={() => setDrawerOpen(true)}
          menuButtonRef={menuButtonRef}
        />
        {!diagOpen && (
          <button
            type="button"
            onClick={() => setDiagOpen(true)}
            className="fixed bottom-3 right-3 z-50 rounded-md border border-border bg-popover px-3 py-1.5 text-xs text-popover-foreground shadow hover:bg-accent"
          >
            Logs
          </button>
        )}
        <DiagnosticsPanel open={diagOpen} onClose={() => setDiagOpen(false)} />
      </div>
    </RtaiRuntimeProvider>
  );
}
