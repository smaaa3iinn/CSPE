# CSPE — Technical Architecture Overview

This document describes how the CSPE system is structured and how its parts interact, based on the repository as it exists today. It is intended for technical project review (suivi).

---

## 1. Global System Overview

### What the system does

CSPE is a **local full-stack product** that combines:

- A **web dashboard** (React) with multiple **modes**: public-transport map and routing, a visual board fed by assistant output, project/task memory, and Spotify-backed music controls.
- A **FastAPI “product shell”** that exposes stable HTTP APIs for the browser, proxies or bridges to the AI runtime, serves transport computations, manages a **command queue** for UI automation, stores **product memory** in SQLite, and implements **Spotify OAuth** and Web API calls.
- An **Atlas** subsystem: a **Flask** HTTP service that runs a **long-lived OpenAI Realtime** session, **semantic tool routing**, and **tool execution** (including calls back into the product shell and external APIs).

Transport and mapping reuse **precomputed graph data** under `data/derived/` and **Mapbox GL**-based HTML generation in Python.

### Main components (runtime)

| Layer | Role |
|--------|------|
| **Vite + React frontend** | UI, mode switching, Zustand state, polling shell commands, iframe map blobs |
| **Product shell (FastAPI / uvicorn)** | BFF: `/api/*` for chat, Atlas proxy, transport, memory, Spotify, shell queue |
| **Atlas Flask API** | Session lifecycle (`/wake`, `/sleep`, `/health`, `/mode`, `/text`, `/ui`), image search/proxy, orchestrator thread |
| **Wake service (optional process)** | Local speech (Vosk) → HTTP calls to Atlas `/wake` / `/sleep` |
| **Core Python (`src/core`, `src/viz`)** | NetworkX graphs, station layer, routing queries, Mapbox HTML, regional mask GeoJSON |

### High-level architecture

The browser talks **only** to the **product shell** (directly or via Vite’s dev proxy). The product shell talks to **Atlas** over HTTP using configurable base URLs (`ATLAS_API_BASE` on the shell side; `ATLAS_API_BASE_URL` / related constants in Atlas config). Atlas tools that need the dashboard call the product shell’s **`/api/shell/enqueue`**; the **browser polls** **`/api/shell/poll`** and applies commands. Transport logic runs **inside the same FastAPI process** by importing `src.core` and `src.viz` with the repo root on `PYTHONPATH`.

---

## 2. Detailed Architecture Breakdown

### 2.1 Frontend

**Role:** Single-page application: layout, mode panels, Atlas rail (text + voice), transport controls, memory and music UIs, shell command polling.

**Technologies (from code):** React, TypeScript, Vite, `react-router-dom`, Zustand, `@fortawesome/fontawesome-free` (CSS), CSS modules/files per mode.

**Structure (conceptual):**

- Entry: `main.tsx` mounts `App.tsx` (routes: home shell, `/music` redirect, `/callback` for Spotify).
- `AppShell.tsx`: top bar, `ToolRail` (mode), main region (Transport mounted but visibility toggled; Visual / Memory / Music conditional), `AtlasRailPanel`, `ShellCommandListener`.
- **State:** `store.ts` — global `AppMode`, chat history, structured outputs, transport parameters (graph mode, LCC, viz, path IDs, map blob URL, errors), `atlasTransportAction` payload for Atlas-driven routing UX.
- **API:** `api/client.ts`, `api/config.ts` (`VITE_API_BASE`), `api/spotify.ts`.
- **Transport helpers:** `transport/atlasTransportTypes.ts`, `atlasTransportResolve.ts`.

**Key modules (brief):** `components/AppShell.tsx`, `AtlasRailPanel.tsx`, `ShellCommandListener.tsx`, `modes/*`, `store.ts`, `api/client.ts`.

---

### 2.2 Backend — Product Shell (FastAPI)

**Role:** **Backend-for-frontend**: CORS for dev/LAN, JSON APIs, normalization of Atlas `/ui` into typed blocks, no browser→Atlas direct coupling for chat.

**Technologies:** FastAPI, Pydantic (`schemas.py`), `python-dotenv` (optional) for repo-root `.env`, `requests` for Atlas HTTP, `uvicorn` as ASGI server.

