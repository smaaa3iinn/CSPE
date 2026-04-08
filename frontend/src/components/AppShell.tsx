import { ToolRail } from "./ToolRail";
import { AtlasOverlay } from "./AtlasOverlay";
import { useAppStore } from "../store";
import { TransportMode } from "../modes/TransportMode";
import { KnowledgeMode } from "../modes/KnowledgeMode";
import { VisualBoardMode } from "../modes/VisualBoardMode";
import { MemoryMode } from "../modes/MemoryMode";

export function AppShell() {
  const mode = useAppStore((s) => s.mode);
  const setMode = useAppStore((s) => s.setMode);
  const setAtlasOpen = useAppStore((s) => s.setAtlasOpen);

  return (
    <div style={{ display: "flex", height: "100vh", overflow: "hidden" }}>
      <ToolRail mode={mode} onMode={setMode} />
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        {mode === "transport" && <TransportMode />}
        {mode === "knowledge" && <KnowledgeMode />}
        {mode === "visual" && <VisualBoardMode />}
        {mode === "memory" && <MemoryMode />}
      </div>
      <button
        type="button"
        className="primary"
        onClick={() => setAtlasOpen(true)}
        style={{
          position: "fixed",
          top: 12,
          right: 12,
          zIndex: 1500,
          borderRadius: 999,
          padding: "8px 14px",
          fontSize: 12,
          fontWeight: 600,
        }}
      >
        Atlas
      </button>
      <AtlasOverlay />
    </div>
  );
}
