import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { initTheme } from "./lib/theme";
import "../chat.css";

// Phase 0 only: load the assistant-ui probe through a dynamic import so Vite
// emits it as its own chunk. This measures whether the primitives can be kept
// out of the initial bundle rather than inflating the main entry point.
void import("./lib/assistantRuntimeProbe").then((probe) => {
  (globalThis as Record<string, unknown>).__rtaiAuiProbe = probe.assistantUiProbe;
});

// Sync the theme store with what the pre-paint script already applied, so the
// store and the document start out identical.
initTheme();

const root = document.getElementById("root");
if (!root) throw new Error("Root element #root not found");

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