**Composition:**

- **`main.py`:** Loads `.env` from repo root before routers; registers middleware; mounts routers under prefix `/api`; exposes `/api/health` with capability flags.
- **Routers:** `atlas`, `chat`, `shell`, `transport`, `memory`, `spotify` (each included with `prefix="/api"` → paths like `/api/chat`, `/api/transport/map`).
- **`transport_engine.py`:** Binds file paths under `data/`, wraps `src.core` / `src.viz` for map HTML, search, routing, stats.
- **Services:** `atlas_http.py` (session ensure, `send_text_and_wait`, `fetch_atlas_ui`), `normalize.py` (Atlas UI → structured list), `product_memory_store.py` (SQLite), `ui_transport_logger.py` (logging).

**Key modules:** `backend/product_shell/main.py`, `schemas.py`, `routers/*.py`, `transport_engine.py`, `services/atlas_http.py`, `services/normalize.py`, `services/product_memory_store.py`.

---

### 2.3 Agent system — Atlas

**Role:** Host the **OpenAI Realtime** WebSocket session, **audio input**, **semantic routing** to tools, **tool execution**, and **Flask HTTP** control plane. Updates shared **`ui_state`** consumed by `/ui`.

**Technologies (from code):** Flask, `websockets`, `openai` (Realtime + separate client for semantic router), `requests`, optional Azure TTS/audio modules, tool modules under `atlas_client.tools`, router under `atlas_client.router`.

**Structure:**

- **`app/api.py`:** Flask app; `init_env()` from `core.bootstrap`; starts background **session thread** on `/wake` or first `/text`; routes: `/`, `/health`, `/ui`, `/image-search`, `/image-proxy`, `/wake`, `/sleep`, `/mode`, `/text`, `/shutdown`; imports `pulse_manager` for subprocess pulse meter.
- **`core/main.py`:** `run_session()` → asyncio loop → `orchestrator.session_main()`.
- **`core/orchestrator.py`:** WebSocket to Realtime API; imports `semantic_router`, tool execution, audio pipeline, `ui_state`, memory/visual/music tools, etc.
- **`router/tool_executor.py`:** Dispatches by tool name; loads **`tools_registry.json`**; implements CSPE tools that **`POST`** to `{PRODUCT_SHELL_URL}/api/shell/enqueue` (`product_shell_origin()` in `core/config.py`).

**Key modules:** `atlas_client/app/api.py`, `atlas_client/core/orchestrator.py`, `atlas_client/core/semantic_router.py`, `atlas_client/router/tool_executor.py`, `atlas_client/tools/*.py`, `atlas_client/ui/ui_state.py`.

---

### 2.4 Core logic — graph / transport engine

**Role:** Load **cached multimodal graphs**, build **station layer** (grouping stops), run **shortest-path** and **search** on NetworkX graphs, produce **Mapbox GL HTML** strings and GeoJSON overlays; optional **POI** lookup from parquet + spatial index; **Île-de-France / Paris** mask data for map dimming when boundary GeoJSON exists.

**Technologies:** `networkx`, `pandas` (parquet), pickle bundle, Mapbox token injected into generated HTML, `src.viz.plot_mapbox` for rendering helpers, `src.viz.paris_mask` for mask payload.

**Key modules:** `src/core/cache_bundle.py`, `graph_loader.py`, `queries.py`, `station_layer.py`, `poi_index.py`, `debug_log.py`; `src/viz/plot_mapbox.py`, `paris_mask.py`; consumed by `backend/product_shell/transport_engine.py`.

---

### 2.5 Additional services

**Spotify (in product shell):** OAuth Authorization Code flow: `login-url`, `callback` (POST), token persistence to configurable path, status, probe, disconnect, playlists, tracks, saved tracks, search, playback, play-by-query, etc. Uses `requests` against `https://api.spotify.com/v1` and Spotify Accounts endpoints.

**Product memory:** SQLite at `data/product_memory.sqlite` — projects and tasks (CRUD via `/api/memory/*`). Separate from Atlas’s SQLite memory store.

**Atlas memory (agent):** Implemented in `atlas_client` (`storage/memory_store`, tools in `tools/memory.py`); **not** the same database as product memory.

