# CSPE / Atlas — Full Technical Overview

This document describes the **CSPE** (Complex Spatial Product Environment) project and its **Atlas** AI layer as implemented in the current repository. It is intended for developers, reviewers, and operators who need to understand architecture, data flow, and extension points.

**Scope:** Based on code inspection as of the current tree. Items marked **Needs verification** should be confirmed against live behavior or missing files.

---

## 1. Project overview

### What CSPE is

**CSPE** is a local full-stack application for exploring **Île-de-France public transport** with:

- Interactive **2D maps** (Mapbox GL HTML generated server-side)
- **Route planning** on precomputed NetworkX graphs (stop-level and station-level views)
- **Area exploration** (nearby stops, POIs, filters)
- Optional **3D / VR graph** viewing via GraphXR
- A **multi-mode dashboard**: transport, visual board, product memory (projects/tasks), Spotify music
- An **Atlas** voice/text assistant that interprets natural language and drives the UI through tools

Transport logic runs in Python (`src/core`, `src/viz`) and is exposed through a **FastAPI product shell** on port **8787**. The browser uses a **React + Vite** frontend on port **5173**.

### What Atlas is

**Atlas** is an embedded AI runtime under `src/work/atlas/`. It provides:

- A **Flask HTTP API** (default port **5055**) for session control, text input, and UI state
- An **OpenAI Realtime** WebSocket session for voice (when not in text-only mode)
- A **multi-step planner** (`agent_planner.py`) that maps user utterances to **registered tools**
- **Tool execution** (`tool_executor.py`) including HTTP calls back into the product shell

Atlas does **not** train models. It uses **OpenAI APIs** (and optionally **Ollama** as a planner fallback) to interpret commands; deterministic Python handles graphs, maps, routing, and UI command enqueueing.

### How they work together

```
User (browser or wake word)
    → React UI + Atlas rail (chat/voice)
    → Product shell FastAPI (:8787)
        ↔ Atlas Flask (:5055) for AI session
        ↔ src/core + src/viz for transport/maps
    → Atlas planner selects tool
    → tool_executor runs tool (often POST /api/shell/enqueue)
    → Browser polls /api/shell/poll
    → ShellCommandListener applies UI commands
    → TransportMode refreshes map / route / exploration panels
```

The product shell is the **single HTTP entry point** for the browser. Atlas tools that change the dashboard enqueue **shell commands**; the browser **polls** (or optionally uses SSE) to apply them.

---

## 2. Main architecture

### Runtime services

| Service | Port | Process | Responsibility |
|---------|------|---------|----------------|
| **Vite dev server** | 5173 | `npm run dev` in `frontend/` | React UI; proxies `/api` → 8787 |
| **Product shell (FastAPI)** | 8787 | `uvicorn backend.product_shell.main:app` | BFF: chat proxy, transport, shell queue, memory, Spotify, agent context |
| **Atlas API (Flask)** | 5055 | `python -m src.atlas_client.app.run_api` | Realtime session, planner, `/text`, `/ui`, `/wake` |
| **Wake service** | — | `src/wake_service/main.py` | Vosk wake word → Atlas `/wake` / `/sleep` |
| **GraphXR viewer** (optional) | 3000 | `npm run dev` in `viewers/graphxr/` | 3D/VR graph from session API |

### Global request flow (transport command example)

```
1. User types in Atlas rail: "show stops around Châtelet"
2. POST /api/chat → send_text_and_wait() → Atlas POST /text
3. orchestrator → run_planner_turn() → cspe_explore_area
4. tool_executor POST http://127.0.0.1:8787/api/transport/area/explore
5. transport_exploration.explore_area() resolves center, finds stops
6. shell_router.enqueue_commands(shell_commands_for_exploration(...))
7. Browser GET /api/shell/poll → transport_exploration_view + atlas_transport_action
8. Zustand store updated; TransportMode refreshMap() → POST /api/transport/map
9. plot_mapbox.render_mapbox_gl_html() returns HTML → iframe blob URL
10. Atlas final OpenAI text summarizes named stops for chat bubble
```

### ASCII diagram

```
┌─────────────┐     /api/*      ┌──────────────────┐
│   Browser   │ ──────────────► │ Product shell    │
│  React:5173 │ ◄────────────── │ FastAPI :8787    │
└──────┬──────┘   shell poll    └────────┬─────────┘
       │                                  │
       │                         imports  │
       │                                  ▼
       │                         ┌──────────────────┐
       │                         │ src/core         │
       │                         │ src/viz          │
       │                         │ transport_engine │
       │                         └──────────────────┘
       │
       │  chat/atlas proxy
       ▼
┌──────────────────┐   shell/enqueue   ┌──────────────────┐
│ Atlas Flask:5055 │ ◄──────────────── │ tool_executor    │
│ planner + RT WS  │                   │ (CSPE tools)     │
└──────────────────┘                   └──────────────────┘
```

---

## 3. Repository structure

### Top level

| Path | Status | Purpose |
|------|--------|---------|
| `frontend/` | **Current** | React + Vite product UI |
| `backend/product_shell/` | **Current** | FastAPI BFF |
| `src/core/` | **Current** | Graph loading, queries, POI index, logging |
| `src/viz/` | **Current** | Mapbox HTML, Paris mask GeoJSON |
| `src/work/atlas/` | **Current** | Atlas Flask app, planner, tools, wake service |
| `viewers/graphxr/` | **Current** | Next.js 3D/VR viewer |
| `data/` | **Current** (gitignored) | GTFS-derived artifacts, SQLite |
| `logs/` | **Current** | `health.log`, `activity.log`, `activity_compact.log` |
| `scripts/` | **Current** | Planner stress tests, transport tests |
| `tests/` | **Current** | Unit/integration tests |
| `docs/` | **Current** | Additional documentation |
| `build_data_layers.py`, `build_geometry_layers.py` | **Current** | Offline data builders |
| `run_web_app.ps1` | **Current** | Full-stack dev startup |
| `A25-iviz-main/` | **Legacy reference** | Old iviz copy; not wired to startup |
| `cspe_api/` | **Removed** | Not present in tree (was deleted) |
| `app/` (Streamlit) | **Removed** | Not present; git history shows deleted `app/app.py` |

