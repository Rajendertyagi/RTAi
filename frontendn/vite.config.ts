import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Build directly into backend/app/static/dist/ so the FastAPI static mount
// serves it at / with no copy step needed. `base: "./"` keeps asset URLs
// relative for both production and the missing-frontend diagnostic path.
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: {
    outDir: "../backend/app/static/dist",
  },
});
