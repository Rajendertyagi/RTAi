"use client";

import { OpenChamberChat } from "./OpenChamberChat";

export function ChatPanel() {
  return (
    <main className="flex-1 min-w-0 flex flex-col bg-background">
      <OpenChamberChat />
    </main>
  );
}