**Read-only helper:** `backend/product_shell/services/atlas_memory_reader.py` defines paths/functions to read Atlas’s SQLite; **no FastAPI router imports this module** in the current tree — it is a **standalone service module** for potential reuse.

**Wake service:** Separate process using **sounddevice**, **Vosk**, HTTP to Atlas wake/sleep/health — optional for hands-free wake words.

**SerpAPI / image search:** `web_search` tool uses `serpapi_client`; Flask exposes `/image-search` and `/image-proxy` for image URLs.

---

## 3. Communication Between Components

### 3.1 Frontend ↔ Backend

- **Default:** Relative URLs `/api/...` — in dev, **Vite proxies** `/api` to `PRODUCT_SHELL_URL` or `VITE_DEV_PROXY_TARGET` (see `vite.config.ts`), default target `http://127.0.0.1:8787`.
- **Optional:** `VITE_API_BASE` set to absolute FastAPI origin — browser calls API cross-origin; FastAPI CORS + optional regex for LAN IPs (`PRODUCT_SHELL_CORS_*`).

**Representative JSON flows:**

- **Chat:** `POST /api/chat` body `{ "message": string }` → response `structured_outputs` (list of dicts), optional `error`, optional `raw_ui`.
- **Atlas proxy:** `POST /api/atlas/input-mode`, `GET /api/atlas/ui`.
- **Transport:** `POST /api/transport/map`, `POST /api/transport/route`, `GET /api/transport/stops/search`, `GET /api/transport/stats`, `GET /api/transport/bundle-health`.
- **Shell:** `GET /api/shell/poll` returns `{ "commands": [...] }`; `POST /api/shell/enqueue` (used by Atlas server-side); `POST /api/shell/client-log`.
- **Memory / Spotify:** paths under `/api/memory/*` and `/api/spotify/*` as implemented in routers.

**Note:** In `client.ts`, most helpers use `apiUrl()`. One transport route helper posts to `"/api/transport/route"` without `apiUrl` — **same-origin only**; with `VITE_API_BASE` set, that call may need alignment with other methods (behavior depends on deployment).

---

### 3.2 Backend ↔ Atlas

- **Configuration:** `atlas_http.atlas_base_url()` reads `ATLAS_API_BASE` (default `http://127.0.0.1:5055`).
- **Session readiness:** `ensure_atlas_session_mode` — `GET /health`, optional `POST /wake` with mode, wait until `session_active`, then `POST /mode` with `voice` or `text`.
- **Chat path:** `send_text_and_wait`:
  - Ensures text mode.
  - Snapshots `GET /ui`.
  - `POST /text` with JSON `{"text": ...}`.
  - Polls `GET /ui` until assistant text or panels change, with stabilization logic and extra wait for panel updates.
- **Atlas proxy routes:** `fetch_atlas_ui()` → `GET /ui` JSON; returned to frontend combined with `normalize_atlas_ui`.

---

### 3.3 Atlas ↔ Backend (tools → shell)

- **`core/config.product_shell_origin()`:** `PRODUCT_SHELL_URL` (default `http://127.0.0.1:8787`), strips trailing `/api` if mistakenly included.
- **`tool_executor`:** For CSPE-related tools, builds `requests.post(f"{base}/api/shell/enqueue", json={"commands": [...]})`.
- **Command kinds** handled on the client include (non-exhaustive): `set_mode`, `navigate`, `transport_graph_mode`, `transport_options`, `transport_route_view`, `atlas_transport_action`, `memory_project`, `apply_structured_outputs`, plus related CSPE tool names (`cspe_route`, `cspe_transport_action`, `cspe_open_transport_map`, `cspe_set_mode`, etc.).

---

### 3.4 Backend ↔ Core logic

- **Import path:** `transport_engine.py` inserts repo root on `sys.path` and imports `src.core.*`, `src.viz.*`.
- **No separate transport microservice** — same process as FastAPI.

---

### 3.5 Command queue / polling

- **Server-side queue:** `shell.py` — thread-locked `deque`, max length 256; `enqueue` appends dicts with `kind`; `poll` returns all and **clears** (single consumer).
- **Client:** `ShellCommandListener` polls on an interval (~600 ms), applies commands to Zustand and React Router `navigate`, logs client milestones via `/api/shell/client-log` when applicable.