### `frontend/` — key files

| File | Role |
|------|------|
| `src/main.tsx` | React entry |
| `src/App.tsx` | Routes: `/`, `/music` redirect, `/callback` (Spotify) |
| `src/components/AppShell.tsx` | Layout: ToolRail, modes, AtlasRailPanel, listeners |
| `src/components/ShellCommandListener.tsx` | Polls `/api/shell/poll`, applies command kinds |
| `src/components/AtlasRailPanel.tsx` | Text chat + hold-to-talk voice |
| `src/components/TransportExplorationPanel.tsx` | Nearby stops/POIs list in Atlas rail |
| `src/components/AgentContextSync.tsx` | PATCH `/api/agent/context` from Zustand |
| `src/modes/TransportMode.tsx` | Map iframe, route/search dock, Atlas action handler |
| `src/store.ts` | Zustand global state |
| `src/api/client.ts` | HTTP helpers (chat, transport, shell log) |
| `src/api/config.ts` | `apiUrl()`, GraphXR base URL |
| `src/transport/atlasTransportTypes.ts` | Shell action spec types |

### `backend/product_shell/` — key files

| File | Role |
|------|------|
| `main.py` | FastAPI app, CORS, routers, `/api/health` |
| `transport_engine.py` | Graph bundle, map HTML, search, route, 3D sessions |
| `transport_exploration.py` | Nearby stops/POIs, explore area, filter |
| `schemas.py` | Pydantic request/response models |
| `ui_transport_logger.py` | Structured transport/exploration UI logs |
| `routers/transport.py` | Transport HTTP API |
| `routers/shell.py` | Command queue poll/enqueue/SSE |
| `routers/agent.py` | Planner context, events, server-side route |
| `routers/chat.py` | Proxies to Atlas for text chat |
| `routers/atlas.py` | Input mode + UI fetch proxy |
| `routers/memory.py` | Product memory CRUD |
| `routers/spotify.py` | OAuth + playback |
| `services/agent_store.py` | In-memory world state for planner |
| `services/agent_tools.py` | Resolve stops, compute route, build shell commands |
| `services/atlas_http.py` | Atlas session + send_text_and_wait |
| `services/normalize.py` | Atlas UI → structured outputs |
| `services/product_memory_store.py` | SQLite projects/tasks |

### `src/core/` — key files

| File | Role |
|------|------|
| `cache_bundle.py` | `load_or_build_graph_bundle()`, `CACHE_VERSION=3` |
| `graph_loader.py` | GTFS → NetworkX edges (ride + transfer) |
| `queries.py` | `search_stops_autocomplete`, `shortest_path`, `summarize_path` |
| `station_layer.py` | `StationLayerIndex`, station grouping, station routing helpers |
| `poi_index.py` | `LocalPOILookup`, spatial POI search |
| `project_logs.py` | Central logging (`CSPE_LOG_MODE`, compact file) |
| `tools.py` | Hub/network helpers, `export_graphxr()` |
| `debug_log.py` | **Legacy** shim → `project_logs` |

### `src/work/atlas/` — key files

| File | Role |
|------|------|
| `src/atlas_client/app/run_api.py` | Starts Flask on **5055** |
| `src/atlas_client/app/api.py` | Flask routes: `/text`, `/ui`, `/wake`, `/health`, … |
| `src/atlas_client/core/orchestrator.py` | Realtime WebSocket loop |
| `src/atlas_client/core/agent_planner.py` | `run_planner_turn()` multi-step planner |
| `src/atlas_client/router/planner_pipeline.py` | Shortcuts → OpenAI → local fallback |
| `src/atlas_client/router/local_planner.py` | Ollama planner, `validate_planner_decision()` |
| `src/atlas_client/router/tool_executor.py` | `execute_tool()`, CSPE HTTP integration |
| `src/atlas_client/router/tools_registry.json` | Tool schemas and validation rules |
| `src/atlas_client/core/tool_instructions.py` | `build_router_catalog()` |
| `src/wake_service/main.py` | Speech wake → Atlas |

### `data/` — expected layout (gitignored)

```
data/
├── derived/
│   ├── routing/graph_bundle.pkl
│   ├── stops/stop_popup_index.parquet
│   ├── render_graphs/{mode}.render_graph.json
│   ├── maps/                          # line geometry GeoJSON
│   ├── indexes/poi_balltree.pkl|.npz
│   ├── geo/ile_de_france_admin_boundary.geojson
│   └── product_shell/map_html_cache/
├── normalized/poi/poi.parquet
├── normalized_gtfs/stops.parquet        # or normalized/gtfs/stops.parquet
└── product_memory.sqlite
```

---

## 4. Startup and runtime flow

### `run_web_app.ps1` sequence

1. Load repo-root `.env` into process environment
2. Initialize/clear log files under `logs/`
3. Set `CSPE_LOG_DIR`, `CSPE_LOG_MODE` (default `compact`), log paths
4. **Unless `-SkipAtlas`:**
   - Stop stale Atlas processes
   - Start Atlas API: `python -m src.atlas_client.app.run_api` with `PYTHONPATH=src/work/atlas`
   - Start wake service: `wake_service/main.py`
   - Wait for `http://127.0.0.1:5055/health`
5. Set `PYTHONPATH` to repo root
6. Default `PRODUCT_SHELL_URL=http://127.0.0.1:8787`, `CSPE_FRONTEND_URL=http://127.0.0.1:5173`
7. Stop stale uvicorn on 8787; start `uvicorn backend.product_shell.main:app --host 0.0.0.0 --port 8787`
8. Wait for `/api/health` with `transport_exploration: true` capability
9. `npm run dev` in `frontend/` on **0.0.0.0:5173**

