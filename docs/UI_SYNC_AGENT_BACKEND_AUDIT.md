# UI Sync Agent → Backend Audit

**Problem statement:** Atlas accepts a user command, the backend computes the result (route, exploration, mode change, etc.), and the user receives a **textual answer**, but the **2D map / transport UI often does not update** (no path, no highlight, no mode switch). Fixes have been applied repeatedly; regressions reappear after later changes.

**Scope of this document:** Full technical chain from user input to rendered map. No code changes — root-cause analysis and durable fix design only.

**Evidence from live session (2026-06-20):**

```
[Tool] cspe_compute_route ok=true ... summary="Route: 2 min, 0 transfers from Châtelet to République"
[Chat] product_chat_return ... shell_enqueued_delta=3 shell_pending=3
[Chat] product_chat_return ... shell_enqueued_delta=3 shell_pending=6
GET /api/shell/stats → {"pending":6,"total_enqueued":6}
```

Backend and Atlas succeeded; **six shell commands were never consumed by the browser**.

---

## Table of contents

1. [Global overview of the current architecture](#1-global-overview-of-the-current-architecture)
2. [Exact files involved](#2-exact-files-involved)
3. [Current data flow for a route command](#3-current-data-flow-for-a-route-command)
4. [Current data flow for other UI actions](#4-current-data-flow-for-other-ui-actions)
5. [Backend success vs UI success](#5-backend-success-vs-ui-success)
6. [Previous fixes and temporary patches](#6-previous-fixes-and-temporary-patches)
7. [API contracts and schemas](#7-api-contracts-and-schemas)
8. [UI synchronization mechanism](#8-ui-synchronization-mechanism)
9. [Map rendering mechanism](#9-map-rendering-mechanism)
10. [Race conditions and lifecycle problems](#10-race-conditions-and-lifecycle-problems)
11. [Logs and observability](#11-logs-and-observability)
12. [Root-cause hypotheses](#12-root-cause-hypotheses)
13. [Recommended stable architecture](#13-recommended-stable-architecture)
14. [Concrete fix plan](#14-concrete-fix-plan)
15. [Tests to prevent regression](#15-tests-to-prevent-regression)
16. [Final diagnostic summary](#16-final-diagnostic-summary)

---

## 1. Global overview of the current architecture

### 1.1 Processes and ports (default dev stack)

| Process | Role | Port / URL | Started by |
|---------|------|------------|------------|
| **Vite (React frontend)** | UI, map iframe, shell consumer | `http://127.0.0.1:5173` | `run_web_app.ps1` → `npm run dev` |
| **Product Shell (FastAPI)** | Transport API, chat proxy, **shell command queue** | `http://127.0.0.1:8787` | `run_web_app.ps1` |
| **Atlas (Flask API)** | Planner, intent router, tool executor, voice | `http://127.0.0.1:5055` | `run_web_app.ps1` |
| **GraphXR (Next.js)** | 3D / WebXR viewer | `http://127.0.0.1:3000/viewer` | `run_web_app.ps1` |
| **VR proxy** (Quest mode only) | HTTPS reverse proxy | `http://127.0.0.1:8080` | `run_web_app.ps1 -QuestVR` |
| **ngrok** (Quest mode only) | Public HTTPS tunnel | `https://*.ngrok-free.dev` | `run_web_app.ps1 -QuestVR` |

All must be running for full agent + map + 3D. Chat requires Atlas + Product Shell. **Map sync additionally requires the browser tab with `ShellCommandListener` actively polling or subscribed to SSE.**

### 1.2 End-to-end flow (intended)

```
┌─────────────┐     POST /api/chat      ┌──────────────┐     POST /text      ┌─────────────┐
│   Browser   │ ──────────────────────► │ Product Shell│ ──────────────────► │    Atlas    │
│  (React)    │                         │   :8787      │                     │   :5055     │
└──────┬──────┘                         └──────┬───────┘                     └──────┬──────┘
       │                                       │                                    │
       │  (A) Chat response: text only         │                                    │ run_planner_turn()
       │◄──────────────────────────────────────┤                                    │
       │                                       │                                    ▼
       │                                       │                          Intent → tool selection
       │                                       │                                    │
       │                                       │◄──── POST /api/agent/transport/* ──┤ cspe_compute_route
       │                                       │      (sync_ui=true)                │ cspe_explore_area
       │                                       ▼                                    │ cspe_transport_action
       │                              enqueue_commands() ◄──────────────────────────┘
       │                                       │
       │  (B) Separate channel:                │  In-memory deque (max 256)
       │  GET /api/shell/poll                  │  OR SSE /api/shell/stream
       │  OR EventSource /api/shell/stream     │
       ▼                                       ▼
 ShellCommandListener                    shell.py _queue
       │
       ▼
 Zustand store (pathIds, exploration, actions queue)
       │
       ▼
 TransportMode → POST /api/transport/map → Mapbox iframe (blob URL)
       │
       ▼
 Optional: postMessage overlay (exploration/route) to iframe
```

**Critical architectural fact:** paths **A** (chat HTTP response) and **B** (shell queue) are **decoupled**. A successful chat turn does **not** guarantee UI update. The assistant text and the map sync use different channels.

### 1.3 Layer responsibilities

| Layer | Responsibility |
|-------|----------------|
| **User input** | Text (`useAtlasTextChat` → `POST /api/chat`) or voice (`POST /api/atlas/input-mode` + poll `/api/atlas/ui`) |
| **Atlas planner** | `run_planner_turn()` in `agent_planner.py` — resolves plan, validates tools, executes steps |
| **Intent detection** | `try_ui_settings_intent`, `try_deterministic_intent`, `route_intent()` → domain routers |
| **Tool execution** | `tool_executor._execute_tool_impl()` — HTTP to Product Shell on `127.0.0.1:8787` |
| **Backend execution** | `agent_tools.compute_route_from_queries()`, `transport_exploration.explore_area()`, etc. |
| **UI command emission** | `agent_tools.shell_commands_for_route()` → `shell_router.enqueue_commands()` |
| **Chat response** | `atlas_http.send_text_and_wait()` polls Atlas `/ui` → `normalize_atlas_ui()` → `ChatResponse.structured_outputs` (text) |
| **UI application** | `ShellCommandListener` drains queue → Zustand → `TransportMode` effects → map HTTP |
| **Map rendering** | Server-side Mapbox HTML in `transport_engine.py` / `plot_mapbox.py`, loaded in iframe |
| **3D / GraphXR** | `transport_graph3d_sync` shell command + `graph3dSync.ts` → `/api/transport/graph3d/sync` |

There is **no WebSocket** from Atlas to the browser for UI commands. There is **no structured UI payload in `POST /api/chat` response**.

---

## 2. Exact files involved

### 2.1 Frontend

| File | Role | Key symbols | Receives | Emits / returns |
|------|------|-------------|----------|-----------------|
| `frontend/src/hooks/useAtlasTextChat.ts` | Chat send path | `send()`, `postChat()` | User text | Updates `chatHistory` via `applyChatResponse` — **text only** |
| `frontend/src/api/client.ts` | HTTP client | `postChat`, `postRoute`, `postTransportMap`, `postTransportRouteOverlay`, `postTransportExplorationOverlay` | API JSON | Typed responses; **`postTransportRouteOverlay` unused in UI** |
| `frontend/src/api/config.ts` | API base URL | `apiUrl()`, `getApiBase()` | `VITE_API_BASE` env | Absolute or proxied `/api` URLs — **cross-origin misconfig breaks shell poll** |
| `frontend/src/components/ShellCommandListener.tsx` | **Shell queue consumer** | `applyOne()`, `drainCommands()`, `ShellCommandListener` | `/api/shell/poll`, SSE `commands` events | Zustand mutations, `enqueueAtlasTransportAction`, `postAgentEvent("shell.commands_applied")` |
| `frontend/src/components/AppShell.tsx` | Root layout | mounts `ShellCommandListener`, `AgentContextSync`, `TransportMode` | — | — |
| `frontend/src/components/AgentContextSync.tsx` | Planner context mirror | `patchAgentContext()` | Zustand transport fields | `PATCH /api/agent/context` — **not map driver** |
| `frontend/src/components/AtlasRailPanel.tsx` | Chat UI + voice hold | `useAtlasTextChat`, `fetchAtlasUi` | Chat, voice poll | User-visible messages |
| `frontend/src/store.ts` | Global state | `transportPathIds`, `transportStationPathIds`, `transportExploration`, `atlasTransportActions`, setters | Shell listener, TransportMode | React re-renders |
| `frontend/src/transport/atlasTransportTypes.ts` | Shell action types | `AtlasTransportActionSpec`, `normalizeAtlasTransportSpec`, `transportActionSpecFingerprint` | Shell JSON | Normalized spec for action queue |
| `frontend/src/transport/transportViewState.ts` | Map request builders | `readTransportViewContext`, `buildTransportMapBody`, `buildTransportBaseMapBody` | Zustand snapshot | POST body for `/api/transport/map` |
| `frontend/src/transport/mapExplorationBridge.ts` | iframe postMessage | `postExplorationToMapIframe`, `postRouteToMapIframe`, `subscribeMapIframeMessages` | Map iframe | `cspe-map-set-exploration`, `cspe-map-set-route` — **route postMessage unused** |
| `frontend/src/transport/mapRefreshScheduler.ts` | Debounced refresh | `createMapRefreshScheduler` | schedule calls | Coalesced `executeBaseMapRefresh` |
| `frontend/src/transport/graph3dSync.ts` | GraphXR live sync | `pushGraph3dViewSync`, `registerGraph3dSyncClientId` | Zustand + shell cmd | POST `/api/transport/graph3d/sync` |
| `frontend/src/modes/TransportMode.tsx` | **Map + action executor** | `executeBaseMapRefresh`, `applyAtlasTransportPatches`, atlas action `useEffect` (~L686) | Zustand, shell-applied state | Map iframe URL, route panel, exploration delivery |
| `frontend/src/transport/atlasTransportDedupe.ts` | Action dedupe | `wasTransportActionProcessed`, `markTransportActionProcessed` | action seq | Prevents double-processing |

### 2.2 Backend (Product Shell)

| File | Role | Key symbols |
|------|------|-------------|
| `backend/product_shell/routers/chat.py` | Chat endpoint | `post_chat()` — logs `shell_enqueued_delta`, `shell_pending` |
| `backend/product_shell/routers/shell.py` | **Command queue** | `enqueue_commands()`, `shell_poll()`, `shell_stream()` |
| `backend/product_shell/routers/agent.py` | Agent composite APIs | `post_agent_transport_route()`, `patch_agent_context()` |
| `backend/product_shell/routers/transport.py` | Map, route, explore | `post_transport_map`, `post_transport_route_overlay`, explore endpoints with `sync_ui` |
| `backend/product_shell/routers/atlas.py` | Atlas proxy | input mode, `/ui` poll |
| `backend/product_shell/services/atlas_http.py` | Atlas HTTP client | `send_text_and_wait()`, `ensure_atlas_session_text_mode()` |
| `backend/product_shell/services/agent_tools.py` | Route resolve + **shell builders** | `compute_route_from_queries()`, `shell_commands_for_route()`, `shell_commands_for_exploration()` |
| `backend/product_shell/services/agent_store.py` | In-memory planner context | `patch_world_state()`, `record_event()` |
| `backend/product_shell/services/normalize.py` | Atlas UI → chat outputs | `normalize_atlas_ui()` — text structured outputs |
| `backend/product_shell/transport_engine.py` | Graph + map HTML | `compute_route`, `compute_route_stations`, `render_mapbox_gl_html`, `build_transport_route_overlay` |
| `backend/product_shell/transport_exploration.py` | POI / nearby / explore | `explore_area()`, `nearby_stops()`, `nearby_pois()` |
| `backend/product_shell/schemas.py` | Pydantic models | `TransportRouteResponse`, `TransportMapRequest`, `AgentTransportRouteRequest`, etc. |
| `backend/product_shell/ui_transport_logger.py` | UI pipeline logs | `log_atlas_transport_client_event`, `log_exploration_shell_enqueue` — **suppressed in compact mode** |

### 2.3 Atlas agent / planner

| File | Role | Key symbols |
|------|------|-------------|
| `src/work/atlas/src/atlas_client/core/agent_planner.py` | Turn orchestration | `run_planner_turn()`, `_log_plan_step()` |
| `src/work/atlas/src/atlas_client/router/central_intent_router.py` | Intent routing | `route_intent()` |
| `src/work/atlas/src/atlas_client/router/domain_routers.py` | Domain plans | `route_transport()`, `route_poi()`, `route_map_ui()`, `route_visual_3d()` |
| `src/work/atlas/src/atlas_client/router/intent_fallback.py` | Regex shortcuts | `try_deterministic_intent()` |
| `src/work/atlas/src/atlas_client/router/intent_ui_control.py` | UI settings intents | `try_ui_settings_intent()`, `parse_transport_ui_patches()` |
| `src/work/atlas/src/atlas_client/router/tool_executor.py` | Tool HTTP | `_execute_tool_impl()` — `cspe_compute_route` → `POST /api/agent/transport/route` |
| `src/work/atlas/src/atlas_client/router/tool_plan_adapter.py` | Plan conversion | `routing_decision_to_planner_plan()` |
| `src/work/atlas/src/atlas_client/core/orchestrator.py` | Realtime session | OpenAI Realtime, final text response |
| `src/work/atlas/src/atlas_client/core/orchestrator_event_handlers.py` | Response logging | `_format_final_response_log()` — `[PlannerLive] final_openai_response=` |

### 2.4 Map / graph rendering (Python)

| File | Role |
|------|------|
| `src/viz/plot_mapbox.py` | Mapbox GL HTML generation, route layers, exploration layers, postMessage handlers for iframe |
| `src/core/graph_loader.py` | GTFS graph loading |
| `src/core/path_legs.py` | Route leg breakdown for UI |

### 2.5 GraphXR viewer

| File | Role |
|------|------|
| `viewers/graphxr/app/viewer/ViewerClient.tsx` | Embedded viewer, sync from Product Shell |
| `viewers/graphxr/app/components/3DandXRComponents/utils/GraphRenderer.ts` | Graph rendering |

### 2.6 Tests (reference behavior)

| File | Role |
|------|------|
| `tests/test_intent_routing.py` | Intent → tool mapping |
| `tests/test_transport_exploration.py` | Exploration API |
| `scripts/planner_live_test_lib.py` | Live planner log parsing |

---

## 3. Current data flow for a route command

**Example user message:** « Montre-moi un itinéraire de République à Orly »

### Step 1 — Frontend chat submit

```
useAtlasTextChat.send()
  → postChat(message)  // POST /api/chat
  → appendUserMessage (optimistic)
```

**No map interaction at this step.**

### Step 2 — Product Shell chat handler

```python
# backend/product_shell/routers/chat.py
shell_before = shell_router.shell_stats()
ui, err = send_text_and_wait(body.message)  # atlas_http.py
shell_after = shell_router.shell_stats()
# logs: shell_enqueued_delta, shell_pending
return ChatResponse(structured_outputs=normalize_atlas_ui(ui))
```

`send_text_and_wait()`:

1. `POST http://127.0.0.1:5055/text` with user message
2. Poll `GET http://127.0.0.1:5055/ui` until assistant text stabilizes (up to 120s)

### Step 3 — Atlas planner / intent

Expected path with `ATLAS_INTENT_ROUTER=1`:

```
run_planner_turn(user_text=...)
  → intent_router_enabled() == True
  → try_ui_settings_intent / try_deterministic_intent / StructuredIntent
  → route_intent(intent) → route_transport(intent)
  → ExecutionStep(tool="cspe_compute_route", args={
       from_query: "République",
       to_query: "Orly" (or "aéroport d'orly"),
       mode: "metro",
       routing_scope: "station",
       sync_ui: true
     })
```

Logged as:

```
[PlannerLive] step=1 ... tool='cspe_compute_route' ... validation_ok=True
```

### Step 4 — Tool execution (Atlas → Product Shell)

```python
# tool_executor.py — cspe_compute_route
POST http://127.0.0.1:8787/api/agent/transport/route
Body: AgentTransportRouteRequest JSON
```

Note: Atlas always posts to **`127.0.0.1:8787`** via `product_shell_origin()`, not to ngrok, regardless of frontend `VITE_API_BASE`.

### Step 5 — Backend route computation

```python
# agent.py post_agent_transport_route
result = agent_tools.compute_route_from_queries(from_query, to_query, ...)
if body.sync_ui:
    cmds = agent_tools.shell_commands_for_route(result)
    shell_queued = shell_router.enqueue_commands(cmds)
```

`compute_route_from_queries()` (`agent_tools.py`):

1. `resolve_stop_query(from_query)` → `{ status: "exact", match: { station_id, ... } }`
2. Same for `to_query`
3. `te.compute_route_stations(from_station_id, to_station_id, mode, use_lcc)`
4. Returns:

```python
{
  "ok": True,
  "from": {...}, "to": {...},
  "routing_scope": "station",
  "mode": "metro", "use_lcc": True,
  "from_query": "République", "to_query": "Orly",
  "route": {
    "ok": True,
    "path": ["IDFM:...", ...],           # stop IDs
    "station_path": ["STATION:...", ...],
    "path_legs": [{ "kind", "summary", "color", ... }],
    "path_summary": ["Métro 8", ...],
    "result": { "time_s": 1800, "transfers": 1, ... }
  }
}
```

### Step 6 — Shell commands enqueued (3 commands)

```python
# shell_commands_for_route() — order matters
[
  { "kind": "set_mode", "mode": "transport" },
  { "kind": "atlas_transport_action", "spec": {
      "open_app_mode": "transport",
      "dock_tab": "route",
      "run": "none",                    # ← does NOT recompute on client
      "from_query": "République",
      "to_query": "Orly",
      "graph_mode": "metro",
      "use_lcc": true,
      "routing_scope": "station"
  }},
  { "kind": "transport_route_view",     # ← actual path data
    "path_ids": [...],
    "station_path_ids": [...],
    "route_legs": [...],
    "route_meta": "30 min · 1 transfers"
  }
]
```

**Design intent:** server computes route once; frontend receives IDs via `transport_route_view`, not via `run: "route"`.

### Step 7 — Atlas natural-language reply

Tool result injected into Realtime prompt → assistant speaks/writes summary.

Logged:

```
[PlannerLive] final_openai_response=done correlation_id=...
[Chat] atlas_turn_ready ... assistant_len=89
```

**User sees text in Atlas rail. Map not updated yet.**

### Step 8 — Chat HTTP response to browser

```json
{
  "structured_outputs": [
    { "type": "text", "role": "assistant", "content": "Trajet confirmé : 30 minutes..." }
  ],
  "error": null
}
```

**No `path_ids`, no shell commands in this response.**

### Step 9 — Shell consumption (expected)

```typescript
// ShellCommandListener.tsx — parallel mechanisms
EventSource(apiUrl("/api/shell/stream"))  // if VITE_SHELL_SSE !== "0"
setInterval(tick, 2000)                   // poll backup
fetch(apiUrl("/api/shell/poll"))          // drains _queue
```

For each command in batch, `applyOne()`:

1. **`set_mode`** → `setMode("transport")`
2. **`atlas_transport_action`** → may `clearTransportRouteState()` if graph fields present in listener; enqueues to `atlasTransportActions`
3. **`transport_route_view`** →
   ```typescript
   setTransportPathIds(raw.path_ids)
   setTransportStationPathIds(raw.station_path_ids)
   setTransportRouteLegs(raw.route_legs)
   setTransportRouteMeta(raw.route_meta)
   ```

### Step 10 — TransportMode map refresh (expected)

```typescript
// useEffect deps include pathIds, pathStationIds, transportExplorationSeq, ...
if (!showMapbox) return;  // viz must be geographic | network_3d
scheduleBaseMapRefresh()
  → executeBaseMapRefresh()
  → readTransportViewContext()
  → buildTransportBaseMapBody(ctx, { selectedStopId, selectedStationId })
  → POST /api/transport/map
  → setMapUrl(blob URL)  // new iframe
```

Map body includes:

```json
{
  "mode": "metro",
  "use_lcc": true,
  "viz_mode": "geographic",
  "graph_viz_mode": "station",
  "path_stop_ids": ["IDFM:..."],
  "path_station_ids": ["STATION:..."]
}
```

### Step 11 — Atlas transport action handler (async, after shell apply)

```typescript
// TransportMode useEffect — processes atlasTransportActions[0]
applyAtlasTransportPatches(spec)  // fills qStart, qEnd, dock tab, graph_mode
if (spec.run === "none") {
  finishAction();
  return;  // ← no postRoute(), no client-side compute
}
```

### Step 12 — Map iframe render

Server returns Mapbox HTML with route layers baked in for `path_stop_ids` / `path_station_ids`. iframe loads blob URL; optional postMessage for incremental overlays.

### Failure point observed in production logs

If step 9 never runs: `shell_pending` stays > 0, Zustand path IDs remain `null`, step 10 never receives path data → **map unchanged, chat still OK**.

---

## 4. Current data flow for other UI actions

### 4.1 POIs around a station

**Example:** « Montre les POI autour de Gare de l'Est »

| Stage | Detail |
|-------|--------|
| Intent | `route_poi()` or explore intent → `cspe_explore_area` or `cspe_nearby_pois` |
| Backend | `POST /api/transport/area/explore` or tool wrapper with `sync_ui: true` |
| Shell cmds | `set_mode` → `transport_route_view` (clear route) → `transport_exploration_view` → `atlas_transport_action(run: "exploration_map")` |
| Frontend | `setTransportExploration(view)` bumps `transportExplorationSeq`; action handler calls `scheduleMapRefresh()` (full map HTML with embedded `exploration_overlay`) |
| Chat | `appendChatExploration(view)` in shell listener |

**Chat-only path (no map):** `cspe_lookup_place_online` → `POST /api/agent/transport/place-lookup` — **no shell enqueue** (`shell_enqueued_delta=0`).

### 4.2 Search / highlight a stop

| Path | Mechanism |
|------|-----------|
| Agent | `cspe_transport_action` with `run: "search_map"`, `stop_lookup_query` OR exploration with selected IDs |
| Manual | User types in Search tab → `searchStops()` → `setMapSelection` → `scheduleMapRefresh` with `selected_station_id` / `selected_stop_id` |
| Shell | `transport_exploration_view` may include center; `exploration_map` action sets selection + refresh |

### 4.3 Change transport mode (metro / rail / …)

| Path | Mechanism |
|------|-----------|
| Intent UI | `try_ui_settings_intent` or `route_transport` mode-only → `cspe_transport_action(spec: { run: "none", graph_mode: "metro" })` |
| Shell | `transport_graph_mode` OR `atlas_transport_action` with `graph_mode` |
| Frontend | `setTransportGraphMode()` → `useEffect` clears route if graph mode changed in listener → map refresh |

### 4.4 Open transport map / switch viz

| Command | Shell / action |
|---------|----------------|
| Geographic / 3D map | `transport_options` `{ viz: "geographic" \| "network_3d" }` or `atlas_transport_action` `{ viz: ... }` |
| Refresh | `run: "refresh_map"` → `scheduleMapRefresh()` |
| Clear | `run: "clear_transport_ui"` or `reset_route` |

### 4.5 Open GraphXR / 3D

| Stage | Detail |
|-------|--------|
| Tool | `cspe_open_graph3d` or route with `open_graph3d: true` |
| Backend | `agent_tools.create_graph3d_for_route()` → session row |
| Shell | `{ kind: "transport_graph3d_sync", sync_client_id, enabled: true }` |
| Frontend | `setTransportViz("graph3d")`, `enableGraph3dLiveSync()`, load viewer iframe |
| Sync | `graph3dSync.ts` pushes fingerprint to `/api/transport/graph3d/sync` on state changes |

### 4.6 Filter visible POIs / exploration follow-up

`cspe_filter_visible_results` → explore filter API with `sync_ui` → new `shell_commands_for_exploration()` batch.

---

## 5. Backend success vs UI success

Five distinct success levels:

| Level | Meaning | Observable signal | Can fail silently? |
|-------|---------|-------------------|-------------------|
| **L1 — Tool OK** | Route computed, exploration built | `[Tool] cspe_compute_route ok=true` | No |
| **L2 — Shell enqueued** | Commands in `_queue` | `shell_enqueued_delta=3`, `shell_pending=N` | **Yes** — pending grows if no consumer |
| **L3 — Shell applied** | `ShellCommandListener` ran `applyOne` | `postAgentEvent("shell.commands_applied")`, client logs `atlas_transport_action` | **Yes** — compact log mode hides client logs |
| **L4 — State updated** | Zustand has `transportPathIds` | React devtools / `AgentContextSync` PATCH | Partial — PATCH is async |
| **L5 — Map rendered** | iframe shows path | Visual / `POST /api/transport/map` 200 | **Yes** — if `showMapbox` false or refresh skipped |

### “Looks successful” trap matrix

| Symptom in logs | What user sees | Missing level |
|-----------------|----------------|---------------|
| `[Tool] ok=true`, `[Final] Route confirmed...` | Chat OK, map empty | L2–L5 (shell not consumed or map not refreshed) |
| `shell_pending=6` after turns | Chat OK | L3 — browser never drained queue |
| `shell_enqueued_delta=3`, pending unchanged | Chat OK | L3 |
| Shell applied, `pathIds` set, `viz=graph3d` | Chat OK, no 2D path | L5 — wrong viz mode |
| `transport_route_view` applied then `clearTransportRouteState` from later command | Intermittent blank map | L4 race / command order |
| Backend route OK, frontend uses `run:"route"` path separately | Double compute or overwrite | Duplicate mechanisms |

**Major architectural issue:** `POST /api/chat` success is treated as full turn success by the UI, but it only represents **L0 (text reply)** — not map sync.

---

## 6. Previous fixes and temporary patches

From `git log` on sync-related files:

| Commit | Date | Stated intent | Files | Why temporary / fragile |
|--------|------|---------------|-------|-------------------------|
| `cb598446` | 2026-04-09 | Improved UI | `TransportMode.tsx`, `AtlasRailPanel.tsx`, `AppShell.tsx`, shell routers | UI refactor without single sync contract |
| `3ba7e0ae` | 2026-05-28 | **Enhance transport exploration + logging** | `shell.py`, `agent_tools.py`, `TransportMode.tsx`, `ShellCommandListener.tsx`, `transport_exploration.py`, `mapExplorationBridge.ts`, `transportViewState.ts` | Added **second map path** (overlay API + postMessage) alongside full reload; incremental path never wired to main flow |
| `7a97423d`, `5d6bc36b` | — | "Working" / "Somehow working" | Same area | Commit messages indicate unstable fixes |
| `3a6af706` | — | Cleaning Initiated | Broad | Risk of regressions during cleanup |

### Patch patterns found in code

| Pattern | Location | What it tried to fix | Why it breaks again |
|---------|----------|----------------------|---------------------|
| **`run: "none"` + `transport_route_view`** | `shell_commands_for_route()` | Avoid double route compute on client | Depends entirely on shell queue delivery; if queue fails, **nothing** runs on client |
| **SSE + poll dual delivery** | `ShellCommandListener.tsx` | Missed commands | Dedupe by JSON signature; SSE connect steals queue on stream attach; silent fetch failures |
| **`exploration_map` retry loop** | `TransportMode.tsx` L802–808 | Race: action before exploration view | Fixed delay 0–160ms insufficient under load |
| **`schedulePendingExplorationDelivery`** | `TransportMode.tsx` | iframe not ready | Retries up to 5s; route path doesn't use equivalent for path overlay |
| **`postTransportRouteOverlay` API** | `transport.py`, `client.ts` | Incremental route update without full HTML reload | **Never called from TransportMode** — dead code path |
| **`postRouteToMapIframe`** | `mapExplorationBridge.ts` | Incremental route via postMessage | **Never called** |
| **`scheduleExplorationOverlay` scheduler** | `TransportMode.tsx` L335–337 | Separate overlay scheduler | **`scheduleExplorationOverlayRef` never invoked** — dead |
| **`AgentContextSync` PATCH** | `AgentContextSync.tsx` | Planner reads UI state | Mirror only; **does not drive map**; can drift from shell |
| **Compact log suppression** | `ui_transport_logger.py`, `project_logs.py` | Reduce noise | Hides `atlas_transport_action`, shell client events → **debugging blind spot** |
| **`VITE_API_BASE` ngrok override** | `run_web_app.ps1 -QuestVR` | Quest HTTPS | PC on `localhost:5173` + API on ngrok → cross-origin shell poll may fail silently |
| **Signature dedupe in ShellCommandListener** | `shellCommandSignature()` | Duplicate SSE+poll | **Identical repeat commands skipped** — OK for duplicates, bad if legitimate re-route with same endpoints |
| **`transportActionSpecFingerprint` skip** | `ShellCommandListener.tsx` L42–44 | Duplicate actions | Skips repeated explore at same center — can block valid updates |

### Duplicated / contradictory mechanisms (explicit)

1. **Server route + `transport_route_view`** vs **client `run:"route"` + `postRoute()`**
2. **Full map reload** (`POST /transport/map`) vs **exploration overlay API** vs **route overlay API** (latter unused)
3. **Shell queue** vs **`PATCH /api/agent/context`** (planner feedback vs UI driver)
4. **Chat structured_outputs** (text) vs **shell commands** (UI) — no shared schema
5. **Embedded exploration in map body** vs **postMessage overlay** — both exist; route uses embed-only

---

## 7. API contracts and schemas

### 7.1 Shell command schema (de facto, not Pydantic-validated)

Backend emits dicts with required `"kind"`. Frontend switch in `applyOne()`.

**Route view command (backend → frontend):**

```python
# Python keys in shell_commands_for_route
{
  "kind": "transport_route_view",
  "path_ids": list[str],              # ← named path_ids
  "station_path_ids": list[str],      # ← not station_path
  "route_legs": list[dict],
  "route_meta": str,
  "clear_paths": bool,  # optional
  "route_error": str,   # optional
}
```

**Transport engine route response:**

```python
# TransportRouteResponse / compute_route output
{
  "path": list[str],           # ← named path, not path_ids
  "station_path": list[str],   # ← not station_path_ids
}
```

**Mapping happens in `shell_commands_for_route`:** `route["path"]` → `path_ids`, `route["station_path"]` → `station_path_ids`. **Correct at enqueue time.**

### 7.2 Map POST body (frontend → backend)

```typescript
// buildTransportMapBody — transportViewState.ts
{
  mode, use_lcc, viz_mode, graph_viz_mode,
  path_stop_ids: ctx.pathIds,        // ← path_stop_ids not path_ids
  path_station_ids: ctx.pathStationIds,
  selected_stop_id, selected_station_id,
  show_transfers,
  exploration_overlay?: { ... }      // embedded for explore path
}
```

Pydantic: `TransportMapRequest.path_stop_ids`, `path_station_ids`.

### 7.3 Agent route composite response

```python
# AgentTransportRouteResponse
{
  "ok": bool,
  "needs_user_choice": bool,
  "result": { ... compute_route_from_queries output ... },
  "graph3d": dict | null,
  "shell_queued": int
}
```

Tool executor reads this but **does not push to frontend** — only shell queue does.

### 7.4 Chat response

```python
# ChatResponse
{
  "structured_outputs": [{"type": "text", "content": "..."}],
  "raw_ui": dict | null,
  "error": str | null
}
```

**No UI command fields.** `normalize_atlas_ui()` extracts text only.

### 7.5 Known mismatches

| Area | Backend | Frontend | Impact |
|------|---------|----------|--------|
| Path field names | `path`, `station_path` in route object | `transportPathIds`, `path_stop_ids` in map body | Mapped in shell builder — OK if shell runs |
| Shell route cmd | `path_ids`, `station_path_ids` | `setTransportPathIds` | OK |
| Exploration | `nearby_pois` in shell view | `TransportExplorationView.nearby_pois` | OK |
| Route overlay API | GeoJSON in `route.path` FeatureCollection | `postRouteToMapIframe` expects `{ route, view }` | **Unused — UNKNOWN if shape matches without integration test** |
| `routing_scope` in shell spec | string `"station"` | maps to `graph_viz` via `applyAtlasTransportPatches` | Can change graph layer without clearing route when `run==="none"` |
| Transport mode names | `metro`, `rail`, … | Same enum in TS | OK |
| Coordinates | `{ lat, lon }` in exploration rows | Passed through as `Record<string, unknown>` | Map renderer expects this shape in `plot_mapbox.py` |

### 7.6 Major contract gap

**There is no versioned, typed, shared schema for shell commands** between Python and TypeScript. Commands are loose dicts / `Record<string, unknown>`. Drift is only caught at runtime in `applyOne()` default branch (silent no-op).

---

## 8. UI synchronization mechanism

### 8.1 Mechanisms in use

| Mechanism | Direction | Used for | Consumer |
|-----------|-----------|----------|----------|
| **`POST /api/chat`** | Browser → Shell → Atlas | User message | Chat text response only |
| **In-memory shell queue** | Backend → Browser | All UI sync | `ShellCommandListener` |
| **`GET /api/shell/poll`** | Browser drains queue | UI commands | Single consumer; clears queue |
| **`GET /api/shell/stream` (SSE)** | Backend pushes batches | Same queue | EventSource; on connect drains pending into subscriber queue |
| **Zustand** | In-process | Applied UI state | All React components |
| **`atlasTransportActions` queue** | Shell → TransportMode | Deferred imperative actions | `useEffect` in TransportMode |
| **`PATCH /api/agent/context`** | Browser → Backend | Planner world mirror | Atlas planner reads; **not UI driver** |
| **`postAgentEvent`** | Browser → Backend | Telemetry | Activity log |
| **`postShellClientLog`** | Browser → Backend | Pipeline milestones | Activity log (compact suppressed) |
| **postMessage** | Parent ↔ map iframe | Exploration overlay (partial) | `mapExplorationBridge.ts` |
| **Graph3D sync HTTP** | Frontend → `/api/transport/graph3d/sync` | 3D viewer | GraphXR iframe |

**Not used for UI commands:** WebSocket, localStorage, URL params, shared worker.

### 8.2 Shell consumer algorithm

```typescript
// ShellCommandListener.tsx (simplified)
const applied = new Set<string>();  // JSON signature dedupe

async function tick() {
  const r = await fetch(apiUrl("/api/shell/poll"));
  if (!r.ok) return;                    // ← silent failure
  drainCommands(data.commands);
}

// SSE: es.addEventListener("commands", ...)
// Initial: void tick() on mount
// Backup: setInterval(tick, 2000) when SSE enabled
```

**Failure modes:**

- `apiUrl` points to wrong origin (ngrok vs localhost) → fetch fails → caught empty
- Tab closed / listener not mounted → queue grows (`shell_pending`)
- Second tab polls → steals commands from first tab
- SSE reconnect steals `_queue` into subscriber buffer; if EventSource broken, commands lost from poll queue

### 8.3 Conflicts

| Conflict | Description |
|----------|-------------|
| SSE vs poll | Both intended as redundancy; dedupe helps but queue ownership is ambiguous on SSE connect |
| Shell vs context PATCH | Two representations of route state; planner may see PATCH before shell applied |
| Shell vs chat | User perceives turn complete at chat return; shell may arrive seconds later or never |
| Full reload vs postMessage | Two rendering strategies; only full reload used for routes |

---

## 9. Map rendering mechanism

### 9.1 Route / path display

**Primary path (agent routes):**

1. `transport_route_view` sets `transportPathIds`, `transportStationPathIds` in Zustand
2. `useEffect` in `TransportMode` (L397–412) calls `scheduleBaseMapRefresh()` when `pathIds` change **and `showMapbox`**
3. `executeBaseMapRefresh()` → `POST /api/transport/map` with `path_stop_ids`, `path_station_ids`
4. Server `transport_engine` / `plot_mapbox.py` renders route layers into HTML
5. New blob URL assigned to iframe `src`

**Alternate path (manual / `run:"route"` action):**

1. Client `searchStops` + `postRoute()` → `/api/transport/route`
2. `applyRouteResult()` sets path IDs locally
3. Same map refresh effect

**Unused alternate:**

- `POST /api/transport/map/route-overlay` + `postRouteToMapIframe()` — would update without full HTML reload

### 9.2 Selected station / highlight

State: `transportMapSelectionStopId`, `transportMapSelectionStationId`

Map body: `selected_stop_id`, `selected_station_id`

Set by: manual search, `exploration_map` action, `transportMapFocus` from rail list

### 9.3 POIs / exploration

1. `transport_exploration_view` → `setTransportExploration`
2. `buildTransportMapBody` embeds `exploration_overlay` when exploration active **and no route**
3. If route active, exploration overlay **stripped** from map body (`hasRoute` branch in `transportViewState.ts` L100–103)
4. Optional incremental: `postTransportExplorationOverlay` + postMessage — partial wiring

### 9.4 Transport mode / graph layer

`transportGraphMode` → map body `mode` field → filters loaded graph

`transportGraphViz` → `graph_viz_mode` → stop vs station rendering

Changing mode in `ShellCommandListener` may call `clearTransportRouteState()` before new route view arrives.

### 9.5 Conditions where data exists but is not rendered

| Condition | Code location | Effect |
|-----------|---------------|--------|
| `transportViz === "graph3d"` | `showMapbox = false` | Map refresh effect returns early — **path IDs in store but no 2D map** |
| Shell never applied | — | `pathIds` null |
| `fetch /api/shell/poll` fails silently | `ShellCommandListener` catch | No state update |
| Map fetch superseded | `mapFetchSeq` | Stale response dropped — OK |
| Exploration cleared when route set | `transport_route_view` with paths | `clearTransportExplorationState()` in listener |
| Route cleared on graph option change | `transport_options` / `atlas_transport_action` in listener | Paths nulled before route_view in same tick — OK if order preserved |
| **`applyAtlasTransportPatches` with `run !== "none"`** | L652–653 | Clears route overlay on context change — **skipped for `run:"none"`** |

### 9.6 State reset / overwrite

| Trigger | Clears |
|---------|--------|
| `clearTransportRouteState()` in ShellCommandListener | All path fields |
| `clearRoute()` / `clearRouteOverlay()` in TransportMode | Local + store paths |
| New exploration shell cmd | Route cleared explicitly before POI view |
| `setTransportGraphMode` change + listener handlers | Route cleared in shell listener |

---

## 10. Race conditions and lifecycle problems

| # | Scenario | Evidence | Symptom |
|---|----------|----------|---------|
| R1 | **Browser tab not polling shell queue** | `shell_pending=6` | Permanent UI desync; chat works |
| R2 | **`VITE_API_BASE` ngrok + page on localhost** | `run_web_app.ps1 -QuestVR`, `apiUrl()` | Shell fetch cross-origin fail silently |
| R3 | **Chat completes before shell applied** | Async poll 2s interval | User sees answer, map updates late or never |
| R4 | **`exploration_map` before `transport_exploration_view`** | 160ms wait loop | Empty map overlay |
| R5 | **Map iframe not ready** | `mapReadyGeneration !== mapBaseGeneration` | Exploration postMessage retries; route has no equivalent |
| R6 | **SSE connect drains `_queue` into subscriber only** | `shell.py` L119–121 | Poll gets empty; if SSE broken, commands stuck |
| R7 | **Multiple browser tabs** | Single-consumer poll | Random tab steals commands |
| R8 | **`showMapbox` false during route command** | User in GraphXR view | Path stored but 2D not shown |
| R9 | **Hot reload remounts ShellCommandListener** | Vite HMR | Transient duplicate or missed commands during dev |
| R10 | **Stale closure in action handler** | `localUiRef`, `processingActionSeqRef` | Rare double-process or skip |
| R11 | **Command batch order: clear then set** | Same drain loop synchronous | OK today; fragile if refactored to async per command |
| R12 | **Dedupe signature skips legitimate repeat route** | Same from/to queries | Second route might not apply |

---

## 11. Logs and observability

### 11.1 Existing logs

| Source | Location | What it shows | Gap |
|--------|----------|---------------|-----|
| Atlas planner | `activity.log` / compact | `[PlannerLive] step=`, `tool=`, `validation_ok` | No shell apply confirmation |
| Tool receipt | compact `[Tool]` | `cspe_compute_route ok=true` | No UI correlation |
| Chat return | compact `[Chat] product_chat_return` | **`shell_enqueued_delta`, `shell_pending`** | **Best backend indicator of UI failure** |
| Final reply | `[Final]` / `[PlannerLive] final_openai_response=done` | Text completion | Not map |
| Shell enqueue | `ui_transport_logger` | `transport_action_enqueued` | **Disabled in compact mode** |
| Shell client | `POST /shell/client-log` | `atlas_transport_action`, `atlas_transport_trigger`, `exploration_map_refresh` | **Disabled/noisy filter in compact mode** |
| HTTP access | `project_logs.py` | `/api/shell/poll` **suppressed** | Cannot see poll frequency |
| Browser console | `console.info("[atlas_transport] action enqueued")` | Only if shell applied | Not persisted |

**Correlation ID:** Atlas turns use `correlation_id` in planner logs (`begin_turn`, `[Turn N]`). **Shell commands do not carry correlation_id.** Chat log line does not echo correlation_id next to `shell_pending`.

### 11.2 Proposed trace model (command ID end-to-end)

Introduce **`ui_command_id`** (reuse Atlas `correlation_id`):

| Stage | Log line (proposed) |
|-------|---------------------|
| T0 | `[UICommand] cid=abc123 phase=turn_start user="..."` |
| T1 | `[UICommand] cid=abc123 phase=intent tool=cspe_compute_route` |
| T2 | `[UICommand] cid=abc123 phase=backend_route ok=true path_len=12` |
| T3 | `[UICommand] cid=abc123 phase=shell_enqueue count=3 kinds=set_mode,atlas_transport_action,transport_route_view pending=3` |
| T4 | `[UICommand] cid=abc123 phase=shell_deliver consumer=poll count=3` |
| T5 | `[UICommand] cid=abc123 phase=shell_apply kind=transport_route_view path_ids=12` |
| T6 | `[UICommand] cid=abc123 phase=state path_stop_ids=12 map_viz=geographic` |
| T7 | `[UICommand] cid=abc123 phase=map_request path_stop_ids=12` |
| T8 | `[UICommand] cid=abc123 phase=map_render ok=true bytes=842000` |
| T9 | `[UICommand] cid=abc123 phase=complete ui_ok=true` |

**Alert condition:** T3 without T4 within 5s → `UI_SYNC_TIMEOUT`. T5 without T8 → `UI_RENDER_FAILED`.

**Frontend:** surface shell poll failures in UI (toast + `postShellClientLog("shell_poll_error", ...)`).

**Never suppress:** `/api/shell/poll` failures and `shell_pending` growth in compact log.

---

## 12. Root-cause hypotheses

Ranked by likelihood and evidence.

### H1 — Shell queue not consumed by browser (CONFIRMED in live session)

| | |
|--|--|
| **Evidence** | `shell_pending=6`, `total_enqueued=6`; chat OK |
| **Files** | `shell.py`, `ShellCommandListener.tsx`, `chat.py`, `api/config.ts`, `run_web_app.ps1` |
| **Symptom** | Backend + AI success; zero UI change |
| **Confirm** | Watch `GET /api/shell/stats` while using app; poll Network tab |
| **Re-breaks fixes** | Any change to API base URL, Quest mode, or listener mount without fixing delivery |

### H2 — Architectural decoupling: chat success ≠ UI sync (CONFIRMED by design)

| | |
|--|--|
| **Evidence** | `ChatResponse` has text only; shell is separate channel |
| **Files** | `chat.py`, `normalize.py`, `useAtlasTextChat.ts` |
| **Symptom** | Reliable chat, unreliable map |
| **Confirm** | Code inspection — no UI in chat response |
| **Re-breaks fixes** | Patching map in one path without the other |

### H3 — Silent failure in ShellCommandListener (HIGH)

| | |
|--|--|
| **Evidence** | Empty `catch {}` on poll; `if (!r.ok) return` |
| **Files** | `ShellCommandListener.tsx` L257–267 |
| **Symptom** | No UI, no user-visible error |
| **Confirm** | Break `VITE_API_BASE` intentionally, observe silence |
| **Re-breaks fixes** | Cross-origin / ngrok / CORS regressions invisible |

### H4 — QuestVR / VITE_API_BASE cross-origin mismatch (HIGH in Quest dev)

| | |
|--|--|
| **Evidence** | `-QuestVR` sets `VITE_API_BASE=https://ngrok...` while user opens `localhost:5173` |
| **Files** | `run_web_app.ps1` L860, `frontend/src/api/config.ts` |
| **Symptom** | Chat may work via ngrok CORS; shell poll may fail intermittently |
| **Confirm** | Compare `apiUrl("/api/shell/poll")` origin vs page origin |
| **Re-breaks fixes** | Every ngrok URL change |

### H5 — Multiple duplicate sync paths; dead incremental route overlay (MEDIUM)

| | |
|--|--|
| **Evidence** | `postTransportRouteOverlay`, `postRouteToMapIframe`, `scheduleExplorationOverlayRef` unused |
| **Files** | `TransportMode.tsx`, `client.ts`, `transport.py` |
| **Symptom** | Partial fixes wired one path; regressions when other path used |
| **Confirm** | ripgrep call sites |
| **Re-breaks fixes** | Developers assume overlay path works; it doesn't |

### H6 — Race: exploration_map / iframe readiness (MEDIUM for POI)

| | |
|--|--|
| **Evidence** | 160ms poll loop; postMessage retries for exploration only |
| **Files** | `TransportMode.tsx`, `mapExplorationBridge.ts` |
| **Symptom** | POI missing; route path separate |
| **Confirm** | Slow map load + explore command |

### H7 — `showMapbox` false while in graph3d (LOW for 2D route reports)

| | |
|--|--|
| **Evidence** | `if (!showMapbox) return` in refresh effect |
| **Symptom** | User expects 2D path while in 3D view |
| **Confirm** | Check `transportViz` when route issued |

### H8 — SSE queue steal on reconnect (LOW–MEDIUM)

| | |
|--|--|
| **Evidence** | `shell_stream()` clears `_queue` into subscriber on connect |
| **Files** | `shell.py` L117–121 |
| **Symptom** | Commands lost if SSE broken after steal |
| **Confirm** | `shell_pending=0` but UI unchanged, SSE connection errors in Network |

---

## 13. Recommended stable architecture

### 13.1 Principles

1. **One canonical UI command bus** — not chat + shell + context PATCH + ad hoc postMessage
2. **Structured commands versioned** — shared JSON Schema or OpenAPI component consumed by Python + TypeScript codegen
3. **Same HTTP response carries text + UI commands for chat turns** — shell queue becomes optimization/legacy, not sole path
4. **Explicit UI sync acknowledgment** — frontend reports `command_id` applied or failed
5. **Fail loud** — never silent catch on sync channel

### 13.2 Single source of truth

| Concern | Source of truth |
|---------|-----------------|
| **UI commands emission** | Product Shell (after tool execution) |
| **UI commands application state** | Zustand `transportCommandRevision` + derived view state |
| **Planner context mirror** | Read from same applied state snapshot (not parallel PATCH stream) |
| **Rendered map** | Function of Zustand snapshot + map generation epoch |

### 13.3 Canonical UI command schema (proposal)

```typescript
interface UiCommandBatch {
  command_id: string;      // == correlation_id
  turn_id?: number;
  commands: UiCommand[];
}

type UiCommand =
  | { type: "SET_TRANSPORT_VIEW"; payload: TransportViewPatch }
  | { type: "SET_ROUTE"; payload: RouteViewPayload }
  | { type: "SET_EXPLORATION"; payload: ExplorationViewPayload }
  | { type: "CLEAR_ROUTE" }
  | { type: "OPEN_GRAPH3D"; payload: { sync_client_id: string } }
  | { type: "RUN_ACTION"; payload: AtlasTransportActionSpec };
```

Replace ad hoc `kind` strings gradually; version field `schema_version: 1`.

### 13.4 Chat response shape (proposal)

```python
class ChatResponse(BaseModel):
    structured_outputs: list[dict]
    ui_commands: UiCommandBatch | None = None  # NEW — same batch as enqueued
    ui_sync: Literal["inline", "queued", "none"] = "inline"
    error: str | None = None
```

Frontend applies **`ui_commands` immediately** in `useAtlasTextChat` after chat returns, **and** shell queue remains for voice-only / headless / multi-tab with dedupe by `command_id`.

### 13.5 Queue when map not ready

Command applier service in frontend:

```
receive batch → persist in Zustand pendingCommands
for each command: apply to state immediately
if command requires map render: bump mapGenerationRequest
map iframe onReady → flush pending render requirements
report POST /api/agent/events { event: "ui.command_applied", command_id }
```

### 13.6 Prevent schema drift

- Add `shared/ui_commands.schema.json` at repo root
- Generate Python TypedDict / TS types in CI
- Contract tests: shell builder output validated against schema

### 13.7 Error surfacing

If backend enqueues commands but frontend does not ACK within N seconds:

- Backend logs `UI_SYNC_TIMEOUT`
- Frontend shows banner: « Route calculé — carte non synchronisée. [Réessayer] »
- Retry = `GET /api/shell/poll` + manual `scheduleMapRefresh()`

---

## 14. Concrete fix plan

**Do not implement quick patches.** Phased root-level work:

### Phase 0 — Observability (1–2 days)

| Task | Files |
|------|-------|
| Add `correlation_id` to shell command batches at enqueue | `agent_tools.py`, `shell.py`, Atlas planner |
| Log `shell_deliver` / `shell_apply` with cid | `shell.py`, `ShellCommandListener.tsx` |
| Remove silent catch on poll; log + toast | `ShellCommandListener.tsx` |
| Log `shell_pending` warning if > 0 at end of `post_chat` | `chat.py` |
| Stop suppressing shell poll errors in compact log | `project_logs.py` |

### Phase 1 — Dual delivery fix (2–3 days)

| Task | Files |
|------|-------|
| Return enqueued commands inline in `ChatResponse` | `chat.py`, `atlas_http.py`, `schemas.py` |
| Apply inline commands in `useAtlasTextChat` | `useAtlasTextChat.ts`, extract shared `applyUiCommands()` from listener |
| Deduplicate by `command_id` | `ShellCommandListener.tsx`, store |
| Fix QuestVR: do not set `VITE_API_BASE` to ngrok for PC browser OR document open ngrok URL only | `run_web_app.ps1`, `GUIDE_UTILISATION.md` |

### Phase 2 — Consolidate map update strategy (3–5 days)

| Task | Files |
|------|-------|
| Choose **one** route render strategy: full reload OR overlay API — implement fully | `TransportMode.tsx`, delete unused path |
| Wire `postRouteToMapIframe` OR remove dead code | `mapExplorationBridge.ts`, `client.ts` |
| Remove `scheduleExplorationOverlayRef` dead scheduler or connect it | `TransportMode.tsx` |
| Unify `run:"none"` + route view into single `SET_ROUTE` command | `agent_tools.py`, listener |

### Phase 3 — Schema + tests (3–5 days)

| Task | Files |
|------|-------|
| Add `shared/ui_commands.schema.json` | new |
| Codegen TS + Python validators | CI script |
| Integration test: route command → state → map body | `tests/` |

### Phase 4 — Ack + timeout (2 days)

| Task | Files |
|------|-------|
| `POST /api/agent/events` UI ack with command_id | `AgentContextSync` or new hook |
| Backend watchdog for pending shell + no ack | `shell.py`, `agent_store.py` |

### Rollback strategy

- Feature flag `UI_SYNC_INLINE_COMMANDS=1` for Phase 1
- Keep shell queue unchanged behind flag until inline proven
- Revert flag without removing observability from Phase 0

### Manual test scenarios

1. Route République → Orly — path visible ≤ 3s after chat
2. POI explore — markers visible
3. Mode switch metro → rail — map layer changes
4. `-QuestVR` ngrok URL — path visible on PC and Quest
5. Two tabs — no stolen commands (or explicit single-tab warning)
6. Graph3D open — return to geographic shows last route

---

## 15. Tests to prevent regression

### 15.1 Backend unit tests

| Test | Input | Expected backend | Expected shell |
|------|-------|------------------|----------------|
| `test_shell_commands_for_route_success` | mock route result | `ok=True` | 3 cmds, `path_ids` populated |
| `test_shell_commands_for_route_failure` | unresolved endpoints | `ok=False` | `route_error` set |
| `test_chat_returns_inline_ui_commands` | mock Atlas turn with route | `ChatResponse.ui_commands` not empty | matches enqueued batch |
| `test_shell_stats_after_enqueue` | enqueue 3 | `pending=3` | — |

### 15.2 Frontend unit tests

| Test | Input | Expected state | Expected UI |
|------|-------|------------------|-------------|
| `applyUiCommands_route_view` | `transport_route_view` cmd | `transportPathIds.length > 0` | — |
| `applyUiCommands_clears_on_explore` | exploration batch | `transportPathIds === null` | — |
| `shellListener_dedupes_by_command_id` | duplicate batch | applied once | — |
| `buildTransportMapBody_includes_paths` | pathIds set | body.path_stop_ids non-null | — |

### 15.3 Integration tests

| Test | Flow | Assertion |
|------|------|-----------|
| `test_agent_route_end_to_end` | POST `/api/agent/transport/route` + poll shell | poll returns 3 cmds with path_ids |
| `test_chat_shell_pending_drain` | POST `/api/chat` + poll loop | pending returns to 0 |

### 15.4 E2E (Playwright)

| Test | Steps | Visible result |
|------|-------|----------------|
| `route_displays_on_map` | Open app, send chat route, wait map | SVG/canvas route layer OR legend meta |
| `poi_markers_visible` | Explore command | POI count > 0 in DOM/log |
| `station_highlight` | Search station | selected marker |
| `mode_switch` | « Passe en mode métro » | mode button active |

### 15.5 Mocked AI command tests

Use recorded shell batches from `planner_live_test_lib.py`:

- Feed batch to `applyUiCommands`
- Snapshot Zustand state
- Snapshot `buildTransportMapBody` output

---

## 16. Final diagnostic summary

### Most likely root cause

**The UI sync channel (in-memory shell queue + browser poll/SSE) is not reliably consumed**, while the chat channel succeeds independently. Live evidence: **`shell_pending=6`** with successful `cspe_compute_route` and assistant replies. This is exacerbated by **silent fetch failures** in `ShellCommandListener` and **QuestVR cross-origin API configuration**.

### Most dangerous architectural weakness

**Decoupled success criteria:** `POST /api/chat` returns natural language only; structured UI updates depend on a **second, best-effort, single-consumer queue** with no acknowledgment, no correlation ID, and no user-visible error path. The system is designed to look successful in Atlas logs when the map is unchanged.

### Recommended fix priority

1. **Phase 0 observability** — make failure visible immediately
2. **Phase 1 inline UI commands in chat response** — eliminate sole dependency on poll
3. **Phase 2 single map render path** — remove dead overlay code
4. **Phase 3 schema + contract tests** — stop drift

### What should not be done again

- Fixing only `TransportMode` refresh logic without verifying shell delivery
- Adding a third parallel sync mechanism (more postMessage paths) without removing old ones
- Treating `[Tool] ok=true` or assistant text as proof of UI sync
- Silencing `/api/shell/poll` errors in logs or empty catch blocks
- Temporary `setTimeout` retries without command-level tracing and ACK

---

*Audit generated from codebase inspection and live log correlation. Key reproduction: route commands enqueue 3 shell commands; `shell_pending` remains elevated when the browser does not drain `/api/shell/poll`.*