---

### 3.6 Flow examples (concrete)

**A — User requests a route in the UI**

1. User selects endpoints (stop- or station-level) and triggers route in Transport mode.
2. Frontend `POST /api/transport/route` with mode, `use_lcc`, and either stop IDs or station IDs (mutually exclusive — validated in router).
3. `transport_engine` loads graph via `get_bundle()` → `graph_for` → `station_layer_for`; `compute_route` or `compute_route_stations` uses `src.core.queries` (`shortest_path`, `best_stop_path_between_stations`, etc., per implementation).
4. JSON response includes paths, names, metrics or structured errors.
5. For map refresh, frontend `POST /api/transport/map` with path IDs, viz options, POI options — server returns **HTML string** + token source hint; UI uses blob URL for iframe.

**B — User sends a chat message**

1. `POST /api/chat` → `send_text_and_wait` → Atlas `/text` + polling `/ui`.
2. `normalize_atlas_ui` produces `text`, `visual_board`, `image_results`, `system_status` blocks.
3. Frontend `applyChatResponse` merges into chat history and image/panel state.

**C — User utterance → tool → UI update**

1. Inside Atlas, `orchestrator` / semantic routing decides a tool (e.g. `cspe_route` or `cspe_transport_action`).
2. `execute_tool` runs asynchronously; tool posts to product shell `enqueue`.
3. Browser’s next `poll` receives command; `ShellCommandListener` updates store (e.g. `atlasTransportAction`) → `TransportMode` reacts (resolve queries, call transport APIs, refresh map).

---

## 4. Data Layer & Data Flow

### Transport / graph

- **Primary bundle:** `data/derived/routing/graph_bundle.pkl` — pickle; contains NetworkX graphs per mode and LCC variants; version field `CACHE_VERSION` in loader.
- **Stop metadata:** `data/derived/stops/stop_popup_index.parquet` — joined to nodes for popups and labels.
- **Render graphs:** JSON under `data/derived/render_graphs/*.render_graph.json` — optional per-mode network overlays.
- **Line geometries:** directory `data/derived/maps` — optional line layers for map.
- **GTFS / stops for parent_station:** `station_layer` looks for `data/normalized_gtfs/stops.parquet` or `data/normalized/gtfs/stops.parquet` when building grouping.
- **POI:** `data/normalized/poi/poi.parquet` with optional BallTree pickle/npz under `data/derived/indexes/`.
- **Regional mask:** `data/derived/geo/ile_de_france_admin_boundary.geojson` and/or `paris_admin_boundary.geojson` — used when present for mask construction.

### UI state (Atlas)

- **`ui_state`** module holds assistant text, panels, status — serialized by Flask `/ui` as JSON. Product shell normalizes to **typed blocks** for React.

### Product memory

- **SQLite** file `data/product_memory.sqlite` — projects and tasks (schemas in `product_memory_store.init_db`).

### Atlas agent memory

- Default path under `src/work/atlas/data/` (see `memory_store` / env overrides in Atlas code) — **different file** from product memory.

### Spotify

- Tokens stored on disk (path from `SPOTIFY_TOKEN_PATH` or default under repo) — JSON-like store accessed with locks in `spotify.py`.

### Formats summary

| Format | Usage |
|--------|--------|
| Pickle | Graph bundle cache |
| Parquet | Stops, POI |
| JSON | API bodies, render graphs, tool registry, Spotify token file |
| HTML (string) | Map iframe content from `/api/transport/map` |
| SQLite | Product memory; Atlas memory |

---

## 5. Frontend Architecture

### UI structure

- **Layout:** Header + left `ToolRail` + main column + fixed `AtlasRailPanel`.
- **Modes:** `transport` | `visual` | `memory` | `music` — `AppShell` toggles visibility; Transport subtree stays mounted to preserve iframe state.
- **Routes:** `/` shell; `/callback` Spotify OAuth; `/music` redirects to main with music mode.

### State management

- **Zustand** single store: mode, chat, structured outputs, transport parameters, errors, optional memory project id, `atlasTransportAction` with monotonic `seq` for imperative handoff to Transport mode.

### API calls

