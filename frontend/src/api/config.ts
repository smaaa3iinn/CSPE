/**
 * Optional absolute API origin for the product shell (FastAPI).
 *
 * - **Unset / empty** (default): use same-origin relative URLs (`/api/...`). With `npm run dev`,
 *   Vite proxies `/api` to the backend — works for laptop + iPad when you open `http://<LAN-IP>:5173`.
 * - **Set** (e.g. `VITE_API_BASE=http://192.168.1.10:8787`): call the backend directly. Use when
 *   bypassing the dev proxy; FastAPI must allow CORS for your dev page origin (see `PRODUCT_SHELL_CORS_*`).
 */
export function getApiBase(): string {
  const raw = import.meta.env.VITE_API_BASE;
  if (raw == null || String(raw).trim() === "") return "";
  return String(raw).replace(/\/$/, "");
}

/** Absolute API base for external windows that cannot use this Vite app's relative `/api` proxy. */
export function getExternalApiBase(): string {
  const direct = getApiBase();
  if (direct) return direct;
  const proxyTarget = import.meta.env.VITE_DEV_PROXY_TARGET || import.meta.env.PRODUCT_SHELL_URL;
  if (proxyTarget && String(proxyTarget).trim()) return String(proxyTarget).replace(/\/$/, "");
  return "http://127.0.0.1:8787";
}

export function getGraphXRViewerBase(): string {
  const raw = import.meta.env.VITE_GRAPHXR_VIEWER_URL || import.meta.env.VITE_A25_VIEWER_URL;
  if (raw && String(raw).trim()) return String(raw).replace(/\/$/, "");
  return "http://localhost:3000/viewer";
}

/** Prefix a path (must start with `/`) with `VITE_API_BASE` when set. */
export function apiUrl(path: string): string {
  const base = getApiBase();
  const p = path.startsWith("/") ? path : `/${path}`;
  return base ? `${base}${p}` : p;
}
