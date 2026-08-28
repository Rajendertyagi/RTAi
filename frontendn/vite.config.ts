import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Multi-file build: emits index.html + assets/*.js + assets/*.css.
// `base: "./"` keeps asset URLs relative so they resolve under /demo1/.
// CI copies the whole dist/ to backend/app/static/dist/demo1/.
export default defineConfig({
  plugins: [react()],
  base: "./",
  build: {
    outDir: "dist",
  },
});
