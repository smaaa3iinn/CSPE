import type { DisplayMode } from "../displaySession/uiCommandTypes";

type TransportViz = "geographic" | "network_3d" | "graph3d";
type GraphMode = "all" | "all_mb" | "metro" | "rail" | "tram" | "bus" | "other";

export type AgentUxSnapshot = {
  transportViz: TransportViz;
  activeDisplayMode: DisplayMode;
  graphMode: GraphMode;
  routeMeta: string | null;
  selectedStopId: string | null;
  selectedStationId: string | null;
  chatLoading: boolean;
  fromQuery?: string | null;
  toQuery?: string | null;
};

export function deriveActiveView(viz: TransportViz, displayMode: DisplayMode): string {
  if (displayMode === "vr_real" || displayMode === "vr_dev") return "vr_mode";
  if (viz === "graph3d") return "3d_graph";
  return "2d_map";
}

export function buildAgentUxState(
  snap: AgentUxSnapshot,
  prev: AgentUxSnapshot | null,
): Record<string, string | null> {
  const activeView = deriveActiveView(snap.transportViz, snap.activeDisplayMode);
  const focused =
    snap.selectedStationId?.trim() ||
    snap.selectedStopId?.trim() ||
    null;

  let activeRoute: string | null = null;
  const fromQ = (snap.fromQuery || "").trim();
  const toQ = (snap.toQuery || "").trim();
  if (fromQ && toQ) {
    activeRoute = `${fromQ} -> ${toQ}`;
  } else if (snap.routeMeta?.trim()) {
    activeRoute = snap.routeMeta.trim();
  }

  let lastUiAction: string | null = null;
  if (prev) {
    if (prev.activeDisplayMode !== snap.activeDisplayMode) {
      lastUiAction =
        snap.activeDisplayMode === "vr_dev" || snap.activeDisplayMode === "vr_real"
          ? "activated 3D/VR display mode"
          : snap.activeDisplayMode === "2d"
            ? "returned to 2D map view"
            : `switched display to ${snap.activeDisplayMode}`;
    } else if (prev.transportViz !== snap.transportViz) {
      lastUiAction = `switched map visualization to ${snap.transportViz}`;
    } else if (prev.graphMode !== snap.graphMode) {
      lastUiAction = `switched graph layer to ${snap.graphMode}`;
    } else if (prev.routeMeta !== snap.routeMeta && snap.routeMeta) {
      lastUiAction = `computed route (${snap.routeMeta})`;
    }
  }

  const voiceMode = snap.chatLoading ? "command_active" : "idle";

  return {
    active_view: activeView,
    active_layer: snap.graphMode,
    active_route: activeRoute,
    focused_place: focused,
    last_ui_action: lastUiAction,
    voice_mode: voiceMode,
  };
}