On Ctrl+C: stops Vite, product shell, wake service, Atlas API.

### Environment loading

- **Python:** `backend/product_shell/main.py` → `_load_local_env()` loads repo `.env` via `python-dotenv`
- **Vite:** `vite.config.ts` sets `envDir` to repo root; reads `VITE_*` and proxy target from `.env`
- **Atlas:** `atlas_client/core/bootstrap` / config modules read env at Atlas process start

### Frontend → backend connection

- **Default dev:** Browser uses relative URLs `/api/...`; Vite proxy forwards to `8787`
- **LAN / direct API:** Set `VITE_API_BASE=http://<host>:8787`; requires CORS (`PRODUCT_SHELL_CORS_*`)

### Wake / session

- Wake service listens for phrases (e.g. "atlas wake up") and POSTs to Atlas `/wake`
- `/wake` starts background `orchestrator.session_main()` thread (Realtime WebSocket)
- `/text` enqueues user text; planner runs in orchestrator context
- `/sleep` / `/shutdown` tear down session

---

## 5. Frontend architecture

### Layout (`AppShell.tsx`)

```
┌────────────────────────────────────────────────────────────┐
│ Top bar: ATLAS - Dashboard                                 │
├──────┬─────────────────────────────────────────┬───────────┤
│ Tool │  Main content (mode-dependent)          │ Atlas     │
│ Rail │  - Transport: full-bleed map + HUD       │ Rail      │
│      │  - Visual / Memory / Music panels       │ (chat +   │
│      │                                         │  explore) │
└──────┴─────────────────────────────────────────┴───────────┘
```

- **Left:** `ToolRail` — switches `AppMode`: `transport | visual | memory | music`
- **Center:** Mode panel; **Transport stays mounted** (hidden via CSS) to preserve map iframe
- **Right:** `AtlasRailPanel` — persistent chat/voice + `TransportExplorationPanel`

### State management (`store.ts`)

Zustand store `useAppStore` holds:

- Chat history, loading, structured outputs
- Transport: graph mode, LCC, viz mode, graph viz (stop/station/hybrid), path IDs, exploration view, map errors
- **`atlasTransportAction`**: `{ seq, spec }` imperative patches for `TransportMode`
- **`transportMapFocus`**: rail list click → map center
- **`transportExplorationSeq`**: bumps on exploration view updates (logging/triggers)

### Shell command application

`ShellCommandListener.tsx`:

- Poll interval: **600 ms** (`POLL_MS`)
- Optional SSE: `VITE_SHELL_SSE=1` → `/api/shell/stream`
- **`applyOne()`** handles command `kind` values (see section 6)

Transport actions use **`enqueueAtlasTransportAction()`** with dedupe fingerprint; `exploration_map` runs are allowed to repeat for same center with new results.

### Map display (`TransportMode.tsx`)

1. `POST /api/transport/map` with body from current UI state + optional `exploration_overlay`
2. Response HTML → `Blob` → `URL.createObjectURL` → `<iframe key={mapUrl}>`
3. **`refreshMap()`** uses request sequencing (`mapFetchSeq`) to ignore stale responses
4. Exploration overlay attached when `transportExploration` store has center/stops/POIs

### Agent context sync

`AgentContextSync.tsx` PATCHes `/api/agent/context` when mode, graph mode, paths, memory project change — feeds planner via `cspe_get_current_context` / `GET /api/agent/context`.

---

## 6. Product shell backend

### Router map (all prefixed `/api`)

| Router | Notable endpoints |
|--------|-------------------|
| **health** | `GET /health` — capabilities flags |
| **chat** | `POST /chat` — Atlas text round-trip |
| **atlas** | `POST /atlas/input-mode`, `GET /atlas/ui` |
| **shell** | `POST /shell/enqueue`, `GET /shell/poll`, `GET /shell/stream`, `POST /shell/client-log` |
| **transport** | See section 10–11 |
| **agent** | `GET/PATCH /agent/context`, `POST /agent/events`, `POST /agent/transport/route`, tasks |
| **memory** | `/memory/projects`, `/memory/tasks` CRUD |
| **spotify** | OAuth, playback, search, playlists |

### `/api/agent/context`

Returns from `agent_store.get_context()`:

```json
{
  "world": { "ui_mode", "transport", "memory_project_id", "spotify", ... },
  "recent_events": [...],
  "pending_tasks": [...],
  "capabilities": { "transport": [...], "memory": [...], ... }
}
```

Planner tools read this for "current station", last exploration snapshot, UI mode.

### Shell command queue (`routers/shell.py`)

- Thread-safe `deque`, max **256** commands
- **`GET /shell/poll`**: returns all pending commands and **clears queue** (single consumer)
- **`POST /shell/enqueue`**: used by Atlas `tool_executor` and exploration sync
- Command dicts must include `"kind": "..."`

### Shell command kinds (frontend)

| `kind` | Effect |
|--------|--------|
| `set_mode` | `setMode(transport|visual|memory|music)` |
| `navigate` | React Router navigate |
| `transport_graph_mode` | Set metro/bus/rail/… |
| `transport_options` | LCC, viz, graph_viz, show_transfers |
| `transport_exploration_view` | `setTransportExploration()` |
| `transport_route_view` | Path IDs, route errors/meta |
| `atlas_transport_action` | Enqueue spec for `TransportMode` |
| `memory_project` | Set memory project id |
| `apply_structured_outputs` | Chat/visual blocks |
| `atlas_transport_intent` | **Deprecated** route-only legacy |

---

## 7. Atlas planner architecture

### Path from user text to tool

1. User message → product shell `POST /chat` → Atlas `POST /text`
2. `orchestrator` receives text; if agent planner enabled → **`run_planner_turn()`** (`agent_planner.py`)
3. **`resolve_planner_plan()`** (`planner_pipeline.py`) order:
   - **Allowlisted shortcuts** (`planner_shortcuts.py`) — fast path for fixed phrases
   - **OpenAI planner** — primary for natural language (`gpt-4o` or `ATLAS_OPENAI_PLANNER_MODEL`)
   - **Local Ollama fallback** — only if OpenAI unavailable and backend allows (`ATLAS_PLANNER_BACKEND`)
