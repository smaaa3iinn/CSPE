import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Spotify allows http://localhost for dev redirect URIs; https://localhost is often rejected as "insecure".
export default defineConfig({
  plugins: [react()],
  server: {
    // Listen on all loopback interfaces so http://localhost:5173 and http://127.0.0.1:5173 hit the same
    // dev server (and /api proxy). Spotify redirect URI should still be http://127.0.0.1:5173/callback.
    host: true,
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: "http://127.0.0.1:8787", changeOrigin: true },
    },
  },
});
