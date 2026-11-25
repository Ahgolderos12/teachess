import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// In development the API runs separately: `uv run teachess serve --no-open-browser`.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
  build: { outDir: "dist", emptyOutDir: true },
  test: { environment: "node", include: ["src/**/*.test.ts"] },
});
