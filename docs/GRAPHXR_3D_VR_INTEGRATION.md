# CSPE 3D/VR GraphXR Integration

This document explains the 3D/VR graph feature added to CSPE, from beginner level to the main technical details.

## Short Version

CSPE already calculates transport routes and displays maps with Mapbox.

GraphXR is a separate 3D/VR viewer that displays the CSPE transport graph as balls and lines:

- balls = stations or stops
- lines = graph connections between them
- orange balls/lines = the generated route, when a route exists

The feature works like this:

1. CSPE loads the transport graph.
2. The user chooses a transport mode, such as `metro`, `bus`, or `all`.
3. The user clicks `3D/VR graph`.
4. CSPE creates a temporary graph viewer session.
5. GraphXR opens in a separate browser window.
6. GraphXR fetches the prepared graph session from CSPE and renders it in 3D.
7. The user can stay in desktop 3D mode or press `VR` to enter headset/WebXR mode.

## Main Project Pieces

### CSPE Backend

Location:

```text
backend/product_shell/
```

The backend is the Python API. It owns:

- loading transport graph data
- calculating routes
- preparing Mapbox views
- preparing GraphXR 3D/VR sessions

Important files:

```text
backend/product_shell/transport_engine.py
backend/product_shell/routers/transport.py
backend/product_shell/schemas.py
```

### CSPE Frontend

Location:

```text
frontend/
```

The frontend is the main CSPE user interface. It owns:

- the transport screen
- Mapbox visualization buttons
- route inputs
- the `3D/VR graph` button

Important files:

```text
frontend/src/modes/TransportMode.tsx
frontend/src/api/client.ts
frontend/src/api/config.ts
```

### GraphXR Viewer

Location:

```text
viewers/graphxr/
```

GraphXR is the cleaned 3D/VR viewer app. It owns only rendering.

It does not calculate routes. It does not build the CSPE graph. It receives a prepared graph session from CSPE and displays it.

Important files:

```text
viewers/graphxr/app/viewer/page.tsx
viewers/graphxr/app/viewer/ViewerClient.tsx
viewers/graphxr/app/components/3DandXRComponents/Graph/GraphSceneWeb.tsx
viewers/graphxr/app/components/3DandXRComponents/Graph/GraphSceneXR.tsx
viewers/graphxr/app/components/3DandXRComponents/utils/GraphRenderer.ts
```

## Technologies Used

### Python

Python is used for the CSPE backend.

It loads transport graph data, calculates routes, and prepares graph payloads.

### FastAPI

FastAPI is the Python web API framework used by CSPE.

An API framework is a tool that lets the frontend call backend functions through URLs.

Example:

```text
POST /api/transport/graph3d/session
```

That endpoint creates a temporary GraphXR session.

### NetworkX

NetworkX is a Python graph library.

A graph is a data structure made of:

- nodes: stations/stops
- edges: connections between them

CSPE uses graph data for transport routing.

### React

React is the JavaScript UI framework used by the CSPE frontend.

It builds the interactive interface: buttons, forms, panels, and modes.

### Vite

Vite runs the CSPE frontend during development.

Default CSPE frontend URL:

```text
http://localhost:5173
```

### Next.js

Next.js runs the GraphXR viewer app.

Default GraphXR URL:

```text
http://localhost:3000/viewer
```

### Babylon.js

Babylon.js is the 3D engine used by GraphXR.

A 3D engine draws 3D objects in the browser, such as:

- spheres for stations
- lines for edges
- cameras
- lights
- VR headset support

### WebXR

WebXR is the browser technology for VR/AR devices.

GraphXR starts in normal desktop 3D mode. When the user presses `VR`, it asks the browser to start a WebXR session.

## How The Flow Works

### Without A Route

The user can open the 3D/VR graph without generating a path.

Flow:

```text
User clicks 3D/VR graph
CSPE creates GraphXR session
GraphXR opens in new window
GraphXR shows full graph
No route is highlighted
```

### With A Route

If the user generated a path first, the path is highlighted.

Flow:

```text
User computes route
CSPE stores route path ids
User clicks 3D/VR graph
CSPE creates GraphXR session with route ids
GraphXR opens in new window
GraphXR shows full graph
Route nodes and edges are orange
```

## Important API Endpoints

### Create 3D/VR Graph Session

```text
POST /api/transport/graph3d/session
```

This creates a temporary graph payload for GraphXR.

The request includes:

```json
{
  "mode": "metro",
  "use_lcc": false,
  "graph_viz_mode": "station",
  "path_stop_ids": [],
  "path_station_ids": []
}
```

Meaning:

- `mode`: transport mode, such as `metro`, `bus`, `rail`, `tram`, or `all`
- `use_lcc`: whether to use the largest connected component only
- `graph_viz_mode`: whether to show stop graph or station graph
- `path_stop_ids`: route stop IDs, if a route exists
- `path_station_ids`: route station IDs, if a route exists