4. Plan parsed via **`parse_openai_plan_object()`** (`planner_plan.py`)
5. Each step validated: **`validate_planner_decision()`** / **`validate_and_enrich_plan()`**
6. **`execute_tool()`** runs tool; receipts collected
7. Final assistant text generated (OpenAI) unless `status=direct` or `clarify`

### Planner outcomes (`status`)

| Status | Meaning |
|--------|---------|
| `continue` | Execute one tool; may loop up to `ATLAS_PLANNER_MAX_STEPS` (default 8) |
| `done` | Turn complete after tool(s) |
| `clarify` | Ask user one question (`clarifying_question`) |
| `direct` | Pure Q&A, no tools |

### Correlation IDs

- Embedded in user text or log context as `correlation_id=...`
- **`split_correlation_id()`** strips for planning; ID propagated in `[Turn N]` log lines
- Visible in `activity_compact.log` for tracing one utterance end-to-end

### Planner logging

- **`[PlannerLive]`** lines in `activity.log` (stress tests parse these)
- Compact mode: turn summaries in `activity_compact.log` via `project_logs.log_turn_*`
- Latency: `resolve_latency_ms`, slow warnings if planner > 3000 ms

### Realtime vs text

- Atlas Realtime WebSocket handles voice audio when input mode is `voice`
- Text mode: `[InputMode] text (microphone disabled)` — planner still runs on `/text`
- Product shell chat uses text path regardless of voice UI state in rail

---

## 8. OpenAI / local model usage

### No training

The project **does not train** custom models. Models are used for:

| Use | Model / API | Module |
|-----|-------------|--------|
| Planner (NL → tool JSON) | OpenAI chat (`gpt-4o` default) | `agent_planner.py`, `planner_pipeline.py` |
| Realtime voice session | `gpt-realtime` (env override) | `orchestrator.py` |
| Final response phrasing | OpenAI | `agent_planner.py` after tools |
| Local fallback planner | Ollama (configurable model) | `local_planner.py` |
| Legacy semantic router | OpenAI JSON mode | `semantic_router.py` if planner disabled |

### Tool catalog for the model

- **`tools_registry.json`**: full schemas (inputs, enums, when_to_use)
- **`build_router_catalog()`** (`tool_instructions.py`): compact text list of tool names, descriptions, required args — injected into planner prompts
- **`list_tools()`** / **`get_tool_info()`** in `tool_executor.py`

### Structured planner JSON

OpenAI returns one JSON object (see `_PLANNER_SYSTEM` in `agent_planner.py`):

```json
{
  "status": "continue",
  "steps": [{ "tool": "cspe_explore_area", "arguments": { ... }, "reason": "..." }],
  "clarifying_question": "",
  "final_summary": ""
}
```

### Validation and rejection

- Unknown tool names → validation failure → fallback or clarify
- **`_validate_and_apply_defaults()`** in `tool_executor.py` checks required fields, types, enums from registry
- **`validate_planner_decision()`** enforces allowed tool set per turn

### Deterministic code still handles

- Graph loading, shortest path, station layer
- Map HTML generation
- Exploration geometry and POI ball tree
- Shell command construction (`agent_tools.shell_commands_for_*`)
- Spotify OAuth token refresh
- SQLite memory CRUD

---

## 9. Tool registry and execution

### Registry location

`src/work/atlas/src/atlas_client/router/tools_registry.json`

Loaded by `tool_executor._load_registry()`.

### Execution entry point

```python
async def execute_tool(name: str, args: dict, state) -> dict
```

Returns receipt: `{ ok, tool, summary, data, error }`.

### Tool categories (all registered names)

**Web / media**

| Tool | Purpose |
|------|---------|
| `web_search` | SerpAPI web search |
| `image_search` | SerpAPI image search |
| `image_proxy` | Proxy external image URLs |

**Session**

| Tool | Purpose |
|------|---------|
| `session_sleep` | Atlas sleep |
| `session_shutdown` | Shutdown Atlas session |

**Atlas agent memory** (SQLite under Atlas data dir — separate from product memory)

| Tool | Purpose |
|------|---------|
| `memory_add` | Add reminder/todo with optional `due_at` |
| `memory_search` | Search memory entries |
| `memory_update` | Update entry |
| `memory_delete` | Delete entry |
| `memory_resolve_targets` | Resolve ambiguous targets |

**Music**

| Tool | Purpose |
|------|---------|
| `music` | Spotify play/pause/resume/next via product API |

**Visual**

| Tool | Purpose |
|------|---------|
| `visual_board` | Push image panels to UI state |

**CSPE transport / UI** (HTTP to product shell)

| Tool | Purpose |
|------|---------|
| `cspe_search_stops` | Autocomplete search |
| `cspe_route` | **Legacy** route enqueue pattern |
| `cspe_compute_route` | Resolve names + compute route + optional shell sync |
| `cspe_transport_action` | Partial UI spec + `run` trigger |
| `cspe_open_transport_map` | Open transport mode / map |
| `cspe_set_mode` | App mode switch |
| `cspe_navigate` | React route |
| `cspe_transport_graph_mode` | metro/rail/bus/… |
| `cspe_transport_options` | LCC, viz, graph_viz |
| `cspe_transport_route_view` | Push path IDs to UI |
| `cspe_memory_project` | Select product memory project |
| `cspe_apply_structured_outputs` | Push chat/visual blocks |
| `cspe_open_graph3d` | Open GraphXR viewer URL |
| `cspe_get_current_context` | Read `/api/agent/context` |
| `cspe_update_map` | Refresh map-related shell state |
| `cspe_show_station_or_line_info` | Search-based info |
| `cspe_nearby_stops` | Radius stop search |
| `cspe_nearby_pois` | Radius POI search |
| `cspe_explore_area` | Combined explore + `sync_ui` |
| `cspe_filter_visible_results` | Filter last exploration |

