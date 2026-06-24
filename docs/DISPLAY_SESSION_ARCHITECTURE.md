# Display Session Architecture

## Why exclusive display modes?

Atlas previously tried to update **2D Mapbox**, **embedded GraphXR**, **shell poll queue**, **chat inline payloads**, and **Quest WebXR** at the same time. Backend success did not guarantee a visible update in the view the user was actually looking at.

The project now uses **one active display mode at a time**. Atlas UI commands target that mode through a central **display session manager**.

## Modes

| Mode | Meaning |
|------|---------|
| `2d` | Normal desktop UI — Mapbox 2D transport map is the primary display |
| `vr_dev` | Desktop VR development viewer — `/vr-viewer?mode=dev&session_id=…` in a separate tab |
| `vr_real` | Meta Quest browser via HTTPS/ngrok/WebXR (same command schema, different runtime) |

## Command targeting

Every batch includes:

```json
{
  "command_id": "...",
  "target": "active_display",
  "source": "atlas_chat",
  "session_id": null,
  "created_at": "2026-06-22T...",
  "commands": [...]
}
```

- **`target: active_display`** (default) — routes to whichever mode is currently active
- **`target: 2d` / `vr_dev` / `vr_real`** — explicit override for debugging or special cases

Commands are **not** broadcast to all views by default.

## Frontend architecture

```
Atlas /api/chat or /api/shell/poll
        ↓
routeUiCommandBatch (2D host)
        ↓
  activeDisplayMode?
   ├─ 2d → applyTransportUiCommand → Zustand → TransportMode map refresh
   └─ vr_dev / vr_real → BroadcastChannel `atlas-display-session`
                              ↓
                         VrDevViewer applies same command applier
                              ↓
                         GraphXR 3D scene (graph3d sync API)
```

Key modules:

- `frontend/src/displaySession/displaySessionStore.ts` — session state
- `frontend/src/displaySession/uiCommandRouter.ts` — targeting + dedupe
- `frontend/src/displaySession/applyTransportCommands.ts` — shared command switch
- `frontend/src/displaySession/broadcastDisplayChannel.ts` — `BroadcastChannel` transport
- `frontend/src/viewers/VrDevViewer.tsx` — dev VR page

## VR dev mode (no Quest required)

1. User asks Atlas: “switch to 3D VR mode” (or command `set_display_mode` / `transport_graph3d_sync`)
2. Host sets `activeDisplayMode = vr_dev`, opens `/vr-viewer?mode=dev&session_id=…`
3. Main UI shows overlay: **3D VR mode in use — dev simulation**
4. Further route/POI commands forward to the VR tab via BroadcastChannel
5. VR tab renders GraphXR iframe + applies the same shell command kinds

**Return to 2D:** overlay button, VR window button, or `return_to_2d` / `set_display_mode` command.

## Voice / microphone

Voice input stays on the **PC 2D shell** for now. Commands route to the active display; Quest-side voice is optional future work.

## Real Quest mode (`vr_real`)

Same session manager, schema, router, and viewer command handling. Runtime differences only:

- Access via ngrok HTTPS (`run_web_app.ps1 -QuestVR`)
- WebXR + Quest controllers
- `mode=real` on `/vr-viewer`

## Fallback: shell poll / SSE

Inline `/api/chat` `ui_commands` remain the primary delivery path. Shell poll/SSE is a **legacy fallback** with deduplication — not the main source of truth.

## Known limitations

- VR dev viewer uses GraphXR + graph3d sync API; polish is dev-grade, not final VR UX
- `atlas_transport_action` with `run=route` is processed on 2D host; VR relies on `transport_route_view` from backend sync
- Session ID is not yet persisted server-side; reconnecting a closed VR tab requires reopening VR mode
- BroadcastChannel requires same origin (works for local dev; Quest uses ngrok same-origin through proxy)

## Logging

Look for `[displaySession]`, `[uiCommandRouter]`, and backend `[UICommand]` lines with `target`, `command_id`, and `session_id`.
