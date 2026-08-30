import { useState, useEffect, useRef } from "react";
import { RtaiRuntimeProvider } from "./runtime/RtaiRuntimeProvider";
import { Sidebar } from "./components/Sidebar";
import { ChatPanel } from "./components/ChatPanel";

export function App() {
  const [drawerOpen, setDrawerOpen] = useState(false);
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
        <ChatPanel
          drawerOpen={drawerOpen}
          onMenuClick={() => setDrawerOpen(true)}
          menuButtonRef={menuButtonRef}
        />
      </div>
    </RtaiRuntimeProvider>
  );
}
