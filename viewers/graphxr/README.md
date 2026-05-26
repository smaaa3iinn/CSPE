# CSPE GraphXR Viewer

Next.js 3D/VR viewer for CSPE transport graphs.

CSPE owns graph data, routing, and session creation. This app only renders a prepared
graph session from the product shell API.

## Run

```powershell
npm install
npm run dev -- -p 3000
```

Open from CSPE using:

```text
http://localhost:3000/viewer?session=<id>&api=http://127.0.0.1:8787
```

The root route redirects to `/viewer`.

## Boundaries

- CSPE backend: routing, graph loading, GraphXR sessions.
- CSPE frontend: main transport UI and embedded iframe.
- GraphXR viewer: Babylon/WebXR rendering only.