The response includes:

```json
{
  "session_id": "...",
  "graph_url": "/api/transport/graph3d/session/...",
  "expires_in_s": 1800,
  "metadata": {}
}
```

### Read 3D/VR Graph Session

```text
GET /api/transport/graph3d/session/{session_id}
```

GraphXR calls this endpoint to get the prepared graph data.

## Graph Data Shape

GraphXR expects data like this:

```json
{
  "graph_data": {
    "nodes": [
      {
        "id": "station-id",
        "label": "Station Name",
        "x": 10,
        "y": 0,
        "z": -20,
        "color": "#38bdf8"
      }
    ],
    "edges": [
      {
        "source": "station-a",
        "target": "station-b",
        "color": "#38bdf8"
      }
    ]
  }
}
```

Meaning:

- `x`, `y`, `z`: 3D position
- `color`: display color
- `source`: starting node of an edge
- `target`: ending node of an edge

## Desktop 3D Mode Vs VR Mode

### Desktop 3D Mode

This is the default.

The graph appears on a normal screen. The user moves with mouse or trackpad.

### VR Mode

This starts only when the user presses the `VR` button inside GraphXR.

VR mode uses WebXR. If the browser and headset support it, the user can explore the graph in an immersive headset.

Both modes use the same graph data. The difference is only how the user views and controls it.

## Transport Mode Layers

When CSPE mode is `all`, GraphXR separates transport modes by height.

Current layer heights:

```text
bus    y = -960
tram   y = -480
rail   y =    0
metro  y =  480
other  y =  960
multi  y = 1440
```

This means bus, tram, rail, and metro appear as different flat vertical layers.

Current colors:

```text
bus    green   #22c55e
tram   purple  #a855f7
rail   amber   #f59e0b
metro  blue    #38bdf8
other  gray    #94a3b8
multi  pink    #f472b6
route  orange  #f97316
```

Route color overrides the transport mode color.

## Performance Work Already Added

### Backend Mapbox Cache

CSPE caches generated Mapbox HTML views.

This helps when the same heavy view is requested again, such as:

```text
mode = bus
graph layer = station
visualization = geographic
```

The cache stores the generated HTML, including the graph overlay payload.

It does not cache Mapbox basemap tiles.

### GraphXR Session Reuse

CSPE frontend keeps a small cache of recently opened GraphXR session URLs.

If the same settings are used again, it can reuse the previous session URL.

### Large Graph Rendering

GraphXR detects large graphs and switches to a cheaper rendering path.

For large graphs:

- edges are drawn as lightweight lines
- node spheres use lower detail
- expensive hover/click handlers are reduced

This improves movement smoothness.

## Current Limitations

### Huge Graphs Are Still Heavy

`ALL` and `bus` can contain many thousands of stations and edges.

Even with caching, drawing everything can still be expensive.

### Cache Helps Repeated Loads, Not First Load

The first time a heavy view is generated, it still takes time.

Caching helps the second and later loads.

### Large Graph Interaction Is Reduced

For performance, large graphs may not support detailed hover/click behavior on every node and edge.

Smaller graphs keep richer interactions.

## Recommended Future Improvements

### Prebuilt Graph Assets

Instead of building graph overlays on demand, generate them once into files.

Example:

```text
data/derived/product_shell/graph_assets/
  all_station.json
  bus_station.json
  metro_station.json
```

This would make the backend much faster.

### Vector Tiles For Mapbox

For Mapbox, the best long-term solution is vector tiles.

Vector tiles mean the browser loads only the visible part of the graph instead of the whole graph at once.

This is the strongest improvement for heavy Mapbox views.

### Lazy Loading 3D/VR Layers

GraphXR could load transport layers one by one.

Example:

```text
load metro first
load rail/tram second
load bus only if user enables it
```

This would make `all` mode feel much smoother.

### Web Workers

A Web Worker is a background JavaScript thread.

GraphXR could parse large graph data in a worker so the UI does not freeze.

## How To Run

Start CSPE:

```powershell
cd C:\Users\LEGION\Desktop\CSPE
.\run_web_app.ps1
```

Start GraphXR:

```powershell
cd C:\Users\LEGION\Desktop\CSPE\viewers\graphxr
npm run dev -- -p 3000
```

Open CSPE:

```text
http://localhost:5173
```

Then:

1. Open the transport mode.
2. Choose graph settings.
3. Optionally generate a route.
4. Click `3D/VR graph`.
5. GraphXR opens in a new browser window.

## Ownership Rule

The clean architecture is:

```text
CSPE backend = graph data, routes, sessions
CSPE frontend = main product UI
GraphXR viewer = 3D/VR rendering only
```

This keeps the 3D/VR viewer separate, but still integrated into CSPE.
