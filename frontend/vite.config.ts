import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
/** Repo root (parent of `frontend/`) — single `.env` for Vite + Python. */
const repoRoot = path.resolve(__dirname, "..");

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, repoRoot, "");
  const proxyTarget =
    env.VITE_DEV_PROXY_TARGET?.trim() ||
    env.PRODUCT_SHELL_URL?.trim() ||
    "http://127.0.0.1:8787";

  return {
    plugins: [react()],
    envDir: repoRoot,
    preview: {
      host: "0.0.0.0",
      port: 5173,
      strictPort: true,
      proxy: {
        "/api": {
          target: proxyTarget,
          changeOrigin: true,
        },
      },
    },
    server: {
      // Bind all interfaces so phones/tablets on LAN can reach the dev server (e.g. http://192.168.x.x:5173).
      host: "0.0.0.0",
      port: 5173,
      strictPort: true,
      proxy: {
        "/api": {
          target: proxyTarget,
          changeOrigin: true,
        },
      },
    },
  };
});
