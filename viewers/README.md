# CSPE Viewers

Standalone visualization apps used by the CSPE product shell.

## `graphxr`

Next.js/Babylon/WebXR viewer for CSPE transport graphs.

Boundaries:

- CSPE backend owns graph data, route calculation, and viewer sessions.
- CSPE frontend embeds the viewer in the transport screen.
- GraphXR only renders prepared graph session payloads.

Run locally:

```powershell
cd viewers\graphxr
npm install
npm run dev -- -p 3000
```
