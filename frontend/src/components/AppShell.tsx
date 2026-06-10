import { AtlasRailPanel } from "./AtlasRailPanel";
import { AgentContextSync } from "./AgentContextSync";
import { ShellCommandListener } from "./ShellCommandListener";
import { MapFocusHotkey } from "./MapFocusHotkey";
import { TransportMode } from "../modes/TransportMode";
import { useAppStore } from "../store";

export function AppShell() {
  const mapChromeHidden = useAppStore((s) => s.transportMapChromeHidden);
  const mapFocusActive = mapChromeHidden;

  return (
    <div className={`app-root${mapFocusActive ? " app-root--map-focus" : ""}`}>
      <ShellCommandListener />
      <AgentContextSync />
      <MapFocusHotkey />
      <div className="app-root__body app-root__body--transport-only">
        <div className="app-shell__main">
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
          {!mapFocusActive && <AtlasRailPanel />}
        </div>
      </div>
    </div>
  );
}
