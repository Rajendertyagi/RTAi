import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { initTheme } from "./lib/theme";
import { assistantUiProbe } from "./lib/assistantRuntimeProbe";
import "../chat.css";

// Phase 0 only: hold the probe with an unconditional side effect so the bundler
// cannot tree-shake it away before the measurement build reads it.
(globalThis as Record<string, unknown>).__rtaiAuiProbe = assistantUiProbe;

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