**Product memory**

| Tool | Purpose |
|------|---------|
| `product_memory_list_projects` | List SQLite projects |
| `product_memory_create_project` | Create project |
| `product_memory_list_tasks` | List tasks |
| `product_memory_add_task` | Add task |

**Agent helpers**

| Tool | Purpose |
|------|---------|
| `agent_fetch_context` | Fetch `/api/agent/context` |

### CSPE tool → backend pattern

Most `cspe_*` tools call:

```
POST {PRODUCT_SHELL_URL}/api/shell/enqueue
POST {PRODUCT_SHELL_URL}/api/transport/...
GET  {PRODUCT_SHELL_URL}/api/agent/context
```

Base URL from `product_shell_origin()` in `atlas_client/core/config.py` (default `http://127.0.0.1:8787`).

---

## 10. Transport / CSPE core

### Graph loading

1. **`cache_bundle.load_or_build_graph_bundle()`** reads `data/derived/routing/graph_bundle.pkl`
2. Bundle version **`CACHE_VERSION=3`**; modes: `all`, `metro`, `rail`, `tram`, `bus`, `other`
3. Each mode has graphs with and without **LCC** (largest connected component filter)
4. Stop metadata joined from **`stop_popup_index.parquet`**

### GTFS / edges (`graph_loader.py`)

- Ride edges from GTFS stop sequences per route
- Transfer edges between nearby stops (mode-specific rules)
- Node attributes: lat/lon, lines, mode, popup fields

### Station layer (`station_layer.py`)

- Groups stops into **`station_id`** using GTFS `parent_station` or heuristic clustering
- **`StationLayerIndex`**: `station_to_stops`, labels, centroids
- **Routing** always on **stop graph**; station paths derived for display

### Stop search

- **`queries.search_stops_autocomplete()`** — normalized text scoring
- **`transport_engine.search_stops()`** — HTTP adapter with mode/LCC fallbacks
- Exploration uses **`resolve_exploration_center()`** in `transport_exploration.py`

### Route computation

**Stop-level:** `transport_engine.compute_route()` → `queries.shortest_path(G, a, b)`

- Default strategy: **`hops`** (unweighted shortest path in NetworkX)
- Edge weights available in graph (`weight_m`, `time_s`); summarization uses them in **`summarize_path()`**
- Transfer count: edges with `edge_kind == "transfer"`

**Station-level:** `compute_route_stations()` → tries stop pairs between station stop sets, picks best path

**Agent-side:** `agent_tools.compute_route_from_queries()` resolves names then calls compute

### Modes and LCC

| `graph_mode` | Graph slice |
|--------------|-------------|
| `metro` | Metro stops/edges |
| `bus` | Bus (large render graph) |
| `rail`, `tram`, `other` | Mode-specific |
| `all` | Combined |

**`use_lcc`**: when true, use largest connected component subgraph for routing/search stability.

### Graph viz modes (UI overlay — not routing graph)

| `graph_viz_mode` | Map behavior |
|------------------|--------------|
| `stop` | Stop markers on map |
| `station` | Station network points/lines; suppress stop markers |
| `hybrid` | Combined overlays |

### POI logic

- **`poi_index.LocalPOILookup`**: parquet + BallTree index
- Exploration: **`nearby_pois()`**, **`explore_area()`** with `poi_categories`
- Map: optional POI markers near selected stop (non-exploration)

### Exploration tools (implemented)

| API | Function |
|-----|----------|
| `GET /transport/stops/nearby` | `nearby_stops()` |
| `GET /transport/pois/nearby` | `nearby_pois()` |
| `POST /transport/area/explore` | `explore_area()` |
| `POST /transport/area/filter` | `filter_visible_results()` |

When `sync_ui=true`, enqueues:

1. `set_mode: transport`
2. `transport_exploration_view` (stops, POIs, summary)
3. `atlas_transport_action` with `run: exploration_map`

Snapshot stored in **`agent_store`** → `world.transport.last_exploration`.

---

## 11. Map rendering

### Pipeline

```
POST /api/transport/map
  → transport_engine.render_transport_map_html()
  → plot_mapbox.render_mapbox_gl_html()
  → returns (html_string, token_source)
```

### Inputs (`TransportMapRequest`)

- `mode`, `use_lcc`, `viz_mode` (geographic vs network_3d pitched)
- `path_stop_ids`, `path_station_ids`
- `selected_stop_id`, `selected_station_id`
- `exploration_overlay` (center, radius, nearby_stops/pois)
- `poi_radius_m`, `poi_limit`, `poi_category_key`

### Mapbox HTML (`plot_mapbox.py`)

- Embeds **`map_payload`** JSON in `<script>` (network GeoJSON, paths, stations, exploration layers, token)
- Loads Mapbox GL JS v3.4 from CDN
- Layers: network lines, route path, stations, transfers, exploration stop/POI circles
- **Paris/IDF mask** from `paris_mask.build_paris_mask_payload()` when GeoJSON exists
- Exploration center sets map center as **`{lon, lat}`** object (required by map init JS)

### Caching

- In-memory cache keyed by request parameters + exploration overlay string
- Disk cache under `data/derived/product_shell/map_html_cache/` for static maps (disabled when exploration overlay present)

### Frontend map update flow

1. Shell command sets exploration + `exploration_map` action
2. `TransportMode` applies patches, calls **`refreshMap()`**
3. Map HTML blob loaded in iframe
4. Logs: `[Exploration] map_render ...` in `activity_compact.log`

### Key functions

| Function | File |
|----------|------|
| `render_transport_map_html` | `transport_engine.py` |
| `render_mapbox_gl_html` | `plot_mapbox.py` |
| `_exploration_geojson` | `plot_mapbox.py` |
| `build_paris_mask_payload` | `paris_mask.py` |
| `load_line_geometries` | `plot_mapbox.py` |
| `load_render_graph` | `plot_mapbox.py` |

