import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/auth": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/homes": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/admin": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/devices": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/events": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/health": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/automations": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/sensors": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/activity": { target: "http://127.0.0.1:8000", changeOrigin: true },
      "/ws": {
        target: "ws://127.0.0.1:8000",
        ws: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test-setup.ts",
    include: ["src/**/*.test.ts", "src/**/*.test.tsx", "../../packages/shared/src/**/*.test.ts"],
  },
});