- **`apiUrl`** wraps paths when `VITE_API_BASE` is set.
- Transport and Atlas helpers use fetch + JSON.

### Rendering Atlas outputs

- **`ingestStructuredOutputs`** in `store.ts`: derives assistant text, deduplicated images, `visualPanels` from `text`, `visual_board`, `image_results`.
- **Types** in `types/payloads.ts` mirror normalized server blocks.
- **Voice:** `AtlasRailPanel` switches mode via `/api/atlas/input-mode`, polls `/api/atlas/ui`, syncs transcript fields into local state and structured outputs when signatures change.

---

## 6. Backend (Product Shell) — API Structure

### Routers (all under `/api`)

- **`/api/health`** — service liveness + capability flags.
- **Chat:** `POST /api/chat`.
- **Atlas:** `POST /api/atlas/input-mode`, `GET /api/atlas/ui`.
- **Shell:** `POST /api/shell/enqueue`, `GET /api/shell/poll`, `POST /api/shell/client-log`.
- **Transport:** `GET /api/transport/bundle-health`, `POST /api/transport/map`, `GET /api/transport/stops/search`, `POST /api/transport/route`, `GET /api/transport/stats` (exact paths as in `transport.py`).
- **Memory:** `GET/POST/PATCH/DELETE` under `/api/memory/projects` and `/api/memory/tasks` (see router).
- **Spotify:** login URL, callback, status, probe, disconnect, playlists, tracks, saved tracks, play, play-query, search, playback, pause, next (see `spotify.py`).

### BFF responsibilities

- Isolate browser from Atlas Flask URL and polling semantics for chat.
- Normalize Atlas UI to a **stable contract** for React.
- Centralize **CORS**, env loading, and transport **error mapping** (HTTP 503 for missing bundle/token where implemented).

### Integration points

- **Transport:** direct calls into `transport_engine`.
- **Atlas:** `services/atlas_http` + `services/normalize`.

---

## 7. Atlas (AI Agent)

### Flask app and session model

- **Background thread** runs `run_session()` → orchestrator until stop.
- **`/wake`:** marks session active, starts thread, pulse subprocess if configured.
- **`/sleep` / `/shutdown`:** request stop, tear down pulse.
- **`/text`:** enqueues user text into session queue; may auto-start session if inactive.

### Orchestration

- **WebSocket** connection to OpenAI Realtime (`gpt-realtime` in orchestrator).
- **`semantic_router`:** separate **OpenAI** HTTP client (JSON mode) producing `RouteDecision` — tool vs direct, tool name and args; uses `OPENAI_API_KEY`.
- **Tool execution:** `execute_tool` in `router/tool_executor.py` — async, registry-backed, updates `ui_state` and returns receipts.

### Tools (examples present in executor)

- Memory CRUD/search (`tools/memory`), web search (SerpAPI), visual board, music, CSPE shell/transport tools, image search via Flask base URL, etc.

### Communication with product shell

- HTTP **POST** to `/api/shell/enqueue` with JSON commands — **no** WebSocket from Atlas to browser.

### Triggering UI actions

- Enqueued commands consumed by **`ShellCommandListener`**; transport-specific commands may set `atlasTransportAction` for **`TransportMode`** to resolve and call transport APIs.

---

## 8. Transport / Graph Engine

### Loading data

- `transport_engine.get_bundle()` → `src.core.cache_bundle.load_or_build_graph_bundle` with explicit paths to bundle and stop index parquet under `data/derived/...`.
- Graphs keyed by mode: `all`, `metro`, `rail`, `tram`, `bus`, `other`; optional **LCC** subgraphs for connected analysis.

### Routing (high level)

- **Stop-level** shortest path on NetworkX (`src.core.queries.shortest_path` and related).
- **Station-level** routing resolves endpoints to candidate stops (`best_stop_path_between_stations` path in station-layer module), then summarizes with `summarize_path` / station path extraction as implemented in `transport_engine`.

### Stops vs stations

- **`StationLayerIndex`:** maps each stop to one `station_id`, groups stops, labels, centroids; built from graph + optional GTFS `parent_station` + proximity/name rules (see module docstring in `station_layer.py`).
- **Routing** remains on the **stop graph**; **station paths** are derived for display and station-to-station requests.

