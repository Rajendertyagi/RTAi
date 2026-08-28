import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { initTheme } from "./lib/theme";
import "../chat.css";

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