---

## 12. 3D graph / immersive visualization

### Session flow

1. **`POST /api/transport/graph3d/session`** → `transport_engine.create_graph3d_session()`
2. Builds graph payload (nodes, links, route highlight) for mode/LCC/path
3. Returns `session_id`, metadata
4. Frontend opens: `{GRAPHXR_BASE}/viewer?session={id}&api={PRODUCT_SHELL_URL}`
5. GraphXR **`GET /api/transport/graph3d/session/{session_id}`** fetches JSON

### Atlas tool

**`cspe_open_graph3d`** — opens viewer URL in browser; uses `VITE_GRAPHXR_VIEWER_URL` or `CSPE_FRONTEND_URL` defaults.

### Viewer stack

- **`viewers/graphxr/`** — Next.js + Babylon.js (`GraphSceneWeb.tsx`) + WebXR (`GraphSceneXR.tsx`)
- **Legacy:** `A25-iviz-main/` — reference only

### Limitations

- Separate process (port 3000) — not started by default in `run_web_app.ps1`
- Large graphs (e.g. bus mode) may be slow to render
- VR requires WebXR-capable browser/headset
- Session expiry handled server-side — **Needs verification** of TTL in `transport_engine.get_graph3d_session()`

See **`docs/GRAPHXR_3D_VR_INTEGRATION.md`** for step-by-step integration details.

---

## 13. Memory and context

### Two memory systems (not synced)

| System | Storage | Access |
|--------|---------|--------|
| **Product memory** | `data/product_memory.sqlite` | `/api/memory/*`, Memory mode UI |
| **Atlas agent memory** | Atlas SQLite (under `src/work/atlas/data/`) | `memory_*` tools |

### Agent world state (`agent_store.py`)

Patches via:

- Exploration: `_store_exploration_snapshot()` → `transport.last_exploration`
- Browser: `AgentContextSync` → `ui_mode`, `transport.graph_mode`, paths
- Shell commands: route views, mode changes

### Planner context consumption

- **`cspe_get_current_context`** / **`agent_fetch_context`** → full JSON
- Deictic queries ("near here"): **`query_from_agent_context()`** in `transport_exploration.py`
- Selected station from last exploration or UI patch

### Todos / reminders

- **`memory_add`** with `due_at` (Atlas memory) — planner enriches dates in **`enrich_memory_add_args()`**
- Product tasks: **`product_memory_add_task`** tool + Memory mode CRUD

---

## 14. Logging system

### Log files (`logs/`)

| File | Env override | Content |
|------|--------------|---------|
| `health.log` | `CSPE_HEALTH_LOG` | Startup, health checks |
| `activity.log` | `CSPE_ACTIVITY_LOG` | Full detail, `[PlannerLive]`, HTTP in debug/trace |
| `activity_compact.log` | `CSPE_COMPACT_LOG` | Human-readable tail; **default read for demos** |

Reset each run by `run_web_app.ps1` (`Initialize-ProjectLogFiles`).

### `CSPE_LOG_MODE`

| Mode | Behavior |
|------|----------|
| `compact` (default) | Summaries to compact file; suppresses noisy HTTP/client events |
| `debug` | More events to `activity.log` |
| `trace` | Verbose Realtime/planner internals |

Module: **`src/core/project_logs.py`**

### Categories

- `[Startup]`, `[Turn N]`, `[Planner]`, `[Tool]`, `[Final]`
- `[Transport]`, `[Exploration]`, `[MapRender]`
- `[Slow]` warnings: planner >3s, map >3s, HTTP >1s

### Correlation IDs

Format: `correlation_id=xxxxxxxx` on turn lines — tie planner, tools, and final response.

### Debugging exploration UI

Tail compact log:

```powershell
Get-Content logs\activity_compact.log -Wait
```

Expected chain:

```
[Exploration] api ok ...
[Exploration] shell enqueue view ...
[Exploration] ui view_applied ...
[Exploration] ui trigger exploration_map ...
[Exploration] ui map_refresh start ...
[Exploration] map_render ... html_bytes=...
[Exploration] ui map_refresh done ...
```

### UI transport logger

**`backend/product_shell/ui_transport_logger.py`** — exploration-specific compact lines; browser posts via **`POST /api/shell/client-log`**.

---

## 15. Stress tests and validation

### Live planner stress

**`scripts/test_live_planner_stress.py`**

Prerequisites: `run_web_app.ps1` running (Atlas :5055, product :8787).

```powershell
python scripts/test_live_planner_stress.py
python scripts/test_live_planner_stress.py --category 1 --category 2
```

Categories include:

1. Shortcuts / simple commands (open map, 3D graph, set mode, memory add)
2. Route shortcuts
3. Multi-step flows
4. Exploration commands (nearby stops, POIs, explore area, filters)
5. Fallback / invalid input handling

Harness: **`scripts/planner_live_test_lib.py`** — sends `POST :5055/text`, parses `[PlannerLive]` from `activity.log`.

### Other scripts

| Script | Purpose |
|--------|---------|
| `test_live_planner_flow.py` | Smaller live flows |
| `test_local_planner.py` | Ollama planner unit/benchmark |
| `test_transport_search.py` | Direct transport engine (no Atlas) |

### Unit tests

**`tests/test_transport_exploration.py`** — exploration center resolve, filter, summary.

Run: **Needs verification** of project's standard pytest invocation (likely `pytest tests/` from repo root with venv).

---

## 16. Configuration

### Environment variables (repo-root `.env`)

No committed `.env.example` at repo root; use `.env` locally.

