# CSPE Project Architecture

This document describes the **CSPE** (Combined Spatial Product Environment) stack as implemented in the repository: a local full-stack application for exploring and routing on **Île-de-France public transport**, with an **Atlas** AI assistant that drives the UI through a shell command queue.

Diagrams use [Mermaid](https://mermaid.js.org/). They render in GitHub, VS Code, and most modern markdown viewers.

---

## Table of contents

1. [System overview](#1-system-overview)
2. [Runtime processes and ports](#2-runtime-processes-and-ports)
3. [Repository layout](#3-repository-layout)
4. [Frontend architecture](#4-frontend-architecture)
5. [Product shell (FastAPI BFF)](#5-product-shell-fastapi-bff)
6. [Atlas agent](#6-atlas-agent)
7. [Transport and data pipeline](#7-transport-and-data-pipeline)
8. [Viewers: 2D map and GraphXR 3D/VR](#8-viewers-2d-map-and-graphxr-3dvr)
9. [Integration flows](#9-integration-flows)
10. [Quest VR mode](#10-quest-vr-mode)

---

## 1. System overview

At runtime, CSPE is a set of cooperating processes on localhost (or LAN). The browser talks to the **React frontend** and, through it or directly, to the **product shell API**. Atlas runs as a separate Flask service; tools call back into the product shell, which enqueues **shell commands** for the browser.

```mermaid
flowchart TB
  subgraph User["User"]
    Browser["Browser / Meta Quest"]
  end

  subgraph Frontend["Frontend — React + Vite :5173"]
    AppShell["AppShell"]
    TransportMode["TransportMode"]
    AtlasRail["AtlasRailPanel"]
    ShellListener["ShellCommandListener"]
    Store["Zustand store"]
  end

  subgraph OptionalVR["Optional Quest stack"]
    ProxyVR["proxy-vr.js :8080"]
    Ngrok["ngrok HTTPS tunnel"]
  end

  subgraph BFF["Product Shell — FastAPI :8787"]
    ChatAPI["/api/chat"]
    TransportAPI["/api/transport/*"]
    ShellAPI["/api/shell/*"]
    AgentAPI["/api/agent/*"]
    AtlasProxy["/api/atlas/*"]
  end

  subgraph Atlas["Atlas Agent — Flask :5055"]
    AtlasAPI["/text, /ui, /mode, /health"]
    Orchestrator["Orchestrator"]
    Planner["Agent Planner"]
    ToolExec["tool_executor (cspe_* tools)"]
  end

  subgraph Core["Python core + viz"]
    GraphBundle["graph_bundle.pkl"]
    MapboxGen["plot_mapbox.py"]
    POIIndex["POI balltree"]
  end

  subgraph GraphXR["GraphXR — Next.js :3000"]
    Viewer["ViewerClient (Babylon.js / WebXR)"]
  end

  subgraph Data["data/"]
    GTFS["gtfs/"]
    Derived["derived/"]
  end

  Browser --> Frontend
  Browser -.->|Quest mode| ProxyVR
  ProxyVR --> Frontend
  ProxyVR --> BFF
  ProxyVR --> GraphXR

  AppShell --> TransportMode
  AppShell --> AtlasRail
  AppShell --> ShellListener
  TransportMode --> Store
  AtlasRail --> Store
  ShellListener --> Store

  AtlasRail -->|POST /api/chat| ChatAPI
  AtlasRail -->|voice: /api/atlas/*| AtlasProxy
  TransportMode -->|maps, routes, graph3d| TransportAPI
  ShellListener -->|poll + SSE| ShellAPI
  TransportMode -->|iframe| Viewer

  ChatAPI --> AtlasAPI
  ChatAPI --> ShellAPI
  AtlasProxy --> AtlasAPI
  ToolExec --> TransportAPI
  ToolExec --> ShellAPI
  ToolExec --> AgentAPI

  TransportAPI --> GraphBundle
  TransportAPI --> MapboxGen
  TransportAPI --> POIIndex
  Viewer -->|session + sync| TransportAPI

  AtlasAPI --> Orchestrator --> Planner --> ToolExec
  GraphBundle --> Derived
  GTFS --> Derived
```

**Roles in one sentence each:**

| Layer | Role |
|-------|------|
| **Frontend** | Transport UI, map iframe, embedded 3D/VR iframe, Atlas chat/voice rail |
| **Product shell** | Single BFF: transport engine, shell queue, chat proxy, agent context |
| **Atlas** | NL planner + tool execution; never touches the browser directly |
| **Core / viz** | GTFS graphs, routing, Mapbox HTML generation, POI search |
| **GraphXR** | Standalone 3D/WebXR viewer consuming graph sessions from the BFF |
| **Data** | Offline GTFS-derived artifacts and runtime caches |

---

## 2. Runtime processes and ports

Launched by `run_web_app.ps1` from the repo root.

```mermaid
flowchart LR
  subgraph Launch["run_web_app.ps1"]
    S1["1. Atlas"]
    S2["2. Product shell"]
    S3["3. GraphXR"]
    S4["4. Vite (foreground)"]
    S5["5. Warmup POST"]
  end

  S1 -->|:5055| AtlasP["Atlas Flask"]
  S2 -->|:8787| ShellP["uvicorn product_shell"]
  S3 -->|:3000| GxrP["next dev graphxr"]
  S4 -->|:5173| ViteP["vite frontend"]
  S5 --> ShellP

  subgraph Quest["-QuestVR flag"]
    S6["proxy-vr.js :8080"]
    S7["ngrok → HTTPS"]
  end

  S6 --> ViteP
  S6 --> ShellP
  S6 --> GxrP
  S7 --> S6
```

| Port | Process | Entry / command | Purpose |
|------|---------|-----------------|---------|
| **5055** | Atlas Flask | `python -m atlas_client.app.run_api` in `src/work/atlas/` | Text/voice agent, planner, tools |
| **8787** | Product shell | `uvicorn backend.product_shell.main:app` | All `/api/*` for UI and Atlas tools |
| **5173** | Vite dev server | `npm run dev` in `frontend/` | React SPA; proxies `/api` → :8787 |
| **3000** | GraphXR | `npm run dev` in `viewers/graphxr/` | 3D/VR viewer at `/viewer` |
| **8080** | VR proxy | `node proxy-vr.js` (Quest mode) | Single HTTP entry for headset |
| **4040** | ngrok dashboard | ngrok CLI (Quest mode) | Public HTTPS URL for Quest WebXR |

**Launcher flags:**

- `-SkipAtlas` — skip Atlas; chat needs something on :5055
- `-SkipGraphXR` — skip viewer; set `VITE_GRAPHXR_VIEWER_URL` if running elsewhere
- `-QuestVR` — start proxy + ngrok; override `VITE_API_BASE` and `VITE_GRAPHXR_VIEWER_URL` with ngrok host

**Key environment variables:**

| Variable | Default / role |
|----------|----------------|
| `PRODUCT_SHELL_URL` | `http://127.0.0.1:8787` — Atlas tools call this |
| `CSPE_FRONTEND_URL` | `http://127.0.0.1:5173` — open map in browser |
| `VITE_API_BASE` | Same-origin `/api` in dev; ngrok URL in Quest mode |
| `VITE_GRAPHXR_VIEWER_URL` | `http://127.0.0.1:3000/viewer` |
| `MAPBOX_TOKEN` | Required for map HTML generation |
| `IDFM_API_KEY` | Optional live Navitia enrichment |
| `ATLAS_PYTHON` | Python executable for Atlas subprocess |

---

## 3. Repository layout

```mermaid
flowchart TB
  Root["CSPE repo root"]

  Root --> FE["frontend/"]
  Root --> BE["backend/product_shell/"]
  Root --> SRC["src/"]
  Root --> Atlas["src/work/atlas/"]
  Root --> Viewers["viewers/graphxr/"]
  Root --> Data["data/"]
  Root --> Scripts["scripts/"]
  Root --> Tests["tests/"]
  Root --> Docs["docs/"]
  Root --> Logs["logs/"]

  FE --> FEApp["src/ — React app"]
  FE --> FEVite["vite.config.ts — :5173, /api proxy"]

  BE --> Routers["routers/ — chat, transport, shell, agent, atlas"]
  BE --> Services["services/ — atlas_http, agent_tools, idfm, warmup"]
  BE --> Engine["transport_engine.py"]

  SRC --> Core["core/ — graph, routing, stations, POI"]
  SRC --> Viz["viz/ — plot_mapbox, paris_mask"]

  Data --> GTFS["gtfs/ — raw GTFS"]
  Data --> Derived["derived/ — graphs, indexes, caches"]
  Data --> Normalized["normalized/ — poi.parquet"]

  Atlas --> AtlasClient["atlas_client/ — app, core, router"]
```

| Path | Responsibility |
|------|----------------|
| `frontend/` | React 19 + Vite SPA: transport map, Atlas rail, shell listener |
| `backend/product_shell/` | FastAPI BFF on :8787 |
| `src/core/` | GTFS → NetworkX graphs, routing queries, station layer, POI index |
| `src/viz/` | Server-side Mapbox GL HTML |
| `src/work/atlas/` | Embedded Atlas runtime (Flask, orchestrator, planner, tools) |
| `viewers/graphxr/` | Next.js + Babylon.js 3D/WebXR graph viewer |
| `data/gtfs/` | Raw GTFS feeds |
| `data/derived/` | Built graphs, render JSON, map cache, IDFM CSVs |
| `scripts/` | Bundle rebuild, ops utilities |
| `tests/` | Python integration/unit tests |
| `proxy-vr.js` | Quest reverse proxy at repo root |
| `run_web_app.ps1` | Primary dev stack launcher |

---

## 4. Frontend architecture

The SPA is **transport-focused**: a single route `/` mounts `AppShell`, which fills the viewport with `TransportMode` and optionally shows `AtlasRailPanel` on the right.

```mermaid
flowchart TB
  subgraph Entry["Entry"]
    Main["main.tsx"]
    App["App.tsx → AppShell"]
  end

  subgraph Global["Global listeners (always mounted)"]
    Shell["ShellCommandListener"]
    AgentSync["AgentContextSync"]
    MapHotkey["MapFocusHotkey (F)"]
  end

  subgraph UI["Main UI"]
    Transport["TransportMode"]
    AtlasRail["AtlasRailPanel"]
  end

  subgraph TransportInternals["TransportMode internals"]
    MapIframe["Mapbox iframe (blob URL)"]
    Graph3dIframe["GraphXR iframe (embedded=1)"]
    LeftStack["Left HUD — viz, graph layer, mode"]
    Dock["Bottom dock — route / search"]
    ActionQueue["Atlas transport action processor"]
    MapRefresh["mapRefreshScheduler"]
    Graph3dSync["graph3dSync.ts"]
  end

  subgraph State["Zustand store.ts"]
    ChatState["chatHistory, structured outputs"]
    TransportState["graph mode, viz, paths, exploration, selection"]
    ShellQueue["atlasTransportActions[]"]
    Chrome["transportMapChromeHidden"]
  end

  subgraph API["frontend/src/api/"]
    Client["client.ts — HTTP to /api/*"]
    Config["config.ts — VITE_API_BASE, GraphXR URL"]
  end

  Main --> App
  App --> Global
  App --> UI
  Transport --> TransportInternals
  Shell --> State
  AgentSync --> State
  Transport --> State
  AtlasRail --> State
  TransportInternals --> Client
  AtlasRail --> Client
  Shell --> Client
```

### Visualization modes (`transportViz`)

```mermaid
stateDiagram-v2
  [*] --> geographic: default
  geographic --> network_3d: 3D map button
  network_3d --> geographic: Geographic button
  geographic --> graph3d: 3D/VR graph button
  graph3d --> geographic: ← Map exit / shell command
  network_3d --> graph3d: 3D/VR graph button

  note right of graph3d
    Fullscreen: hides Atlas rail,
    transport HUD, map chrome.
    GraphXR iframe with embedded=1.
  end note
```

### Shell command kinds (browser)

Handled in `ShellCommandListener.tsx`:

| Command kind | Effect |
|--------------|--------|
| `set_mode` | Switch app mode (transport) |
| `transport_graph_mode` | `all` / `metro` / `rail` / … |
| `transport_options` | LCC, viz, graph_viz, transfers |
| `transport_route_view` | Path IDs, legs, route meta/errors |
| `transport_exploration_view` | Nearby stops/POIs, radius, summary |
| `transport_graph3d_sync` | Enable live sync + switch to graph3d |
| `atlas_transport_action` | Enqueue structured transport action spec |
| `apply_structured_outputs` | Push planner outputs into chat store |

Delivery: **SSE** primary (`GET /api/shell/stream`), **poll** backup every 300 ms (or 2 s when SSE enabled).

---

## 5. Product shell (FastAPI BFF)

Single process on **:8787**. All browser and Atlas-tool traffic for transport, shell, chat proxy, and agent context goes through here.

```mermaid
flowchart TB
  subgraph FastAPI["backend/product_shell/main.py"]
    CORS["CORS middleware"]
    Warmup["warmup.start_background_warmup()"]
  end

  subgraph Routers["Routers (/api)"]
    RChat["chat.py"]
    RAtlas["atlas.py"]
    RShell["shell.py"]
    RAgent["agent.py"]
    RTransport["transport.py"]
  end

  subgraph Services["Services"]
    AtlasHTTP["atlas_http.py → :5055"]
    AgentTools["agent_tools.py"]
    AgentStore["agent_store.py"]
    Normalize["normalize.py"]
    IDFM["idfm_client + enrichment"]
    WarmupSvc["warmup.py"]
  end

  subgraph Engine["transport_engine.py"]
    BundleLoad["load graph_bundle.pkl"]
    MapRender["render_transport_map_html()"]
    RouteCompute["shortest path routing"]
    Graph3dStore["graph3d session + sync registry"]
    MapCache["map_html_cache/"]
  end

  FastAPI --> Routers
  RChat --> AtlasHTTP
  RChat --> Normalize
  RTransport --> Engine
  RTransport --> AgentTools
  RAgent --> AgentTools
  RAgent --> AgentStore
  AgentTools --> RShell
  Engine --> BundleLoad
  Engine --> MapRender
  Warmup --> WarmupSvc --> Engine
```

### Transport API surface

| Endpoint | Role |
|----------|------|
| `POST /transport/map` | Full Mapbox HTML from view state |
| `POST /transport/map/exploration-overlay` | Incremental exploration overlay |
| `POST /transport/map/route-overlay` | Route highlight overlay |
| `GET /transport/stops/search` | Autocomplete |
| `POST /transport/route` | Shortest-path route |
| `GET /transport/stops/nearby` | Nearby stops (+ optional `sync_ui`) |
| `GET /transport/pois/nearby` | Nearby POIs |
| `POST /transport/area/explore` | Combined area exploration |
| `POST /transport/graph3d/session` | Create 3D graph session |
| `GET /transport/graph3d/session/{id}` | Session project JSON for GraphXR |
| `POST /transport/graph3d/sync` | Push view fingerprint → new session |
| `GET /transport/graph3d/sync/{client_id}` | Poll for fingerprint changes |
| `GET /transport/stats` | Node/edge counts |

When handlers are called with `sync_ui=true`, `agent_tools` builds shell commands and `shell.py` enqueues them for the browser.

### Shell queue

```mermaid
sequenceDiagram
  participant Tool as Atlas tool_executor
  participant Enq as POST /shell/enqueue
  participant Q as In-memory deque (max 256)
  participant SSE as /shell/stream subscribers
  participant Poll as GET /shell/poll
  participant Browser as ShellCommandListener

  Tool->>Enq: commands[]
  Enq->>Q: append
  Enq->>SSE: fan-out event
  Browser->>Poll: tick (backup)
  Browser->>SSE: primary listener
  Q-->>Browser: drain commands
  Browser->>Browser: applyOne → Zustand
```

---

## 6. Atlas agent

Located under `src/work/atlas/`. Runs as a **separate Flask process** so its Python path and dependencies stay isolated from CSPE root imports.

```mermaid
flowchart TB
  subgraph Flask["Atlas Flask :5055"]
    Health["GET /health"]
    Text["POST /text"]
    UI["GET /ui"]
    Mode["POST /mode"]
  end

  subgraph Core["atlas_client/core"]
    RunSession["run_session() — background thread"]
    Orch["orchestrator.py — Realtime WS (voice)"]
    Planner["agent_planner.py — run_planner_turn()"]
    SessionState["session_state.py"]
  end

  subgraph Router["atlas_client/router"]
    Pipeline["planner_pipeline.py"]
    Shortcuts["planner_shortcuts.py"]
    Validator["planner_validator.py"]
    Tools["tool_executor.py"]
    Registry["tools_registry.json"]
  end

  subgraph External["HTTP callbacks"]
    PSTransport["PRODUCT_SHELL :8787 /api/transport/*"]
    PSShell["PRODUCT_SHELL :8787 /api/shell/enqueue"]
    PSAgent["PRODUCT_SHELL :8787 /api/agent/context"]
  end

  Text --> RunSession
  RunSession --> Orch
  RunSession --> Planner
  Planner --> Pipeline --> Tools
  Tools --> Registry
  Tools --> PSTransport
  Tools --> PSShell
  Tools --> PSAgent
  UI --> SessionState
```

### Text chat path

```mermaid
sequenceDiagram
  participant User
  participant Rail as AtlasRailPanel
  participant BFF as POST /api/chat
  participant Atlas as Atlas /text + /ui
  participant Planner as agent_planner
  participant Tools as tool_executor
  participant Shell as /api/shell/enqueue
  participant UI as React store

  User->>Rail: send message
  Rail->>BFF: chat request
  BFF->>Atlas: POST /text
  Atlas->>Planner: plan turn
  Planner->>Tools: cspe_* tools
  Tools->>BFF: transport API / agent context
  Tools->>Shell: enqueue UI commands
  BFF->>Atlas: poll GET /ui
  Atlas-->>BFF: panels + assistant text
  BFF-->>Rail: normalized structured outputs
  Shell-->>UI: SSE/poll → map/route/exploration update
```

### Representative CSPE tools

| Tool | Typical action |
|------|----------------|
| `cspe_search_stops` | Stop/station search via product shell |
| `cspe_compute_route` | Route computation |
| `cspe_explore_area` | Area exploration + `sync_ui` shell commands |
| `cspe_nearby_stops` / `cspe_nearby_pois` | Proximity queries |
| `cspe_open_graph3d` | Shell enqueue → graph3d viz |
| `cspe_update_map` | Shell enqueue → map state sync |
| `cspe_get_current_context` | Read agent world state from BFF |
| `cspe_open_transport_map` | Open `CSPE_FRONTEND_URL` in browser |

---

## 7. Transport and data pipeline

Offline GTFS is compiled into routing graphs and supporting indexes. The product shell loads a **cached bundle** at startup (with optional background warmup).

```mermaid
flowchart LR
  subgraph Raw["Raw inputs"]
    GTFS["data/gtfs/"]
    OSM["OSM POIs → poi.parquet"]
    IDFMLive["IDFM Navitia API (live)"]
  end

  subgraph Build["Build scripts"]
    Rebuild["scripts/rebuild_routing_bundle.py"]
    GraphLoader["src/core/graph_loader.py"]
    CacheBundle["src/core/cache_bundle.py"]
  end

  subgraph Derived["data/derived/"]
    Bundle["routing/graph_bundle.pkl"]
    Stops["stops/stop_popup_index.parquet"]
    Render["render_graphs/*.render_graph.json"]
    Maps["maps/ line geometry"]
    Indexes["indexes/poi_balltree.pkl"]
    MapCache["product_shell/map_html_cache/"]
  end

  GTFS --> Rebuild --> GraphLoader --> CacheBundle --> Bundle
  Bundle --> Stops
  Bundle --> Render
  OSM --> Indexes

  subgraph Runtime["Runtime queries"]
    Queries["src/core/queries.py"]
    Stations["src/core/station_layer.py"]
    POI["src/core/poi_index.py"]
    Legs["src/core/path_legs.py"]
  end

  Bundle --> Queries
  Bundle --> Stations
  Indexes --> POI
  IDFMLive -.->|enrichment| BFF["product_shell IDFM services"]
```

### Graph model (conceptual)

```mermaid
flowchart TB
  subgraph Modes["Per-mode graphs (NetworkX)"]
    All["all"]
    Metro["metro"]
    Rail["rail"]
    Tram["tram"]
    Bus["bus"]
  end

  subgraph Edges["Edge types"]
    Ride["GTFS ride edges"]
    Transfer["GTFS + inferred transfers"]
  end

  subgraph Layers["Presentation layers"]
    StopViz["stop markers"]
    StationViz["station aggregation"]
    HybridViz["both"]
  end

  Modes --> Edges
  Edges --> StopViz
  Edges --> StationViz
  Edges --> HybridViz
```

Routing is **stop-level** in the graph; **station paths** are derived via `station_layer.py` for station-first UI and summaries.

---

## 8. Viewers: 2D map and GraphXR 3D/VR

### 2D Mapbox map (embedded iframe)

```mermaid
sequenceDiagram
  participant TM as TransportMode
  participant BFF as POST /transport/map
  participant Engine as transport_engine
  participant Plot as plot_mapbox.py
  participant Iframe as Map iframe

  TM->>BFF: view state (mode, viz, paths, selection)
  BFF->>Engine: render_transport_map_html()
  Engine->>Plot: Mapbox GL HTML string
  Plot-->>Engine: self-contained HTML
  Engine-->>BFF: JSON { html }
  BFF-->>TM: blob URL
  TM->>Iframe: src = blob URL

  Note over TM,Iframe: Overlays via postMessage +<br/>exploration/route overlay endpoints
```

Map HTML is **generated server-side** (requires `MAPBOX_TOKEN`). The browser never talks to Mapbox directly for tile logic — it runs the returned HTML in a sandboxed iframe.

### GraphXR 3D/VR (embedded or standalone)

```mermaid
flowchart TB
  subgraph CSPE["CSPE frontend"]
    TM2["TransportMode"]
    Sync["graph3dSync.ts"]
  end

  subgraph BFF2["Product shell"]
    SyncPost["POST /graph3d/sync"]
    SyncGet["GET /graph3d/sync/{client_id}"]
    SessionGet["GET /graph3d/session/{id}"]
    SessionStore["In-memory sessions TTL 30m"]
  end

  subgraph GXR["GraphXR :3000/viewer"]
    VC["ViewerClient.tsx"]
    SceneWeb["GraphSceneWeb"]
    SceneXR["GraphSceneXR (WebXR)"]
    Poll["Poll sync every ~900ms"]
  end

  TM2 --> Sync
  Sync -->|push fingerprint| SyncPost
  SyncPost --> SessionStore
  Sync -->|viewer URL ?session=&sync=&embedded=1| VC
  VC --> SessionGet
  VC --> Poll
  Poll --> SyncGet
  SyncGet -->|fingerprint changed| VC
  VC --> SceneWeb
  VC --> SceneXR
```

**Embedded mode** (`embedded=1` query param): hides GraphXR standalone header; viewer controls stay on the right. CSPE hides Atlas rail and transport HUD when `transportViz === "graph3d"`.

---

## 9. Integration flows

### End-to-end: “Route from A to B”

```mermaid
sequenceDiagram
  participant User
  participant Atlas
  participant Tools
  participant BFF
  participant Shell
  participant UI as TransportMode

  User->>Atlas: natural language route request
  Atlas->>Tools: cspe_compute_route / cspe_search_stops
  Tools->>BFF: POST /transport/route
  BFF-->>Tools: path_ids, legs, meta
  Tools->>BFF: POST /shell/enqueue
  Note over Shell: transport_route_view,<br/>atlas_transport_action
  Shell-->>UI: SSE/poll
  UI->>BFF: POST /transport/map (route overlay)
  UI->>UI: map iframe updates
```

### End-to-end: “Explore restaurants near X”

```mermaid
sequenceDiagram
  participant User
  participant Atlas
  participant Tools
  participant BFF
  participant Shell
  participant UI as TransportMode

  User->>Atlas: explore request
  Atlas->>Tools: cspe_explore_area
  Tools->>BFF: POST /transport/area/explore?sync_ui=true
  BFF->>BFF: poi_index + stop search
  BFF->>Shell: exploration shell commands
  Shell-->>UI: transport_exploration_view
  UI->>BFF: map + exploration overlay
  UI->>UI: iframe markers + chat summary
```

### Agent context loop

```mermaid
flowchart LR
  UI["TransportMode state changes"]
  Sync["AgentContextSync"]
  PATCH["PATCH /api/agent/context"]
  Store["agent_store (in-memory)"]
  Tools["Atlas cspe_get_current_context"]

  UI --> Sync --> PATCH --> Store
  Tools --> Store
```

The BFF keeps a **server-side mirror** of transport focus (graph mode, paths, errors) so Atlas tools can read current UI context without parsing the DOM.

---

## 10. Quest VR mode

Meta Quest browsers require **HTTPS** for WebXR. `-QuestVR` puts a reverse proxy in front of the dev stack and tunnels it with ngrok.

```mermaid
flowchart TB
  Quest["Meta Quest browser<br/>HTTPS ngrok URL"]

  subgraph Proxy["proxy-vr.js :8080"]
    RouteRoot["/ → Vite :5173"]
    RouteViewer["/viewer, /_next → GraphXR :3000"]
    RouteAPI["/api → Product shell :8787"]
    Health["/health"]
  end

  Quest --> Proxy
  RouteRoot --> Vite["React app"]
  RouteViewer --> GXR["GraphXR"]
  RouteAPI --> BFF["FastAPI"]

  subgraph Env["Session env overrides"]
    ViteAPI["VITE_API_BASE=https://ngrok-host"]
    ViteGXR["VITE_GRAPHXR_VIEWER_URL=https://ngrok-host/viewer"]
  end

  Env --> Vite
```

In-headset controls (GraphXR `GraphSceneXR.tsx`): thumbsticks for move/turn, trigger/grip for selection, A/X for menu. On-screen buttons: Reset, Labels, Filters, VR entry.

---

## Quick reference: who talks to whom

| From | To | Protocol |
|------|-----|----------|
| Browser | Vite :5173 | HTTP — SPA assets |
| Browser | Product shell :8787 | HTTP `/api/*` (proxied or direct) |
| Browser | GraphXR :3000 | iframe `/viewer?session=…` |
| Product shell | Atlas :5055 | HTTP `/text`, `/ui`, `/mode` |
| Atlas tools | Product shell :8787 | HTTP transport + shell + agent |
| GraphXR | Product shell :8787 | HTTP session + sync (via `?api=` param) |
| Product shell | Mapbox | Server-side token in `plot_mapbox.py` |
| Product shell | IDFM Navitia | Optional REST (`IDFM_API_KEY`) |

---

## Related docs

- [`docs/PROJECT_FULL_TECHNICAL_OVERVIEW.md`](PROJECT_FULL_TECHNICAL_OVERVIEW.md) — longer narrative overview (may include legacy modes)
- [`docs/LOCAL_PLANNER.md`](LOCAL_PLANNER.md) — Atlas planner pipeline details
- [`run_web_app.ps1`](../run_web_app.ps1) — stack launcher and port comments

---

*Generated from repository inspection. Ports and paths reflect the current tree; adjust if you change launcher scripts or env defaults.*
