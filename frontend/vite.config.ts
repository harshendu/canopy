import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Dev-server proxy target for /api + /webhooks. On the host this is the local backend;
// inside docker compose it's the backend service (compose sets VITE_PROXY_TARGET).
const proxyTarget = process.env.VITE_PROXY_TARGET || "http://localhost:8000";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/api": { target: proxyTarget, changeOrigin: true },
      "/webhooks": { target: proxyTarget, changeOrigin: true },
    },
  },
});
