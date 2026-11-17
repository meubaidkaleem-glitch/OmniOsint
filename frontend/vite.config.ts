/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

// The development server forwards API calls to a locally running backend
// (`omniosint serve`). The Host header is left as the browser sent it, so the
// backend sees a same-origin request from http://localhost:5173 and its
// host and origin checks work without any special configuration.
const backend = process.env.OMNIOSINT_DEV_BACKEND ?? "http://127.0.0.1:8765";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: backend, changeOrigin: false },
    },
  },
  preview: { host: "127.0.0.1", port: 4173, strictPort: true },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: false,
    // Keep every script external: the backend's Content-Security-Policy
    // forbids inline scripts.
    modulePreload: { polyfill: false },
    chunkSizeWarningLimit: 900,
  },
  test: {
    environment: "jsdom",
    globals: false,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    css: false,
    restoreMocks: true,
  },
});
