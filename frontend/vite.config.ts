import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The dev server mirrors the nginx routing used in the container: the app
// always talks to /api and never needs to know where the backend lives.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:4567",
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    // Component tests only. The e2e/ specs are Playwright's and need a real
    // browser against a running stack; vitest would otherwise collect them.
    include: ["src/**/*.{test,spec}.{ts,tsx}"],
  },
});
