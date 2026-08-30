"use client";

import { OpenChamberChat } from "./OpenChamberChat";
import type { ChatScreenProps } from "./ChatScreen";

export function ChatPanel({
  drawerOpen,
  onMenuClick,
  menuButtonRef,
}: ChatScreenProps) {
  return (
    <main className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
      <OpenChamberChat
        drawerOpen={drawerOpen}
        onMenuClick={onMenuClick}
        menuButtonRef={menuButtonRef}
      />
    </main>
  );
}
