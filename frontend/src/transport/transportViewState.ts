import { useAppStore } from "../store";

/** Shared transport visualization context for map HTML and GraphXR sessions. */
export type TransportViewContext = {
  graphMode: ReturnType<typeof useAppStore.getState>["transportGraphMode"];
  useLcc: boolean;
  viz: "geographic" | "network_3d";
  graphViz: "stop" | "station" | "hybrid";
  pathIds: string[] | null;
  pathStationIds: string[] | null;
  showTransfers: boolean;
  selectedStopId: string | null;
  selectedStationId: string | null;
};

export function readTransportViewContext(): TransportViewContext {
  const s = useAppStore.getState();
  return {
    graphMode: s.transportGraphMode,
    useLcc: s.transportUseLcc,
    viz: s.transportViz,
    graphViz: s.transportGraphViz,
    pathIds: s.transportPathIds,
    pathStationIds: s.transportStationPathIds,
    showTransfers: s.transportShowTransfers,
    selectedStopId: s.transportMapSelectionStopId,
    selectedStationId: s.transportMapSelectionStationId,
  };
}

export function transportViewFingerprint(ctx: TransportViewContext): string {
  return JSON.stringify({
    mode: ctx.graphMode,
    use_lcc: ctx.useLcc,
    viz: ctx.viz,
    graph_viz: ctx.graphViz,
    path_stop_ids: ctx.pathIds ?? [],
    path_station_ids: ctx.pathStationIds ?? [],
    show_transfers: ctx.showTransfers,
    selected_stop_id: ctx.selectedStopId,
    selected_station_id: ctx.selectedStationId,
    exploration_seq: useAppStore.getState().transportExplorationSeq,
  });
}

/** Base map state only (no exploration overlay — patched incrementally on the live map). */
export function transportBaseViewFingerprint(ctx: TransportViewContext): string {
  return JSON.stringify({
    mode: ctx.graphMode,
    use_lcc: ctx.useLcc,
    viz: ctx.viz,
    graph_viz: ctx.graphViz,
    path_stop_ids: ctx.pathIds ?? [],
    path_station_ids: ctx.pathStationIds ?? [],
    show_transfers: ctx.showTransfers,
    selected_stop_id: ctx.selectedStopId,
    selected_station_id: ctx.selectedStationId,
  });
}

export function buildTransportMapBody(
  ctx: TransportViewContext,
  overrides?: { selectedStopId?: string | null; selectedStationId?: string | null },
): Record<string, unknown> {
  const selStop =
    overrides && "selectedStopId" in overrides
      ? overrides.selectedStopId ?? null
      : ctx.selectedStopId;
  const selStation =
    overrides && "selectedStationId" in overrides
      ? overrides.selectedStationId ?? null
      : ctx.selectedStationId;

  const mapBody: Record<string, unknown> = {
    mode: ctx.graphMode,
    use_lcc: ctx.useLcc,
    viz_mode: ctx.viz,
    graph_viz_mode: ctx.graphViz,
    path_stop_ids: ctx.pathIds,
    show_transfers: ctx.showTransfers,
  };

  if (
    (ctx.graphViz === "station" || ctx.graphViz === "hybrid") &&
    ctx.pathStationIds &&
    ctx.pathStationIds.length > 0
  ) {
    mapBody.path_station_ids = ctx.pathStationIds;
  }
  if (selStation && ctx.graphViz !== "stop") {
    mapBody.selected_station_id = selStation;
  } else if (selStop) {
    mapBody.selected_stop_id = selStop;
  }

  const exp = useAppStore.getState().transportExploration;
  const hasOverlay = Boolean(
    exp?.center || exp?.nearby_stops?.length || exp?.nearby_pois?.length,
  );
  if (hasOverlay) {
    mapBody.exploration_overlay = {
      center: exp?.center,
      radius_m: exp?.radius_m,
      nearby_stops: exp?.nearby_stops ?? [],
      nearby_pois: exp?.nearby_pois ?? [],
      counts: exp?.counts,
    };
    if (exp?.radius_m) {
      mapBody.poi_radius_m = Math.min(Math.max(exp.radius_m, 100), 5000);
    }
  }

  return mapBody;
}

export function buildTransportExplorationOverlayBody(): Record<string, unknown> | null {
  const exp = useAppStore.getState().transportExploration;
  const hasOverlay = Boolean(
    exp?.center || exp?.nearby_stops?.length || exp?.nearby_pois?.length,
  );
  if (!hasOverlay) return null;
  return {
    center: exp?.center,
    radius_m: exp?.radius_m,
    nearby_stops: exp?.nearby_stops ?? [],
    nearby_pois: exp?.nearby_pois ?? [],
    counts: exp?.counts,
  };
}

/** Map HTML request body without exploration overlay (layers applied via postMessage). */
export function buildTransportBaseMapBody(
  ctx: TransportViewContext,
  overrides?: { selectedStopId?: string | null; selectedStationId?: string | null },
): Record<string, unknown> {
  const body = buildTransportMapBody(ctx, overrides);
  delete body.exploration_overlay;
  delete body.poi_radius_m;
  return body;
}

export function buildGraph3DSessionBody(ctx: TransportViewContext): Record<string, unknown> {
  return {
    mode: ctx.graphMode,
    use_lcc: ctx.useLcc,
    graph_viz_mode: ctx.graphViz,
    path_stop_ids: ctx.pathIds ?? [],
    path_station_ids: ctx.pathStationIds ?? [],
    selected_stop_id: ctx.selectedStopId,
    selected_station_id: ctx.selectedStationId,
  };
}
