# CSPE Project Technical Documentation

This document describes how the CSPE (Combined Spatial Product Environment) codebase works today, based on inspection of the repository files listed throughout. It is descriptive only: it records current behavior as implemented in code, not intended future design.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Runtime Architecture and Ports](#2-runtime-architecture-and-ports)
3. [Startup and Process Flow](#3-startup-and-process-flow)
4. [Frontend (React / Vite)](#4-frontend-react--vite)
5. [Product Shell Backend (FastAPI)](#5-product-shell-backend-fastapi)
6. [Atlas Agent (Flask + Orchestrator)](#6-atlas-agent-flask--orchestrator)
7. [Planner System](#7-planner-system)
8. [Tool Registry and Executor](#8-tool-registry-and-executor)
9. [Shell Command Bridge (UI Sync)](#9-shell-command-bridge-ui-sync)
10. [Local Transport Graph and Data System](#10-local-transport-graph-and-data-system)
11. [Transport Flows: Search, Route, Exploration, Map](#11-transport-flows-search-route-exploration-map)
12. [Place Lookup and IDFM Integration](#12-place-lookup-and-idfm-integration)
13. [Memory, Music, and Visual Modes](#13-memory-music-and-visual-modes)
14. [GraphXR 3D Viewer](#14-graphxr-3d-viewer)
15. [External APIs and Integrations](#15-external-apis-and-integrations)
16. [Environment Variables and Configuration](#16-environment-variables-and-configuration)
17. [Data Files, Caches, and Generated Artifacts](#17-data-files-caches-and-generated-artifacts)
18. [Logging and Debugging](#18-logging-and-debugging)
19. [Typical User Question Execution Paths](#19-typical-user-question-execution-paths)

---

## 1. Overview

CSPE is a multi-service web application for Paris-area transit exploration, AI-assisted chat (Atlas), memory tasks, music (Spotify), and map/visualization. The system splits responsibilities as follows:

| Layer | Technology | Primary path | Role |
|-------|------------|--------------|------|
| Browser UI | React 18 + Vite + Zustand | `frontend/` | Modes (transport, memory, music, visual), map iframe, Atlas chat rail |
| Product Shell API | FastAPI (uvicorn) | `backend/product_shell/` | Transport engine, shell command queue, agent context, chat proxy to Atlas, memory DB, Spotify OAuth |
| Atlas Agent | Flask + asyncio WebSocket | `src/work/atlas/src/atlas_client/` | Voice/text session, planner, tool execution, OpenAI Realtime answers |
| Wake service | Python + Vosk | `src/work/atlas/src/wake_service/` | Keyword wake/sleep for Atlas session |
| GraphXR viewer | Next.js | `viewers/graphxr/` | Embedded 3D/VR graph viewer |
| Core graph/POI libs | Python | `src/core/`, `src/viz/` | GTFS graph bundle, POI index, Mapbox HTML rendering |

The canonical dev stack launcher is `run_web_app.ps1` at the repository root.

---

## 2. Runtime Architecture and Ports

| Service | Default port | Entry / URL | Inspected files |
|---------|--------------|-------------|-----------------|
| Vite frontend | 5173 | `npm run dev` in `frontend/` | `run_web_app.ps1`, `frontend/vite.config.ts` |
| Product Shell (FastAPI) | 8787 | `backend.product_shell.main:app` | `backend/product_shell/main.py`, `run_product_shell.ps1` |
| Atlas API (Flask) | 5055 | `python -m src.atlas_client.app.run_api` | `src/work/atlas/src/atlas_client/app/run_api.py`, `app/api.py` |
| GraphXR viewer | 3000 | `npm run dev` in `viewers/graphxr/` | `run_web_app.ps1`, `viewers/graphxr/` |
| Ollama (optional local planner) | 11434 | External | `local_planner.py` reads `ATLAS_LOCAL_PLANNER_URL` |

**Request flow (text chat):**

```
Browser → POST /api/chat (8787)
       → atlas_http.send_text_and_wait()
       → POST /text (5055 Atlas)
       → orchestrator route_and_handle → planner → execute_tool
       → HTTP/enqueue back to Product Shell (8787)
       → shell commands via SSE/poll → ShellCommandListener → Zustand store → TransportMode
```

**Proxy behavior:** By default the frontend uses same-origin `/api/*` URLs. Vite dev server proxies `/api` to port 8787 unless `VITE_API_BASE` is set (`frontend/src/api/config.ts`).

---

## 3. Startup and Process Flow

### 3.1 `run_web_app.ps1`

**File:** `run_web_app.ps1`

**Sequence:**
1. Loads repo `.env` via `Import-RepoDotEnv`
2. Initializes log files under `logs/` (`health.log`, `activity.log`, `activity_compact.log`)
3. Starts Atlas headless: `python -m src.atlas_client.app.run_api` + wake service; waits for `http://127.0.0.1:5055/health`
4. Starts Product Shell on 8787 via uvicorn; waits for `/api/health` with `capabilities.transport_exploration=true`
5. Runs product warmup (`Wait-ProductShellWarm`) and `Warm-AtlasTextSession` → `POST /api/atlas/input-mode` with `mode: text`
6. Starts GraphXR on 3000 (unless `-SkipGraphXR`)
7. Starts Vite on 5173 in foreground

**Sets env vars:** `PYTHONPATH`, `CSPE_LOG_*`, `PRODUCT_SHELL_URL`, `CSPE_FRONTEND_URL`, `VITE_GRAPHXR_VIEWER_URL`, optional `GRAPHXR_PORT`

### 3.2 Product Shell startup

**File:** `backend/product_shell/main.py`

**Functions:**
- `_load_local_env()` — loads repo-root `.env` via `python-dotenv` before router imports
- `_project_log_middleware` — logs every HTTP request via `log_http_line`
- `_log_product_shell_ready()` — FastAPI startup event; calls `warmup.start_background_warmup()`

**Routers mounted at `/api`:** `agent`, `atlas`, `chat`, `shell`, `transport`, `memory`, `spotify`

### 3.3 Background warmup

**File:** `backend/product_shell/services/warmup.py`

**Trigger:** `start_background_warmup()` on Product Shell startup (disabled when `PRODUCT_SHELL_WARMUP=0`)

**Function `_run_warmup()` steps (via `_timed_step`):**
1. `transport_engine.get_bundle`
2. `graph_stats` (metro, all)
3. `station_layer_for` (metro, LCC on/off)
4. `line_geometries`, `render_graphs`
5. `poi_lookup`
6. Optional map HTML renders if Mapbox token present

**Output:** Status dict returned by `warmup_status()` and exposed on `GET /api/health`

---

## 4. Frontend (React / Vite)

### 4.1 Application shell

**Files:**
- `frontend/src/main.tsx` — React root
- `frontend/src/App.tsx` — React Router: `/` → `AppShell`, `/callback` → Spotify OAuth
- `frontend/src/components/AppShell.tsx` — layout: `ToolRail`, mode panels, `AtlasRailPanel`, global listeners

**Global listeners mounted in `AppShell`:**
- `ShellCommandListener` — drains `/api/shell/poll` or SSE `/api/shell/stream`
- `AgentContextSync` — PATCHes `/api/agent/context` when UI transport/memory state changes
- `MapFocusHotkey` — keyboard shortcuts

**Mode components:**
| Mode | Component | File |
|------|-----------|------|
| transport | `TransportMode` | `frontend/src/modes/TransportMode.tsx` |
| visual | `VisualBoardMode` | `frontend/src/modes/VisualBoardMode.tsx` |
| memory | `MemoryMode` | `frontend/src/modes/MemoryMode.tsx` |
| music | `MusicMode` | `frontend/src/modes/MusicMode.tsx` |

`TransportMode` stays mounted (hidden via CSS) when switching modes so the map iframe is not destroyed.

### 4.2 Global state (Zustand)

**File:** `frontend/src/store.ts`

**Type:** `useAppStore` hook

**Key state fields:**
- `mode` — `AppMode`: `"transport" | "visual" | "memory" | "music"`
- Transport: `transportGraphMode`, `transportUseLcc`, `transportViz`, `transportGraphViz`, `transportPathIds`, `transportStationPathIds`, `transportRouteLegs`, `transportRouteMeta`, `transportRouteError`, `transportExploration`, `transportExplorationSeq`, `transportMapSelectionStopId`, `transportMapSelectionStationId`, `atlasTransportActions`
- Chat: `history`, `chatLoading`, `chatError`
- Memory: `memoryProjectId`

**Key actions:**
- `setTransportExploration(v)` — sets exploration view and increments `transportExplorationSeq`
- `enqueueAtlasTransportAction(spec)` — queues `AtlasTransportActionSpec` for `TransportMode` to process
- `applyChatResponse(outputs, err)` — ingests structured chat blocks into history

### 4.3 API client

**File:** `frontend/src/api/client.ts`

**Transport-related functions:**
- `postTransportMap(body)` → `POST /api/transport/map`
- `postTransportExplorationOverlay(body)` → `POST /api/transport/map/exploration-overlay`
- `postTransportRouteOverlay(body)` → `POST /api/transport/map/route-overlay`
- `searchStops(q, mode, useLcc, stationFirst)` → `GET /api/transport/stops/search`
- `postRoute(body)` → `POST /api/transport/route`
- `postTransportGraph3DSession(body)` → `POST /api/transport/graph3d/session`
- `postShellClientLog(event, data)` → `POST /api/shell/client-log`

**Chat:** `postChat(message)` → `POST /api/chat`

**Config:** `frontend/src/api/config.ts` — `getApiBase()`, `apiUrl()`, `getGraphXRViewerBase()`, `getExternalApiBase()`

### 4.4 Atlas text chat hook

**File:** `frontend/src/hooks/useAtlasTextChat.ts`

**Function:** `useAtlasTextChat()`

**Flow:**
1. User submits draft text
2. `appendUserMessage(t)` → store
3. `postChat(t)` → Product Shell → Atlas
4. `applyChatResponse(r.structured_outputs, r.error)` → store history

**Used by:** `AtlasRailPanel`, `AtlasFocusBar`

### 4.5 Shell command application

**File:** `frontend/src/components/ShellCommandListener.tsx`

**Trigger:** SSE event `commands` (default) or poll every 300ms when `VITE_SHELL_SSE=0`

**Function:** `applyOne(raw, navigate)` — switch on `kind`:

| `kind` | Effect |
|--------|--------|
| `set_mode` | `useAppStore.setMode` |
| `navigate` | React Router navigate |
| `transport_graph_mode` | `setTransportGraphMode`; may clear route state |
| `transport_options` | `setTransportUseLcc`, `setTransportViz`, `setTransportGraphViz`, `setShowTransfers` |
| `transport_exploration_view` | `setMode("transport")`, `setTransportExploration(view)` |
| `transport_graph3d_sync` | `setTransportViz("graph3d")`, register sync client |
| `transport_route_view` | path IDs, legs, meta, error |
| `atlas_transport_action` | `enqueueAtlasTransportAction(normalizeAtlasTransportSpec(...))` |
| `memory_project` | `setMemoryProjectId` |
| `apply_structured_outputs` | `applyChatResponse` |

### 4.6 Transport mode and map

**File:** `frontend/src/modes/TransportMode.tsx`

**Exported:** `TransportMode`

**Key internal mechanisms:**
- `executeBaseMapRefresh` — calls `postTransportMap` with body from `buildTransportBaseMapBody()`
- `applyExplorationOverlay` — calls `postTransportExplorationOverlay` with `buildTransportExplationOverlayBody()`
- `scheduleExplorationOverlay` / `scheduleBaseMapRefresh` — debounced via `createMapRefreshScheduler` (`mapRefreshScheduler.ts`)
- Processes `atlasTransportActions` queue: runs `exploration_map`, `route`, `search_map`, `compute`, etc.
- `showMapbox` — true when `transportViz === "geographic" | "network_3d"`; exploration overlay scheduling is gated on this

**Map iframe bridge:** `frontend/src/transport/mapExplorationBridge.ts`
- `subscribeMapIframeMessages` — listens for `cspe-map-ready`, `cspe-map-exploration-applied`
- `postExplorationToMapIframe`, `postRouteToMapIframe` — postMessage to iframe

**View state builders:** `frontend/src/transport/transportViewState.ts`
- `readTransportViewContext()`, `buildTransportMapBody()`, `buildTransportExplorationOverlayBody()`, `buildGraph3DSessionBody()`

**Exploration rail panel:** `frontend/src/components/TransportExplorationPanel.tsx`
- Renders when `transportExploration` has `nearby_stops` or `nearby_pois`
- Shown inside `AtlasRailPanel`

### 4.7 Agent context sync

**File:** `frontend/src/components/AgentContextSync.tsx`

**Trigger:** useEffect on mode, memory project, transport graph mode, LCC, path IDs, route error/meta

**Action:** `patchAgentContext({ ui_mode, memory_project_id, transport: { graph_mode, use_lcc, path_ids, ... } })`

**Endpoint:** `PATCH /api/agent/context` (via `frontend/src/api/agentFeedback.ts`)

---

## 5. Product Shell Backend (FastAPI)

### 5.1 Entry point

**File:** `backend/product_shell/main.py`

**App:** `FastAPI(title="CSPE Product Shell API", version="0.1.0")`

### 5.2 API routes summary

All routes are prefixed with `/api`.

#### Health
| Method | Path | Handler | File |
|--------|------|---------|------|
| GET | `/health` | `health()` | `main.py` |

#### Agent — `routers/agent.py`
| Method | Path | Handler |
|--------|------|---------|
| GET | `/agent/context` | `get_agent_context()` |
| PATCH | `/agent/context` | `patch_agent_context()` |
| POST | `/agent/events` | `post_agent_event()` |
| GET | `/agent/events` | `get_agent_events()` |
| POST | `/agent/transport/route` | `post_agent_transport_route()` |
| POST | `/agent/transport/place-lookup` | `post_agent_place_lookup()` |
| POST | `/agent/tasks` | `post_agent_task()` |
| GET | `/agent/tasks/{task_id}` | `get_agent_task()` |

#### Atlas proxy — `routers/atlas.py`
| Method | Path | Handler |
|--------|------|---------|
| POST | `/atlas/input-mode` | `post_atlas_input_mode()` |
| GET | `/atlas/ui` | `get_atlas_ui()` |

#### Chat — `routers/chat.py`
| Method | Path | Handler |
|--------|------|---------|
| POST | `/chat` | `post_chat()` |

**`post_chat` flow:**
1. Records shell stats before/after
2. Calls `atlas_http.send_text_and_wait(body.message)`
3. Normalizes Atlas `/ui` via `normalize.normalize_atlas_ui(ui)`
4. Returns `ChatResponse(structured_outputs, raw_ui, error)`

#### Shell — `routers/shell.py`
| Method | Path | Handler |
|--------|------|---------|
| POST | `/shell/enqueue` | `shell_enqueue()` |
| POST | `/shell/client-log` | `shell_client_log()` |
| GET | `/shell/poll` | `shell_poll()` |
| GET | `/shell/stats` | `shell_stats_route()` |
| GET | `/shell/stream` | `shell_stream()` (SSE) |

**Module function:** `enqueue_commands(commands)` — appends to in-memory deque (max 256) and pushes to SSE subscribers

#### Transport — `routers/transport.py`
| Method | Path | Handler |
|--------|------|---------|
| GET | `/transport/bundle-health` | `get_bundle_health()` |
| POST | `/transport/map` | `post_transport_map()` |
| POST | `/transport/map/exploration-overlay` | `post_transport_exploration_overlay()` |
| POST | `/transport/map/route-overlay` | `post_transport_route_overlay()` |
| POST | `/transport/graph3d/session` | `post_transport_graph3d_session()` |
| GET | `/transport/graph3d/session/{session_id}` | `get_transport_graph3d_session()` |
| POST | `/transport/graph3d/sync` | `post_transport_graph3d_sync()` |
| GET | `/transport/graph3d/sync/{client_id}` | `get_transport_graph3d_sync()` |
| GET | `/transport/stops/search` | `get_stops_search()` |
| POST | `/transport/route` | `post_transport_route()` |
| GET | `/transport/stops/nearby` | `get_stops_nearby()` |
| GET | `/transport/pois/nearby` | `get_pois_nearby()` |
| POST | `/transport/area/explore` | `post_area_explore()` |
| POST | `/transport/area/filter` | `post_area_filter()` |
| GET | `/transport/stats` | `get_transport_stats()` |

**`sync_ui` query/body flag:** When true and result `ok`, exploration/route handlers call `agent_tools.shell_commands_for_*` and `shell_router.enqueue_commands()`.

#### Memory — `routers/memory.py`
CRUD for projects and tasks backed by SQLite (`product_memory_store.py`).

#### Spotify — `routers/spotify.py`
OAuth, playback, search, playlists endpoints (reads `SPOTIFY_*` env vars).

### 5.3 Schemas

**File:** `backend/product_shell/schemas.py`

Pydantic models for all request/response bodies including:
- `ChatRequest`, `ChatResponse`
- `TransportMapRequest`, `TransportRouteRequest`, `TransportExploreAreaRequest`
- `AgentTransportRouteRequest`, `AgentPlaceLookupRequest`
- `AgentContextPatch`, `AgentEventBody`
- Memory project/task models

### 5.4 Agent world state

**File:** `backend/product_shell/services/agent_store.py`

**Functions:**
- `get_context()` — returns `{ world, recent_events, pending_tasks, capabilities }`
- `patch_world_state(patch)` — merges transport dict shallowly
- `record_event(event, data, source)` — deque max 500 events

**Default `world` keys:** `ui_mode`, `transport`, `memory_project_id`, `spotify`, `last_shell_commands`, `updated_at`

**Transport sub-keys used in code:** `last_exploration`, `last_place_lookup`, `selected_station`, graph/route fields patched from frontend

### 5.5 Agent composite tools

**File:** `backend/product_shell/services/agent_tools.py`

| Function | Role |
|----------|------|
| `resolve_stop_query(query, ...)` | Name → stop/station match via `transport_engine.search_stops` |
| `compute_route_from_queries(from, to, ...)` | Resolve endpoints + `transport_engine.compute_route` |
| `shell_commands_for_route(route_payload)` | Builds shell commands: `set_mode`, `transport_route_view`, `atlas_transport_action` |
| `shell_commands_for_exploration(exploration)` | Builds: `set_mode`, `transport_exploration_view`, `atlas_transport_action` with `run: exploration_map` |
| `lookup_place_for_chat(query, kind, topic, ...)` | Station/POI resolution + IDFM enrichment + web query builder |
| `create_graph3d_for_route(...)` | Creates Graph3D session from route result |

### 5.6 Atlas HTTP client

**File:** `backend/product_shell/services/atlas_http.py`

| Function | Calls |
|----------|-------|
| `atlas_base_url()` | Reads `ATLAS_API_BASE`, default `http://127.0.0.1:5055` |
| `ensure_atlas_session_text_mode()` | `GET /health`, `POST /wake`, `POST /mode` |
| `send_text_and_wait(user_message)` | `POST /text`, polls `GET /ui` until turn completes |
| `fetch_atlas_ui()` | `GET /ui` |

### 5.7 UI response normalization

**File:** `backend/product_shell/services/normalize.py`

**Function:** `normalize_atlas_ui(ui)` → list of structured blocks:
- `{ type: "text", role: "assistant", content }` from `ui.assistant`
- `{ type: "visual_board", panels }` from `ui.panels`
- `{ type: "image_results", images }` flattened from panels
- `{ type: "system_status", status }` from `ui.status`

---

## 6. Atlas Agent (Flask + Orchestrator)

### 6.1 Flask API

**Files:**
- `src/work/atlas/src/atlas_client/app/run_api.py` — runs Flask on `127.0.0.1:5055`
- `src/work/atlas/src/atlas_client/app/api.py`

| Route | Function | Behavior |
|-------|----------|----------|
| GET `/health` | `health()` | Session status |
| POST `/wake` | `wake()` | Starts `run_session()` in background thread |
| POST `/sleep` | `sleep()` | `request_stop()` |
| POST `/text` | `text()` | `enqueue_user_text()` |
| POST `/shutdown` | `shutdown()` | SIGTERM |
| GET/POST `/mode` | `mode()` | `"voice"` or `"text"` input mode |
| GET `/ui` | (ui route) | Returns assistant text, panels, status for polling |

### 6.2 Orchestrator session

**File:** `src/work/atlas/src/atlas_client/core/orchestrator.py`

**Entry:** `session_main()` — async WebSocket loop to OpenAI Realtime

**WebSocket URL:** `wss://api.openai.com/v1/realtime?model={ATLAS_REALTIME_MODEL}` (default `gpt-realtime`)

**Key inner functions:**
- `route_and_handle(user_text)` — server-side routing; no tool calls from Realtime model itself
- `text_consumer()` — drains typed text queue
- `safe_create_response()` — sends Realtime `response.create` (text-only output)

**Routing inside `route_and_handle`:**
1. Memory guardrails (forced `memory_search`, `memory_delete`, order questions)
2. If `ATLAS_AGENT_PLANNER` enabled (default): `run_planner_turn(...)` from `agent_planner.py`
3. Else: legacy `route_semantic(...)` from `core/semantic_router.py`
4. Injects results into Realtime via `conversation.item.create` + `response.create`
5. Azure TTS via `azure_tts_player.speak_if_voice()` for voice mode clarifications

### 6.3 Session state

**File:** `src/work/atlas/src/atlas_client/core/session_state.py`

| Function / symbol | Role |
|-------------------|------|
| `SessionState` enum | IDLE, CONNECTING, RUNNING, STOPPING |
| `enqueue_user_text` / `drain_user_text` | Text input queue |
| `set_input_mode` / `get_input_mode` | `"voice"` or `"text"` |
| `update_router_context` / `get_router_context` | Cross-turn planner memory |
| `format_router_context_summary()` | String injected into planner prompts |

**Router context keys:** `topic`, `last_user`, `last_assistant`, `last_tool`, `last_tool_args`, `last_tool_result`, `last_place_focus`, `last_memory_items`, `last_cspe_transport`

### 6.4 Wake service

**File:** `src/work/atlas/src/wake_service/main.py`

- Vosk speech recognition loop
- Wake phrase → `POST http://127.0.0.1:5055/wake`
- Sleep phrase → `POST /sleep`
- Model path: `VOSK_MODEL_PATH` (default `./models/vosk-model-small-en-us-0.15`)

**Note:** `session_sleep` planner tool calls `request_stop()` in-process; this is separate from the wake service HTTP sleep.

### 6.5 Tool catalog for planner

**File:** `src/work/atlas/src/atlas_client/core/tool_instructions.py`

| Function | Output |
|----------|--------|
| `build_router_catalog()` | Compact text list of all tools from registry for planner/router prompts |
| `build_tool_instructions()` | JSON tool call examples for Realtime session instructions |

**Source of tool list:** `tool_executor.list_tools()` reading `tools_registry.json`

---

## 7. Planner System

The planner selects registered tools and arguments from natural language. Unknown tools are rejected before execution (`validate_planner_decision` in `local_planner.py`).

### 7.1 Pipeline routing order

**File:** `src/work/atlas/src/atlas_client/router/planner_pipeline.py`

**Function:** `resolve_planner_plan(...)`

**Order:**
1. **Allowlisted shortcuts** — `try_planner_shortcut()` in `planner_shortcuts.py`
2. **OpenAI Chat Completions planner** — primary path when backend is `openai` or `auto`
3. **Local Ollama planner** — fallback when OpenAI unavailable and backend is `local`/`auto`

**Output enrichment:** `validate_and_enrich_plan()` in `planner_plan.py` calls `enrich_planner_decision()` per step.

### 7.2 Multi-step planner entry

**File:** `src/work/atlas/src/atlas_client/core/agent_planner.py`

**Function:** `run_planner_turn(user_text, tools_catalog_text, allowed_tools, context_text, execute_tool, state)`

**Flow:**
1. `_fetch_agent_context()` → `GET /api/agent/context`
2. `resolve_planner_plan(...)` with `_plan_next_step_openai()` callback
3. For each validated step: `execute_tool(tool_name, args)`
4. Builds `PlannerTurnResult` with `injection_block` for Realtime model

**Dataclasses:** `PlannerStep`, `PlannerTurnResult`

**Env:** `ATLAS_AGENT_PLANNER` (default on), `ATLAS_PLANNER_MAX_STEPS` (default 8), `ATLAS_PLANNER_MODEL` / `ATLAS_ROUTER_MODEL`

### 7.3 Local planner

**File:** `src/work/atlas/src/atlas_client/router/local_planner.py`

| Function | Role |
|----------|------|
| `plan_next_step_local(...)` | Ollama JSON planner |
| `enrich_planner_decision(decision, user_text, agent_context)` | Applies routing enrichers |
| `validate_planner_decision(decision, allowed_tools)` | Schema validation via `_validate_and_apply_defaults` |

**Enrichment order in `enrich_planner_decision`:**
1. Strip correlation IDs from args
2. `memory_add` arg enrichment
3. `apply_exploration_routing()` — `planner_exploration.py`
4. `apply_place_info_routing()` — `planner_place_info.py`

### 7.4 Deterministic shortcuts

**File:** `src/work/atlas/src/atlas_client/router/planner_shortcuts.py`

**Allowlisted tools (`ALLOWLISTED_SHORTCUT_TOOLS`):**
- `session_sleep`, `session_shutdown`
- `cspe_open_graph3d`, `cspe_set_mode`, `cspe_transport_action`
- `cspe_lookup_place_online`
- `cspe_nearby_pois`, `cspe_nearby_stops`, `cspe_explore_area`

**Function:** `try_planner_shortcut(user_text, allowed_tools, agent_context)`

**Patterns handled (non-exhaustive, from code):**
- Sleep/shutdown phrases
- Open 3D graph
- Switch to transport mode
- Reset/clear route/map/UI
- Exploration intents (via `detect_exploration_intent`)
- Place info intents (via `detect_place_info_intent`)

### 7.5 Place info routing

**File:** `src/work/atlas/src/atlas_client/router/planner_place_info.py`

| Function | Role |
|----------|------|
| `detect_place_info_intent(user_text, agent_context)` | Detects station/POI info questions (hours, accessibility, disruptions, about, reviews) |
| `apply_place_info_routing(decision, user_text, agent_context)` | Rewrites mis-routed tools → `cspe_lookup_place_online` |
| `PlaceInfoIntent` | dataclass: `query`, `topic`, `kind`, `includes_today` |

**Uses:** `resolve_conversation_focus()` for follow-ups like "what are the working hours"

**Never redirects from:** exploration tools, route tools, filter tools

### 7.6 Exploration routing

**File:** `src/work/atlas/src/atlas_client/router/planner_exploration.py`

| Function | Role |
|----------|------|
| `detect_exploration_intent(user_text, agent_context)` | Detects map exploration (POIs/stops/area around a place) |
| `apply_exploration_routing(decision, user_text, agent_context)` | Rewrites chat-only tools → `cspe_nearby_pois`, `cspe_nearby_stops`, or `cspe_explore_area` with `sync_ui: true` |
| `ExplorationIntent` | dataclass: `tool`, `query`, `radius_m`, `categories`, `include_stops`, `include_pois` |

### 7.7 Semantic validation

**File:** `src/work/atlas/src/atlas_client/router/planner_validator.py`

**Function:** `validate_step_semantics(tool, args, user_text, agent_context)`

**Examples of checks:**
- Place info questions must not use `web_search` or `cspe_show_station_or_line_info`
- Exploration intents reject `cspe_lookup_place_online`
- `cspe_compute_route` requires `from_query` and `to_query`
- Exploration tools force `sync_ui: true`
- Radius bounds 50–3000m

### 7.8 Domain-scoped tool filtering

**File:** `src/work/atlas/src/atlas_client/router/planner_domains.py`

| Function | Role |
|----------|------|
| `classify_planner_domain(user_text)` | Returns domain string |
| `filter_allowed_tools(all_tools, domain)` | Subset of tools per domain |
| `build_compact_catalog(tools)` | Shorter catalog for local planner |

**Domains:** `transport`, `memory`, `music`, `visual`, `web`, `direct`, `general`

### 7.9 Legacy semantic router

**File:** `src/work/atlas/src/atlas_client/core/semantic_router.py`

**Used when:** `ATLAS_AGENT_PLANNER=0` in orchestrator

**Function:** `route_semantic(user_text, tools_catalog_text, allowed_tools, context_text)` → `RouteDecision`

**Model:** OpenAI Chat Completions (`ATLAS_ROUTER_MODEL`, default `gpt-4o-mini`)

### 7.10 Conversation focus

**File:** `src/work/atlas/src/atlas_client/router/conversation_focus.py`

**Function:** `resolve_conversation_focus(agent_context, router_context)`

**Sources (priority inspected in code):**
1. `world.transport.last_place_lookup`
2. Router `last_place_focus`
3. `world.transport.last_exploration.center`
4. Last exploration tool args from router context

---

## 8. Tool Registry and Executor

### 8.1 Registry

**File:** `src/work/atlas/src/atlas_client/router/tools_registry.json`

**Total registered tools:** 38 (top-level `"name"` entries)

| # | Tool name | Category |
|---|-----------|----------|
| 1 | `web_search` | External search (SerpAPI) |
| 2 | `image_search` | SerpAPI images |
| 3 | `image_proxy` | Image proxy |
| 4 | `music` | Spotify playback |
| 5 | `visual_board` | Image panel generation |
| 6 | `session_sleep` | Stop Atlas session |
| 7 | `session_shutdown` | Shutdown Atlas |
| 8 | `memory_add` | Atlas memory store |
| 9 | `memory_search` | Atlas memory search |
| 10 | `memory_update` | Atlas memory update |
| 11 | `memory_delete` | Atlas memory delete |
| 12 | `memory_resolve_targets` | Memory target resolution |
| 13 | `cspe_search_stops` | Stop/station search |
| 14 | `cspe_route` | Shell enqueue route action |
| 15 | `cspe_transport_action` | Shell enqueue transport spec |
| 16 | `cspe_open_transport_map` | Opens browser to frontend URL |
| 17 | `cspe_set_mode` | Shell `set_mode` |
| 18 | `cspe_navigate` | Shell `navigate` |
| 19 | `cspe_transport_graph_mode` | Shell `transport_graph_mode` |
| 20 | `cspe_transport_options` | Shell `transport_options` |
| 21 | `cspe_transport_route_view` | Shell `transport_route_view` |
| 22 | `cspe_memory_project` | Shell `memory_project` |
| 23 | `cspe_apply_structured_outputs` | Shell structured outputs |
| 24 | `cspe_compute_route` | Server-side route + optional UI sync |
| 25 | `cspe_open_graph3d` | Route + Graph3D session + shell sync |
| 26 | `cspe_get_current_context` | GET agent context (trimmed) |
| 27 | `cspe_update_map` | Shell enqueue map update spec |
| 28 | `cspe_lookup_place_online` | POST place-lookup (chat-only) |
| 29 | `cspe_show_station_or_line_info` | Internal search_stops wrapper |
| 30 | `cspe_nearby_stops` | GET stops/nearby |
| 31 | `cspe_nearby_pois` | GET pois/nearby |
| 32 | `cspe_explore_area` | POST area/explore |
| 33 | `cspe_filter_visible_results` | POST area/filter |
| 34 | `agent_fetch_context` | GET agent context (full) |
| 35 | `product_memory_list_projects` | GET memory/projects |
| 36 | `product_memory_create_project` | POST memory/projects |
| 37 | `product_memory_list_tasks` | GET memory/tasks |
| 38 | `product_memory_add_task` | POST memory/tasks |

**Validation:** `_validate_and_apply_defaults(tool_info, args)` in `tool_executor.py` applies registry defaults (e.g. `sync_ui: true` on exploration tools).

### 8.2 Executor

**File:** `src/work/atlas/src/atlas_client/router/tool_executor.py`

**Entry points:**
- `execute_tool(name, args, state)` — async wrapper
- `_execute_tool_impl(name, args, state)` — dispatch table

**Product Shell helpers:**
- `_product_shell_base()` → `product_shell_origin()` from `core/config.py` (reads `PRODUCT_SHELL_URL`)
- `_product_shell_enqueue(commands, tool_name)` → `POST /api/shell/enqueue`
- `_patch_shell_transport(patch)` → `PATCH /api/agent/context`
- `_remember_place_focus(query, place_kind)` → updates router context + `last_place_lookup`

**Tool receipt shape:** `{ ok, tool, summary, data, error }`

### 8.3 cspe_* tool → Product Shell mapping

| Tool | Product Shell endpoint / action |
|------|--------------------------------|
| `cspe_search_stops` | `GET /api/transport/stops/search` |
| `cspe_compute_route` | `POST /api/agent/transport/route` |
| `cspe_route` | `POST /api/shell/enqueue` (`atlas_transport_action`, `run: route`) |
| `cspe_transport_action` | `POST /api/shell/enqueue` |
| `cspe_update_map` | `POST /api/shell/enqueue` |
| `cspe_nearby_stops` | `GET /api/transport/stops/nearby?sync_ui=...` |
| `cspe_nearby_pois` | `GET /api/transport/pois/nearby?sync_ui=...` |
| `cspe_explore_area` | `POST /api/transport/area/explore` with `sync_ui` |
| `cspe_filter_visible_results` | `POST /api/transport/area/filter?sync_ui=...` |
| `cspe_lookup_place_online` | `POST /api/agent/transport/place-lookup`; may call `web_search` for POI enrichment |
| `cspe_open_graph3d` | `POST /api/agent/transport/route` or `POST /api/transport/graph3d/session` + shell enqueue |
| `cspe_get_current_context` | `GET /api/agent/context` |
| `cspe_set_mode`, `cspe_navigate`, etc. | `POST /api/shell/enqueue` with respective `kind` |
| `product_memory_*` | `/api/memory/*` + optional shell enqueue |

---

## 9. Shell Command Bridge (UI Sync)

### 9.1 Enqueue path

**Producers:**
- `tool_executor._product_shell_enqueue()` — Atlas tools
- `routers/transport.py` — when `sync_ui=true` on exploration endpoints
- `routers/agent.py` — `post_agent_transport_route` when `sync_ui=true`

**Consumer:** `ShellCommandListener.tsx` in browser

### 9.2 Exploration shell command bundle

**File:** `backend/product_shell/services/agent_tools.py`

**Function:** `shell_commands_for_exploration(exploration)`

**Returns list of commands:**
1. `{ kind: "set_mode", mode: "transport" }`
2. `{ kind: "transport_exploration_view", center, radius_m, counts, summary, nearby_stops, nearby_pois }`
3. `{ kind: "atlas_transport_action", spec: { run: "exploration_map", open_app_mode: "transport", dock_tab: "search", stop_lookup_query, selected_station_id, exploration_revision, ... } }`

### 9.3 Route shell command bundle

**Function:** `shell_commands_for_route(route_payload)`

**Returns commands including:**
- `set_mode`, `transport_options`, `transport_route_view`, `atlas_transport_action` with `run: "route"` or similar

### 9.4 Delivery mechanism

**File:** `backend/product_shell/routers/shell.py`

- In-memory deque (max 256 entries)
- SSE subscribers receive JSON `{ commands: [...] }` events
- `GET /api/shell/poll` drains and clears the deque
- Commands are appended to the deque regardless of SSE subscriber presence (inspected in current code)

---

## 10. Local Transport Graph and Data System

### 10.1 Graph bundle

**Runtime load path:** `data/derived/routing/graph_bundle.pkl`

**Files:**
- `backend/product_shell/transport_engine.py` — `get_bundle()`, `graph_for(mode, use_lcc)`, `BUNDLE_PATH`
- `src/core/cache_bundle.py` — `load_or_build_graph_bundle()`, `_build_bundle()`
- `src/core/graph_loader.py` — GTFS loading, edge building, `build_graph`, `build_graphs_by_mode`

**Graph modes:** `"all"`, `"metro"`, `"rail"`, `"tram"`, `"bus"`, `"other"`

**LCC flag:** Largest connected component filtering via `largest_component()` in graph_loader

### 10.2 Station layer

**File:** `src/core/station_layer.py`

**Class:** `StationLayerIndex`

**Functions:** `build_station_layer`, `station_path_from_stop_path`, `best_stop_path_between_stations`, `station_geojson`

**Used by:** `transport_engine.station_layer_for(mode, use_lcc)` for station-level routing and map rendering

### 10.3 Queries and routing

**File:** `src/core/queries.py`

| Function | Role |
|----------|------|
| `search_stops`, `search_stops_autocomplete` | Stop name search |
| `search_stations_autocomplete` | Station name search |
| `shortest_path` | Pathfinding on NetworkX graph |
| `summarize_path` | Path summary for display |
| `k_hop_subgraph` | Local subgraph extraction |

**File:** `src/core/path_legs.py` — `describe_path_legs`

**File:** `src/core/route_styles.py` — line colors/styles for map

### 10.4 POI index

**File:** `src/core/poi_index.py`

**Class:** `LocalPOILookup`
- Data: `data/normalized/poi/poi.parquet`
- Spatial index: `data/derived/indexes/poi_balltree.pkl`, `poi_balltree.npz`
- Method: `query(lat, lon, radius_m, categories, limit)`

**Loader:** `load_poi_lookup()` called from `transport_engine._poi_lookup()`

### 10.5 Map rendering

**File:** `src/viz/plot_mapbox.py`

**Primary entry used by backend:** `render_mapbox_gl_html(...)` (called from `transport_engine.render_transport_map_html`)

**Supporting functions:**
- `load_line_geometries`, `load_render_graph`
- `_network_feature_collection`, `_path_feature_collection`, `_stations_feature_collection`
- `_exploration_geojson`, `build_exploration_overlay_update`

**Map HTML cache:** `data/derived/product_shell/map_html_cache/` (keyed hashes in `transport_engine.py`)

**Line geometries source:** `data/derived/maps/*.network.geojson`

**Render graphs:** `data/derived/render_graphs/*.render_graph.json`

---

## 11. Transport Flows: Search, Route, Exploration, Map

### 11.1 Stop search (manual UI or agent)

**UI path:**
1. User types in TransportMode search box
2. `searchStops()` → `GET /api/transport/stops/search`
3. `transport_engine.search_stops()` → `queries.search_stops` / station variants

**Agent path:**
1. Planner selects `cspe_search_stops`
2. `tool_executor` → same endpoint
3. Returns matches in tool receipt; no automatic map sync unless followed by `cspe_transport_action` / `cspe_update_map`

### 11.2 Route computation

**Direct API:** `POST /api/transport/route` — body: from/to stop IDs, mode, routing scope

**Agent composite:** `POST /api/agent/transport/route`
- `agent_tools.compute_route_from_queries(from_query, to_query, ...)`
- Resolves names via `resolve_stop_query`
- Computes via `transport_engine.compute_route` or `compute_route_stations`
- When `sync_ui=true`: `shell_commands_for_route` → enqueue

**Frontend processing:**
- `ShellCommandListener` applies `transport_route_view`
- `TransportMode` processes `atlas_transport_action` with `run: "route"` or `"compute"`
- Route overlay via `postTransportRouteOverlay` → `build_transport_route_overlay`

### 11.3 Area exploration (stops + POIs)

**Module:** `backend/product_shell/transport_exploration.py`

| Function | Role |
|----------|------|
| `resolve_exploration_center(query, agent_context, ...)` | Resolves center from query or agent context (`selected_station`, deictic "this station") |
| `nearby_stops(...)` | Stops within radius |
| `nearby_pois(...)` | POIs within radius via `LocalPOILookup` |
| `explore_area(...)` | Combined stops + POIs |
| `filter_visible_results(...)` | Filters last snapshot in agent context |
| `_store_exploration_snapshot(payload)` | Writes `transport.last_exploration` in agent_store |

**API endpoints:**
- `GET /api/transport/stops/nearby`
- `GET /api/transport/pois/nearby`
- `POST /api/transport/area/explore`
- `POST /api/transport/area/filter`

**Agent tools:** `cspe_nearby_stops`, `cspe_nearby_pois`, `cspe_explore_area`, `cspe_filter_visible_results`

**UI sync when `sync_ui=true`:**
1. Backend enqueues shell commands
2. `transport_exploration_view` updates Zustand + rail panel
3. `exploration_map` action triggers `scheduleExplorationOverlay` in TransportMode (when `showMapbox`)

### 11.4 Map HTML generation

**Endpoint:** `POST /api/transport/map`

**Handler:** `post_transport_map()` → `transport_engine.render_transport_map_html(...)`

**Request fields (from `TransportMapRequest`):** mode, use_lcc, viz_mode, graph_viz_mode, path IDs, selected stop/station, poi_radius, exploration overlay fields

**Response:** HTML string (cached on disk by fingerprint)

### 11.5 Incremental map overlays

**Exploration overlay:** `POST /api/transport/map/exploration-overlay` → `build_exploration_overlay_update` in plot_mapbox (patches GeoJSON without full HTML regen)

**Route overlay:** `POST /api/transport/map/route-overlay` → `build_transport_route_overlay`

---

## 12. Place Lookup and IDFM Integration

### 12.1 Place lookup endpoint

**Endpoint:** `POST /api/agent/transport/place-lookup`

**Handler:** `post_agent_place_lookup()` in `routers/agent.py`

**Implementation:** `agent_tools.lookup_place_for_chat(...)` in `services/agent_tools.py`

**Documented behavior in handler docstring:** "Chat-only; no map sync."

**On success:** patches `world.transport.last_place_lookup` in agent_store

### 12.2 Lookup flow inside `lookup_place_for_chat`

**File:** `backend/product_shell/services/agent_tools.py`

**Inputs:** `query`, `kind` (`auto|station|poi`), `near_query`, `topic`, `includes_today`, `mode`, `use_lcc`, `station_first`

**Paths (from function structure):**
- Station resolution via local graph + `_station_lookup_payload`
- POI resolution via `transport_exploration.resolve_poi_by_name` and `_poi_lookup_result`
- IDFM enrichment when station resolved and topic warrants it
- Web search query construction for POI topics (hours, reviews) when IDFM not used

### 12.3 IDFM services

| File | Role |
|------|------|
| `services/idfm_client.py` | `IdfmNavitiaClient` — PRIM Navitia v2 API; `api_key()` reads `IDFM_API_KEY` |
| `services/idfm_referential.py` | `IdfmReferentialStore` — cached CSVs in `data/derived/idfm/` |
| `services/idfm_station_enrichment.py` | `enrich_local_station(local, topic, includes_today)` |
| `services/idfm_service_hours.py` | `fetch_station_service_hours`, `summarize_service_hours` for `topic=hours` |

**Navitia base URL (in code):** `https://prim.iledefrance-mobilites.fr/marketplace/v2/navitia`

### 12.4 Agent tool wrapper

**Tool:** `cspe_lookup_place_online` in `tool_executor.py`

**Calls:** `POST /api/agent/transport/place-lookup`

**Post-processing:** Builds injection text from `local_summary`, optional `idfm_summary`, optional SerpAPI web results for POI topics

**Atlas tool registry description:** "Does not update the map."

---

## 13. Memory, Music, and Visual Modes

### 13.1 Product memory (SQLite)

**Store:** `backend/product_shell/services/product_memory_store.py`

**Database file:** `data/product_memory.sqlite`

**API:** `routers/memory.py` — projects and tasks CRUD

**Atlas tools:** `memory_*` (Atlas-internal memory) and `product_memory_*` (product shell SQLite)

### 13.2 Spotify

**Router:** `backend/product_shell/routers/spotify.py`

**Token file default:** `data/spotify_tokens.json` (overridable via `SPOTIFY_TOKEN_PATH`)

**Frontend callback:** `frontend/src/pages/SpotifyCallbackPage.tsx` at route `/callback`

**Atlas tool:** `music` in tool_executor (Spotify play/search via product shell or direct client — inspect `tool_executor.py` music branch for exact calls)

### 13.3 Visual board

**Atlas tool:** `visual_board`, `image_search`, `image_proxy`

**UI mode:** `VisualBoardMode.tsx`

**Chat structured output:** `normalize_atlas_ui` produces `visual_board` and `image_results` blocks

---

## 14. GraphXR 3D Viewer

**Directory:** `viewers/graphxr/`

**Dev server:** port 3000, path `/viewer`

**Integration:**
1. `transport_engine.create_graph3d_session()` writes session payload
2. Frontend `graph3dSync.ts` — `buildGraph3dViewerUrl(sessionId, apiBase, syncClientId)`
3. iframe URL pattern: `{VITE_GRAPHXR_VIEWER_URL}?session=...&api=...&sync=...&embedded=1`
4. Live sync: `POST/GET /api/transport/graph3d/sync`

**Viewer files inspected:** `app/viewer/ViewerClient.tsx`, `app/viewer/page.tsx`

---

## 15. External APIs and Integrations

| Integration | Env var(s) | Used in |
|-------------|------------|---------|
| OpenAI Realtime | `OPENAI_API_KEY`, `ATLAS_REALTIME_MODEL` | `orchestrator.py` |
| OpenAI Chat (planner/router) | `OPENAI_API_KEY`, `ATLAS_PLANNER_MODEL`, `ATLAS_ROUTER_MODEL` | `agent_planner.py`, `semantic_router.py`, `planner_pipeline.py` |
| SerpAPI | `SERPAPI_API_KEY` | `src/work/atlas/src/atlas_client/clients/serpapi_client.py` (web_search, image_search) |
| Mapbox | `MAPBOX_TOKEN` / `MAPBOX_API_KEY` / `MAPBOX_ACCESS_TOKEN`, `MAPBOX_STYLE_URL` | `transport_engine.get_mapbox_token()` |
| IDFM PRIM Navitia | `IDFM_API_KEY` | `idfm_client.py` |
| Spotify Web API | `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `SPOTIFY_REDIRECT_URI` | `routers/spotify.py` |
| Ollama (optional) | `ATLAS_LOCAL_PLANNER_URL`, model env vars | `local_planner.py` |
| Azure TTS | (Azure credentials in atlas client — exact env names in `azure_tts_player` module; not fully inspected in this pass) | `orchestrator.py` speak paths |

---

## 16. Environment Variables and Configuration

### 16.1 Loaded at startup

**Repo `.env`:** loaded by `backend/product_shell/main.py` `_load_local_env()` from repository root (`CSPE/.env`)

**Separate Atlas `.env`:** `src/work/atlas/.env` (Atlas-local; separate from product shell load path)

### 16.2 Product Shell / transport

| Variable | Read in | Default / notes |
|----------|---------|-----------------|
| `MAPBOX_TOKEN`, `MAPBOX_API_KEY`, `MAPBOX_ACCESS_TOKEN` | `transport_engine.get_mapbox_token()` | Required for map HTML |
| `MAPBOX_STYLE_URL` | `transport_engine.default_basemap_style()` | Optional basemap |
| `IDFM_API_KEY` | `idfm_client.api_key()` | IDFM PRIM API |
| `ATLAS_API_BASE` | `atlas_http.atlas_base_url()` | `http://127.0.0.1:5055` |
| `PRODUCT_SHELL_WARMUP` | `warmup.start_background_warmup()` | Default on; set `0` to disable |
| `PRODUCT_SHELL_CORS_ORIGINS` | `main.py` | Comma-separated origins |
| `PRODUCT_SHELL_CORS_ORIGIN_REGEX` | `main.py` | LAN origin regex |
| `SPOTIFY_*` | `routers/spotify.py` | OAuth credentials |

### 16.3 Frontend (Vite)

| Variable | Read in | Purpose |
|----------|---------|---------|
| `VITE_API_BASE` | `api/config.ts` | Direct backend URL (bypass proxy) |
| `VITE_DEV_PROXY_TARGET` | `api/config.ts`, `vite.config.ts` | Proxy target for `/api` |
| `VITE_GRAPHXR_VIEWER_URL` | `api/config.ts` | GraphXR iframe base |
| `VITE_SHELL_SSE` | `ShellCommandListener.tsx` | Set `0` to use poll instead of SSE |

### 16.4 Atlas / planner

| Variable | Read in | Purpose |
|----------|---------|---------|
| `OPENAI_API_KEY` | OpenAI clients | Required for planner/Realtime |
| `ATLAS_AGENT_PLANNER` | `orchestrator.py` | `0` disables multi-step planner |
| `ATLAS_PLANNER_BACKEND` | `planner_config.py` | `openai`, `local`, or `auto` |
| `ATLAS_PLANNER_MAX_STEPS` | `agent_planner.py` | Max tool steps per turn |
| `ATLAS_PLANNER_MODEL` | `agent_planner.py` | OpenAI planner model |
| `ATLAS_ROUTER_MODEL` | `semantic_router.py` | Legacy router model |
| `ATLAS_REALTIME_MODEL` | `orchestrator.py` | Realtime WebSocket model |
| `PRODUCT_SHELL_URL` | `core/config.py` | Product shell base for tools |
| `CSPE_FRONTEND_URL` | `tool_executor.py` | `cspe_open_transport_map` |
| `ATLAS_LOCAL_PLANNER_URL` | `local_planner.py` | Ollama URL |
| `SERPAPI_API_KEY` | SerpAPI client | Web/image search |

### 16.5 Logging

| Variable | Read in | Purpose |
|----------|---------|---------|
| `CSPE_LOG_DIR` | `project_logs.py` | Log directory |
| `CSPE_HEALTH_LOG` | `project_logs.py` | Health log path |
| `CSPE_ACTIVITY_LOG` | `project_logs.py` | Verbose activity log |
| `CSPE_COMPACT_LOG` | `project_logs.py` | Compact activity log |
| `CSPE_LOG_MODE` | `project_logs.py` | `"compact"` or full |
| `CSPE_LOG_RESET` | `project_logs.py` | Log truncation on startup |

---

## 17. Data Files, Caches, and Generated Artifacts

### 17.1 Directory layout

```
data/
├── cache/                          # e.g. graph_bundle.pkl copies, idf_pois.geojson
├── derived/
│   ├── geo/                        # Admin boundary GeoJSON
│   ├── idfm/                       # arrets.csv, accessibilite_en_gare.csv (downloaded)
│   ├── indexes/                    # poi_balltree.pkl, poi_balltree.npz, poi_lookup_meta.json
│   ├── maps/                       # *.network.geojson + .meta.json
│   ├── product_shell/map_html_cache/  # Cached map HTML JSON
│   ├── render_graphs/              # *.render_graph.json per mode
│   ├── routing/                    # graph_bundle.pkl, graph_bundle_meta.json
│   └── stops/                      # stop_popup_index.parquet
├── gtfs/                           # Raw GTFS text feeds, build scripts
├── normalized/
│   ├── geo/                        # line_geometries.parquet
│   ├── gtfs/                       # Normalized routes/stops parquet
│   └── poi/                        # poi.parquet
├── raw/                            # Source copies
├── product_memory.sqlite           # Memory mode database
└── spotify_tokens.json             # Spotify OAuth tokens
```

### 17.2 Runtime-critical paths (referenced in transport_engine)

| Path | Purpose |
|------|---------|
| `data/derived/routing/graph_bundle.pkl` | NetworkX graphs + metadata |
| `data/derived/stops/stop_popup_index.parquet` | Stop popup index |
| `data/normalized/poi/poi.parquet` | POI records |
| `data/derived/indexes/poi_balltree.*` | POI spatial index |
| `data/derived/maps/*.network.geojson` | Line geometries for map |
| `data/derived/render_graphs/*.render_graph.json` | Precomputed render graphs |
| `data/derived/product_shell/map_html_cache/` | Disk cache for map HTML |

### 17.3 Agent context snapshots

**In-memory (not persisted to disk):** `agent_store._world_state`, including `transport.last_exploration` written by `transport_exploration._store_exploration_snapshot()`

---

## 18. Logging and Debugging

### 18.1 Log module

**File:** `src/core/project_logs.py`

**Log files (defaults under `logs/`):**
- `health.log` — startup, health checks
- `activity.log` — verbose events
- `activity_compact.log` — one-line summaries

**Categories:** `CAT_STARTUP`, `CAT_PLANNER`, `CAT_TOOL`, `CAT_TRANSPORT`, `CAT_UI`, `CAT_MAP`, `CAT_HTTP`, `CAT_ERRORS`

**Key functions:** `log_http_line`, `log_startup`, `log_compact`, `log_compact_line`, `log_event`, `begin_turn`, `log_turn_planner`, `log_turn_tool`

### 18.2 Transport UI logger

**File:** `backend/product_shell/ui_transport_logger.py`

**Logger name:** `"ui.transport"`

| Function | Trigger |
|----------|---------|
| `log_ui_search_stops` | Stop search API |
| `log_ui_route` | Route compute |
| `log_exploration_api_result` | Exploration endpoints with sync_ui |
| `log_exploration_shell_enqueue` | `transport_exploration_view` command enqueued |
| `log_atlas_transport_client_event` | Browser POST `/api/shell/client-log` |

### 18.3 Browser client logging

**Frontend:** `postShellClientLog(event, data)` → `POST /api/shell/client-log`

**Events emitted from TransportMode / ShellCommandListener (examples from code):**
- `exploration_view_applied`
- `exploration_map_trigger`
- `atlas_transport_trigger`
- `exploration_map_refresh`

### 18.4 Atlas turn logging

**File:** `src/work/atlas/src/atlas_client/core/logctx.py`

Functions like `log_with_turn`, `begin_user_turn` — used throughout orchestrator and planner

### 18.5 Inspecting logs during dev

**From `run_web_app.ps1` help text:**
```
Get-Content logs\activity_compact.log -Wait
Get-Content logs\activity.log -Wait
Get-Content logs\health.log
```

---

## 19. Typical User Question Execution Paths

### 19.1 "Route me from A to B"

```
User types in AtlasRailPanel
  → useAtlasTextChat.send()
  → POST /api/chat (chat.py)
  → atlas_http.send_text_and_wait()
  → POST /text (Atlas api.py)
  → orchestrator.route_and_handle()
  → run_planner_turn() [if ATLAS_AGENT_PLANNER=1]
  → resolve_planner_plan()
     → shortcut or OpenAI selects cspe_compute_route
  → validate_and_enrich_plan()
  → execute_tool("cspe_compute_route")
     → POST /api/agent/transport/route { sync_ui: true }
     → agent_tools.compute_route_from_queries()
     → shell_commands_for_route() → enqueue_commands()
  → injection_block → OpenAI Realtime → assistant text
  → normalize_atlas_ui() → ChatResponse
  → ShellCommandListener applies transport_route_view + atlas_transport_action
  → TransportMode runs route overlay on map
```

### 19.2 "Show POIs near République"

```
Same chat entry path through orchestrator + planner
  → detect_exploration_intent() or OpenAI selects cspe_nearby_pois
  → apply_exploration_routing() ensures sync_ui: true
  → execute_tool("cspe_nearby_pois")
     → GET /api/transport/pois/nearby?q=République&sync_ui=true
     → transport_exploration.nearby_pois()
     → shell_commands_for_exploration() → enqueue_commands()
  → ShellCommandListener:
     transport_exploration_view → setTransportExploration()
     atlas_transport_action run=exploration_map
  → TransportMode.scheduleExplorationOverlay() [when showMapbox]
  → TransportExplorationPanel shows POI list in rail
```

### 19.3 "What are the working hours of République?"

```
Planner path:
  → detect_place_info_intent() → topic=hours, kind=station
  → apply_place_info_routing() → cspe_lookup_place_online
  → execute_tool("cspe_lookup_place_online")
     → POST /api/agent/transport/place-lookup
     → lookup_place_for_chat() → enrich_local_station() via idfm_service_hours
     → patches last_place_lookup in agent_store
  → tool_executor builds LOCAL MAP DATA + idfm_summary injection
  → Realtime model speaks answer
  → No shell exploration commands (chat-only path)
```

### 19.4 "What are the working hours?" (follow-up)

```
detect_place_info_intent() with agent_context
  → resolve_conversation_focus() reads last_place_lookup
  → PlaceInfoIntent inherits query from focus
  → cspe_lookup_place_online with inherited station query
```

### 19.5 "Remind me to …"

```
orchestrator memory guardrails OR planner
  → memory_add tool (Atlas internal memory, not product_memory_add_task)
  → execute_tool("memory_add")
  → receipt returned → injection → Realtime response
```

### 19.6 Manual stop search in Transport UI (no agent)

```
User types in TransportMode search dock
  → searchStops() directly
  → GET /api/transport/stops/search
  → transport_engine.search_stops()
  → results in UI suggestions; map selection via setMapSelection + scheduleMapRefresh
```

### 19.7 Voice wake

```
wake_service/main.py Vosk detects "atlas wake up"
  → POST /wake (Atlas)
  → run_session() → session_main() Realtime loop
  → voice input via mic (mode=voice) OR text via /text when mode=text
```

---

## Appendix A: Key File Index

| Area | Files |
|------|-------|
| Startup | `run_web_app.ps1`, `run_product_shell.ps1`, `stop_product_shell.ps1` |
| Product Shell | `backend/product_shell/main.py`, `routers/*.py`, `schemas.py`, `transport_engine.py`, `transport_exploration.py` |
| Agent services | `services/agent_store.py`, `agent_tools.py`, `atlas_http.py`, `warmup.py`, `idfm_*.py` |
| Frontend | `frontend/src/store.ts`, `AppShell.tsx`, `ShellCommandListener.tsx`, `TransportMode.tsx`, `api/client.ts` |
| Atlas core | `core/orchestrator.py`, `core/agent_planner.py`, `core/session_state.py`, `core/semantic_router.py` |
| Atlas router | `router/tool_executor.py`, `router/planner_pipeline.py`, `router/local_planner.py`, `router/planner_*.py`, `tools_registry.json` |
| Graph/POI | `src/core/graph_loader.py`, `queries.py`, `poi_index.py`, `station_layer.py`, `cache_bundle.py` |
| Map viz | `src/viz/plot_mapbox.py` |
| Logging | `src/core/project_logs.py`, `backend/product_shell/ui_transport_logger.py` |
| Tests | `tests/test_transport_exploration.py`, `tests/test_planner_place_info.py`, `tests/test_planner_exploration.py`, `tests/test_conversation_focus.py`, `tests/test_idfm_*.py` |

---

## Appendix B: Unclear / Not Fully Inspected

The following were referenced but not read line-by-line in this documentation pass:

- **`azure_tts_player` module** — exact Azure Speech env var names and credential loading
- **`music` tool branch in `tool_executor.py`** — full Spotify call chain inside Atlas vs product shell
- **`visual_board` / `image_proxy` implementation details** — SerpAPI panel assembly
- **Atlas internal memory store** — file paths for `memory_add` / `memory_search` persistence (separate from `product_memory.sqlite`)
- **`frontend/vite.config.ts` proxy rules** — exact rewrite targets (inferred from `VITE_DEV_PROXY_TARGET` usage)
- **Full contents of repo-root `.env`** — not committed; only env var names from code grep are documented

For these areas, inspect the files named in the Atlas `tool_executor.py` dispatch table and `src/work/atlas/src/atlas_client/clients/` directory.

---

*Document generated from codebase inspection. Repository path: `c:\Users\LEGION\Desktop\CSPE`*
