import { ToolRail } from "./ToolRail";
import { AtlasRailPanel } from "./AtlasRailPanel";
import { TransportMode } from "../modes/TransportMode";
import { VisualBoardMode } from "../modes/VisualBoardMode";
import { MemoryMode } from "../modes/MemoryMode";
import { MusicMode } from "../modes/MusicMode";
import { useAppStore } from "../store";

export function AppShell() {
  const mode = useAppStore((s) => s.mode);
  const setMode = useAppStore((s) => s.setMode);

  return (
    <div style={{ display: "flex", height: "100vh", overflow: "hidden" }}>
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
        <AtlasRailPanel />
      </div>
    </div>
  );
}