### Map generation

- Requires **Mapbox token** from `MAPBOX_TOKEN`, `MAPBOX_API_KEY`, or `MAPBOX_ACCESS_TOKEN`.
- `render_mapbox_gl_html` builds self-contained HTML with embedded token, layers for network/path/POI/station overlays; optional **3D** pitched view and Paris/IDF mask from `paris_mask` when data files exist.
- Output is **not** a static file on disk — generated per request and returned as JSON field `html`.

---

## 9. External Integrations

| Integration | Mechanism |
|-------------|-----------|
| **Mapbox** | Access token in generated Mapbox GL HTML; optional custom style URL via `MAPBOX_STYLE_URL`. |
| **OpenAI** | Realtime WebSocket + chat/completions-style client for semantic router; API key from environment. |
| **Spotify** | OAuth 2.0 Authorization Code + Bearer calls to Web API. |
| **SerpAPI** | Used from `serpapi_client` for web search and indirectly for image search flows where configured. |
| **HTTP image fetch** | Atlas `/image-proxy` fetches remote images for the client. |

---

## 10. Execution / Runtime Flow

### Startup (as scripted in `run_web_app.ps1`)

Typical full stack:

1. **Atlas API:** `python -m src.atlas_client.app.run_api` with `PYTHONPATH` set to Atlas tree — Flask listens (default **5055** per `run_api` `app.run`).
2. **Wake service (optional):** separate process running `wake_service/main.py`.
3. **Product shell:** `uvicorn backend.product_shell.main:app` — documented scripts use **8787**, `PYTHONPATH` = repo root.
4. **Vite:** `npm run dev` in `frontend/` — **5173**, proxies `/api` to product shell unless overridden.

Environment variables commonly referenced: `PRODUCT_SHELL_URL`, `CSPE_FRONTEND_URL` (for tools opening the web app), `ATLAS_API_BASE`, Mapbox tokens, `OPENAI_API_KEY`, Spotify client id/secret/redirect, `VITE_*` for frontend.

### Request path (example)

**Browser → transport map:**  
Browser `POST /api/transport/map` → FastAPI → `transport_engine.render_transport_map_html` → NetworkX + `plot_mapbox` → HTML string → JSON → iframe blob URL.

**Browser → chat:**  
Browser `POST /api/chat` → FastAPI → Atlas `/text` + `/ui` polling → normalize → JSON → Zustand.

---

## 11. Limitations & Technical Constraints (code-based)

- **Process coupling:** Chat and voice require **Atlas** running and reachable; failures surface as HTTP errors or empty/error-normalized outputs.
- **Single-consumer shell queue:** `poll` **clears** the queue — multiple tabs race; last poller wins.
- **No database migration layer** described for product SQLite beyond `init_db` — schema evolution is manual.
- **Two memory systems** (product SQLite vs Atlas SQLite) — no automatic sync in routers.
- **Heavy in-process work:** Large graph and map generation share the FastAPI process — long requests can block workers (depends on uvicorn workers configuration; default scripts use reload single worker).
- **Data prerequisites:** Missing `graph_bundle.pkl` or Mapbox token causes **503** or explicit runtime errors in transport routes.
- **`atlas_memory_reader`:** Not wired to HTTP — dead code path for API unless integrated later.
- **Frontend/API URL consistency:** Mixed use of `apiUrl()` vs raw `/api/...` in one transport helper may break when using absolute `VITE_API_BASE`.

---

## 12. Future Evolution (inferred from structure only)

- **BFF consolidation:** Product shell already centralizes browser + tool callbacks; further features likely continue to add **router modules** and **schemas** rather than new origins.
- **Tool–UI bridge:** Richer `cspe_*` commands and normalized blocks suggest continued reliance on **structured enqueue + poll** rather than WebSockets to the browser.
- **Transport vs agent:** Clear split between **`src.core`** (data science) and **`transport_engine`** (HTTP adapter) supports evolving routing or POI without changing Atlas.
- **Possible improvements (non-prescriptive):** unified memory API, WebSocket or SSE for shell commands, stricter client API base handling, optional read endpoints using `atlas_memory_reader`, worker pool or caching for map HTML.

---

*End of document.*
