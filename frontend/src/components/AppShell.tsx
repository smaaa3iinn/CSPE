import { AtlasRailPanel } from "./AtlasRailPanel";
import { AgentContextSync } from "./AgentContextSync";
import { DisplaySessionHost } from "./DisplaySessionHost";
import { DisplaySessionOverlay } from "./DisplaySessionOverlay";
import { ShellCommandListener } from "./ShellCommandListener";
import { MapFocusHotkey } from "./MapFocusHotkey";
import { TransportMode } from "../modes/TransportMode";
import { is2dPrimaryDisplay, useDisplaySessionStore } from "../displaySession/displaySessionStore";
import { useAppStore } from "../store";

export function AppShell() {
  const mapChromeHidden = useAppStore((s) => s.transportMapChromeHidden);
  const transportViz = useAppStore((s) => s.transportViz);
  const activeDisplayMode = useDisplaySessionStore((s) => s.activeDisplayMode);
  const graph3dFullscreen = transportViz === "graph3d" && is2dPrimaryDisplay(activeDisplayMode);
  const mapFocusActive = mapChromeHidden && !graph3dFullscreen;
  const atlasHidden = mapFocusActive || graph3dFullscreen;

  return (
    <div
      className={`app-root${mapFocusActive ? " app-root--map-focus" : ""}${
        graph3dFullscreen ? " app-root--graph3d-fullscreen" : ""
      }`}
    >
      <DisplaySessionHost />
      <ShellCommandListener />
      <AgentContextSync />
      <MapFocusHotkey />
      <div className="app-root__body app-root__body--transport-only">
        <div className="app-shell__main" style={{ position: "relative", flex: 1, minHeight: 0 }}>
          <div
            style={{
              flex: 1,
              minHeight: 0,
              display: "flex",
              flexDirection: "column",
              overflow: "hidden",
            }}
          >
            <TransportMode />
          </div>
          <DisplaySessionOverlay />
          {!atlasHidden && <AtlasRailPanel />}
        </div>
      </div>
    </div>
  );
}
