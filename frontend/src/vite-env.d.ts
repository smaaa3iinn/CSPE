/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Absolute origin of the FastAPI product shell, no trailing slash (e.g. http://192.168.1.5:8787). Empty = same-origin / Vite proxy. */
  readonly VITE_API_BASE?: string;
  /** Where Vite proxies `/api` in dev (default http://127.0.0.1:8787). Set in repo-root `.env` if needed. */
  readonly VITE_DEV_PROXY_TARGET?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