| Variable | Purpose |
|----------|---------|
| **`OPENAI_API_KEY`** | Atlas planner + Realtime |
| **`MAPBOX_TOKEN`** / `MAPBOX_API_KEY` / `MAPBOX_ACCESS_TOKEN` | Map rendering |
| **`MAPBOX_STYLE_URL`** | Optional custom basemap |
| **`ATLAS_PYTHON`** | Python exe for Atlas subprocess |
| **`ATLAS_API_BASE`** | Product shell → Atlas URL (default `http://127.0.0.1:5055`) |
| **`PRODUCT_SHELL_URL`** | Atlas tools → BFF (default `http://127.0.0.1:8787`) |
| **`CSPE_FRONTEND_URL`** | Origin for opening React from tools |
| **`ATLAS_PLANNER_BACKEND`** | `openai`, `auto`, or local preference |
| **`ATLAS_LOCAL_PLANNER_*`** | Ollama URL, model, timeouts — see `docs/LOCAL_PLANNER.md` |
| **`ATLAS_AGENT_PLANNER`** | Enable/disable agent planner |
| **`ATLAS_PLANNER_MAX_STEPS`** | Max tool steps per turn (default 8) |
| **`ATLAS_REALTIME_MODEL`** | Realtime model id |
| **`CSPE_LOG_MODE`** | `compact` / `debug` / `trace` |
| **`CSPE_LOG_DIR`**, `CSPE_*_LOG` | Log file paths |
| **`VITE_API_BASE`** | Direct API URL from browser |
| **`VITE_DEV_PROXY_TARGET`** | Vite proxy target |
| **`VITE_GRAPHXR_VIEWER_URL`** | GraphXR base URL |
| **`VITE_SHELL_SSE`** | `1` to use shell SSE instead of poll |
| **`PRODUCT_SHELL_CORS_ORIGINS`**, `PRODUCT_SHELL_CORS_ORIGIN_REGEX` | CORS |
| **`SPOTIFY_CLIENT_ID`**, `SPOTIFY_CLIENT_SECRET`, `SPOTIFY_REDIRECT_URI` | Music mode |
| **`SERPAPI_API_KEY`** | Web/image search tools — **Needs verification** of exact env name in serpapi client |

---

## 17. Data pipeline and artifacts

### Build scripts

| Script | Output |
|--------|--------|
| **`build_data_layers.py`** | Normalized layers, POI parquet, indexes |
| **`build_geometry_layers.py`** | Line geometries, render graphs |

### Runtime artifacts

| Artifact | Loader |
|----------|--------|
| `graph_bundle.pkl` | `cache_bundle.load_or_build_graph_bundle()` |
| `stop_popup_index.parquet` | Joined in cache_bundle |
| `{mode}.render_graph.json` | `plot_mapbox.load_render_graph()` |
| `maps/*.geojson` | `plot_mapbox.load_line_geometries()` |
| `poi.parquet` + ball tree | `poi_index.load_poi_lookup()` |
| Admin boundary GeoJSON | `paris_mask.resolve_region_mask_path()` |

### Missing data behavior

| Missing | Effect |
|---------|--------|
| `graph_bundle.pkl` | HTTP **503** on transport routes |
| Mapbox token | HTTP **503** "Mapbox token missing" |
| POI index | Exploration POIs empty; `poi_index_error` in payload |
| Paris mask GeoJSON | Map renders without regional dimming mask (logged as skipped) |

---

## 18. Known limitations and current issues

Documented honestly from code and recent debugging:

| Limitation | Detail |
|------------|--------|
| **Planner latency** | OpenAI planner commonly 1.5–4 s; logged as `[Slow]` when >3 s |
| **Map render latency** | Large modes (bus/rail) produce multi-MB HTML; 3–10+ s renders |
| **Single shell consumer** | `poll` clears queue — multiple browser tabs race |
| **Queued vs confirmed UI** | Shell enqueue success ≠ map finished; check `[Exploration] ui map_refresh done` |
| **Two memory systems** | Atlas `memory_*` ≠ product SQLite memory |
| **Route accuracy** | Depends on GTFS graph completeness and hop-based routing; not a production trip planner |
| **`postRoute` URL** | Uses raw `/api/transport/route` without `apiUrl()` — breaks if `VITE_API_BASE` set |
| **GraphXR optional** | Not auto-started; user must run viewer on :3000 |
| **Legacy deleted modules** | `cspe_api`, Streamlit `app/` removed from tree |
| **`atlas_memory_reader.py`** | Referenced in older docs — **not present** in current backend tree |
| **Local planner** | Requires Ollama; quality lower than OpenAI for complex multi-step |
| **Realtime voice** | Requires mic permissions; echo possible without headphones |

---

## 19. How to extend the project

### Add a new Atlas tool

1. Add entry to **`tools_registry.json`** (name, inputs, description)
2. Implement branch in **`tool_executor._execute_tool_impl()`**
3. If UI effect needed: build shell commands; handle new `kind` in **`ShellCommandListener.applyOne()`**
4. Add planner hint to **`agent_planner._PLANNER_SYSTEM`** if non-obvious
5. Add stress test case in **`test_live_planner_stress.py`**

### Add a transport endpoint

1. Implement logic in **`transport_engine.py`** or **`transport_exploration.py`**
2. Add Pydantic models in **`schemas.py`**
3. Register route in **`routers/transport.py`**
4. Expose to Atlas via new `cspe_*` tool calling the HTTP endpoint

### Add a frontend shell action

1. Extend **`atlasTransportTypes.ts`** if using `atlas_transport_action`
2. Handle in **`TransportMode`** atlas action effect or new command kind in **`ShellCommandListener`**
3. Optionally extend **`agent_tools.shell_commands_for_*`**

### Add exploration / POI feature

1. Extend **`transport_exploration.py`**
2. Wire **`exploration_overlay`** in **`plot_mapbox._exploration_geojson()`**
3. Update **`TransportExplorationPanel.tsx`** for rail UI
4. Log via **`ui_transport_logger.log_exploration_*`**

### Add stress test command

Add `TestCase` in **`build_test_cases()`** in `test_live_planner_stress.py` with expected tool set and scorer function.

---

## 20. End-to-end examples

### Example A — Route between two stations

