import { useEffect, useRef } from "react";
import { patchAgentContext } from "../api/agentFeedback";
import { useDisplaySessionStore } from "../displaySession/displaySessionStore";
import { useAppStore } from "../store";
import { buildAgentUxState, type AgentUxSnapshot } from "../transport/agentUxContext";

/** Keeps /api/agent/context in sync with Zustand UI state for the Atlas planner. */
export function AgentContextSync() {
  const graphMode = useAppStore((s) => s.transportGraphMode);
  const useLcc = useAppStore((s) => s.transportUseLcc);
  const pathIds = useAppStore((s) => s.transportPathIds);
  const stationPathIds = useAppStore((s) => s.transportStationPathIds);
  const routeError = useAppStore((s) => s.transportRouteError);
  const routeMeta = useAppStore((s) => s.transportRouteMeta);
  const transportViz = useAppStore((s) => s.transportViz);
  const selectedStopId = useAppStore((s) => s.transportMapSelectionStopId);
  const selectedStationId = useAppStore((s) => s.transportMapSelectionStationId);
  const chatLoading = useAppStore((s) => s.chatLoading);
  const activeDisplayMode = useDisplaySessionStore((s) => s.activeDisplayMode);

  const prevSnapRef = useRef<AgentUxSnapshot | null>(null);

  useEffect(() => {
    const snap: AgentUxSnapshot = {
      transportViz,
      activeDisplayMode,
      graphMode,
      routeMeta,
      selectedStopId,
      selectedStationId,
      chatLoading,
    };
    const ux = buildAgentUxState(snap, prevSnapRef.current);
    prevSnapRef.current = snap;

    void patchAgentContext({
      ui_mode: "transport",
      ux,
      transport: {
        graph_mode: graphMode,
        use_lcc: useLcc,
        path_ids: pathIds,
        station_path_ids: stationPathIds,
        route_error: routeError,
        route_meta: routeMeta,
        selected_stop_id: selectedStopId,
        selected_station_id: selectedStationId,
      },
    });
  }, [
    graphMode,
    useLcc,
    pathIds,
    stationPathIds,
    routeError,
    routeMeta,
    transportViz,
    selectedStopId,
    selectedStationId,
    chatLoading,
    activeDisplayMode,
  ]);

  return null;
}
