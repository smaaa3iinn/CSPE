import { useEffect } from "react";
import { patchAgentContext } from "../api/agentFeedback";
import { useAppStore } from "../store";

/** Keeps /api/agent/context in sync with Zustand UI state for the Atlas planner. */
export function AgentContextSync() {
  const mode = useAppStore((s) => s.mode);
  const memoryProjectId = useAppStore((s) => s.memoryProjectId);
  const graphMode = useAppStore((s) => s.transportGraphMode);
  const useLcc = useAppStore((s) => s.transportUseLcc);
  const pathIds = useAppStore((s) => s.transportPathIds);
  const stationPathIds = useAppStore((s) => s.transportStationPathIds);
  const routeError = useAppStore((s) => s.transportRouteError);
  const routeMeta = useAppStore((s) => s.transportRouteMeta);

  useEffect(() => {
    void patchAgentContext({
      ui_mode: mode,
      memory_project_id: memoryProjectId,
      transport: {
        graph_mode: graphMode,
        use_lcc: useLcc,
        path_ids: pathIds,
        station_path_ids: stationPathIds,
        route_error: routeError,
        route_meta: routeMeta,
      },
    });
  }, [mode, memoryProjectId, graphMode, useLcc, pathIds, stationPathIds, routeError, routeMeta]);

  return null;
}
