import { ToolRail } from "./ToolRail";
import { AtlasRailPanel } from "./AtlasRailPanel";
import { AgentContextSync } from "./AgentContextSync";
import { ShellCommandListener } from "./ShellCommandListener";
import { MapFocusHotkey } from "./MapFocusHotkey";
import { TransportMode } from "../modes/TransportMode";
import { VisualBoardMode } from "../modes/VisualBoardMode";
import { MemoryMode } from "../modes/MemoryMode";
import { MusicMode } from "../modes/MusicMode";
import { useAppStore } from "../store";

export function AppShell() {
  const mode = useAppStore((s) => s.mode);
  const setMode = useAppStore((s) => s.setMode);
  const mapChromeHidden = useAppStore((s) => s.transportMapChromeHidden);
  const mapFocusActive = mode === "transport" && mapChromeHidden;

  return (
    <div className={`app-root${mapFocusActive ? " app-root--map-focus" : ""}`}>
      <ShellCommandListener />
      <AgentContextSync />
      <MapFocusHotkey />
      <div className="app-root__body">
        <ToolRail mode={mode} onMode={setMode} />
        <div className="app-shell__main">
        {/* Keep Transport mounted for the session so the map iframe does not reload when switching modes */}
        <div
          style={{
            flex: 1,
            minHeight: 0,
            display: mode === "transport" ? "flex" : "none",
            flexDirection: "column",
            overflow: "hidden",
          }}
          aria-hidden={mode !== "transport"}
        >
          <TransportMode />
        </div>
        {mode === "visual" && (
          <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", overflow: "hidden" }}>
            <VisualBoardMode />
          </div>
        )}
        {mode === "memory" && (
          <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", overflow: "hidden" }}>
            <MemoryMode />
          </div>
        )}
        {mode === "music" && (
          <div style={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column", overflow: "hidden" }}>
            <MusicMode />
          </div>
        )}
        {!mapFocusActive && <AtlasRailPanel />}
        </div>
      </div>
    </div>
  );
}