| Step | Component | Detail |
|------|-----------|--------|
| User | Atlas rail | "Route me from République to Châtelet" |
| Planner | `cspe_compute_route` | `from_query`, `to_query`, `sync_ui:true`, `routing_scope: station` |
| Backend | `agent_tools.compute_route_from_queries()` | Resolves station IDs, `compute_route_stations()` |
| Tool | shell enqueue | `transport_route_view` + `atlas_transport_action` `run: route` |
| UI | `TransportMode` | Resolves queries, sets path IDs, `refreshMap()` |
| Map | `/api/transport/map` | Path overlay on metro graph |
| Response | OpenAI final | "Direct trip, N transfers…" |

### Example B — Show stops around a station

| Step | Component | Detail |
|------|-----------|--------|
| User | "show me stops around Place d'Italie" |
| Planner | `cspe_explore_area` | `include_stops:true`, `radius_m:500`, `sync_ui:true` |
| Backend | `explore_area()` | 14 stops, summary with names |
| Shell | 3 commands | `set_mode`, `transport_exploration_view`, `exploration_map` |
| UI | Atlas rail | `TransportExplorationPanel` lists stops |
| Map | exploration overlay | Orange markers; center Place d'Italie |
| Logs | compact | `[Exploration] api ok … ui map_refresh done` |

### Example C — Switch to rail mode

| Step | Component | Detail |
|------|-----------|--------|
| User | "switch to rail mode" |
| Planner | `cspe_transport_graph_mode` | `{ graph_mode: "rail" }` |
| Shell | `transport_graph_mode` | Zustand `transportGraphMode=rail` |
| UI | `TransportMode` | `refreshMap()` with rail render graph |
| Response | "Rail mode activated" |

### Example D — Open 3D graph

| Step | Component | Detail |
|------|-----------|--------|
| User | "open VR mode" / "show 3D graph" |
| Planner | `cspe_open_graph3d` | `{ mode: "metro" }` |
| Tool | Opens browser URL | GraphXR viewer with new session |
| Prerequisite | GraphXR dev server on :3000 | Manual start |

### Example E — Restaurants nearby (follow-up)

| Step | Component | Detail |
|------|-----------|--------|
| User | "now restaurants around it" (after exploration) |
| Planner | `cspe_explore_area` | `include_pois:true`, `poi_categories:["restaurant"]`, same center query |
| UI | Rail panel | POI list replaces stop list |
| Map | Green POI markers | Radius circle from `radius_m` |

### Example F — Add todo (Atlas memory)

| Step | Component | Detail |
|------|-----------|--------|
| User | "remind me to leave in 15 minutes" |
| Planner | `memory_add` | `text`, enriched `due_at` |
| Storage | Atlas SQLite | Not product memory UI |
| Response | Confirmation text | |

### Example G — Ask current context

| Step | Component | Detail |
|------|-----------|--------|
| User | "what mode am I in?" |
| Planner | `cspe_get_current_context` or direct answer |
| Data | `agent_store.get_context()` | `ui_mode`, `transport.graph_mode`, `last_exploration` |
| Response | Natural language summary | |

---

## Glossary

| Term | Definition |
|------|------------|
| **Atlas** | Flask AI runtime with Realtime session and tool planner |
| **CSPE** | Overall product: transport viz + dashboard + Atlas integration |
| **Product shell** | FastAPI BFF on port 8787 |
| **Shell command** | JSON dict with `kind` field, queued for browser poll |
| **Planner turn** | One user utterance → plan → tool(s) → final response |
| **Tool receipt** | `{ ok, summary, data, error }` returned by `execute_tool` |
| **Graph mode** | Transit subset: metro, bus, rail, tram, all, other |
| **LCC** | Largest connected component — optional routing subgraph |
| **Station layer** | Mapping stops → stations for station-first UI/routing |
| **Stop graph** | NetworkX graph used for path algorithms |
| **Render graph** | Simplified geometry for map display (especially bus) |
| **Exploration overlay** | Map payload layer for nearby stops/POIs + radius |
| **Graph viz mode** | stop / station / hybrid — map marker style, not routing graph |
| **sync_ui** | Tool flag to enqueue shell commands after backend success |
| **Correlation ID** | UUID fragment linking log lines for one user turn |
| **GraphXR** | Separate Next.js 3D/VR viewer for graph sessions |
| **Product memory** | SQLite projects/tasks in Memory mode |
| **Agent memory** | Atlas SQLite via `memory_*` tools |
| **BFF** | Backend-for-frontend — product shell pattern |
| **GTFS** | General Transit Feed Specification — source stop/route data |
| **SerpAPI** | External search API for web/image tools |

---

## Document metadata

| Item | Value |
|------|-------|
| **File** | `docs/PROJECT_FULL_TECHNICAL_OVERVIEW.md` |
| **Generated from** | Repository source inspection |
| **Companion docs** | `ARCHITECTURE_OVERVIEW.md`, `docs/GRAPHXR_3D_VR_INTEGRATION.md`, `docs/LOCAL_PLANNER.md`, `viewers/README.md` |

### Confidently documented areas

- Startup scripts, ports, and service responsibilities
- Frontend layout, Zustand store, shell polling, transport map flow
- Product shell routers and transport/exploration pipeline
- Atlas planner pipeline, tool registry, CSPE tool HTTP pattern
- Graph loading, routing, station layer, map HTML generation
- Logging modes and exploration debug log lines
- Data artifact paths and missing-file behavior
- Legacy vs current components (deleted Streamlit/cspe_api)

### Areas needing verification

- Exact GraphXR session TTL and disk storage path for sessions
- SerpAPI environment variable name(s) in production `.env`
- Full pytest CI command if configured outside `tests/`
- Spotify token file default path on all platforms
- Whether `semantic_router` is still reachable with default env (`ATLAS_AGENT_PLANNER` defaults)

For those items, inspect the cited files live or run the stack with `CSPE_LOG_MODE=debug`.
