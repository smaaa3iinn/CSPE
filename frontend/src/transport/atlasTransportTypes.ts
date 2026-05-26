/** Shell command `atlas_transport_action` — partial UI patch + optional trigger (omit = preserve). */

export type TransportGraphModeKey = "all" | "metro" | "rail" | "tram" | "bus" | "other";

export type AtlasTransportRun =
  | "route"
  | "compute"
  | "search_map"
  | "reset_route"
  | "refresh_map"
  | "clear_map_highlight"
  | "none";

export type AtlasTransportActionSpec = {
  open_app_mode?: "transport";
  graph_mode?: TransportGraphModeKey;
  use_lcc?: boolean;
  viz?: "geographic" | "network_3d";
  graph_viz?: "stop" | "station" | "hybrid";
  /** Applied only if `graph_viz` is omitted (maps to station/stop layers). */
  routing_scope?: "station" | "stop";
  show_transfers?: boolean;
  dock_tab?: "route" | "search";
  route_focus?: "start" | "end";
  from_query?: string;
  to_query?: string;
  stop_lookup_query?: string;
  /** Default `none` at apply time if absent. */
  run?: AtlasTransportRun;
};

export type AtlasTransportActionPayload = {
  seq: number;
  spec: AtlasTransportActionSpec;
};

/** Keys considered “explicitly set” for logging (non-undefined spec fields). */
export function specKeysProvided(spec: AtlasTransportActionSpec): string[] {
  const keys = Object.keys(spec) as (keyof AtlasTransportActionSpec)[];
  return keys.filter((k) => spec[k] !== undefined);
}

const GM: TransportGraphModeKey[] = ["all", "metro", "rail", "tram", "bus", "other"];

/** Build a spec from loosely-typed shell JSON; unknown keys ignored. */
export function normalizeAtlasTransportSpec(raw: Record<string, unknown>): AtlasTransportActionSpec {
  const spec: AtlasTransportActionSpec = {};

  if (raw.open_app_mode === "transport") spec.open_app_mode = "transport";
  if (typeof raw.graph_mode === "string" && GM.includes(raw.graph_mode as TransportGraphModeKey)) {
    spec.graph_mode = raw.graph_mode as TransportGraphModeKey;
  }
  if (typeof raw.use_lcc === "boolean") spec.use_lcc = raw.use_lcc;
  if (raw.viz === "geographic" || raw.viz === "network_3d") spec.viz = raw.viz;
  if (raw.graph_viz === "stop" || raw.graph_viz === "station" || raw.graph_viz === "hybrid") {
    spec.graph_viz = raw.graph_viz;
  }
  if (raw.routing_scope === "station" || raw.routing_scope === "stop") {
    spec.routing_scope = raw.routing_scope;
  }
  if (typeof raw.show_transfers === "boolean") spec.show_transfers = raw.show_transfers;
  if (raw.dock_tab === "route" || raw.dock_tab === "search") spec.dock_tab = raw.dock_tab;
  if (raw.route_focus === "start" || raw.route_focus === "end") spec.route_focus = raw.route_focus;
  if (typeof raw.from_query === "string") spec.from_query = raw.from_query;
  if (typeof raw.to_query === "string") spec.to_query = raw.to_query;
  if (typeof raw.stop_lookup_query === "string") spec.stop_lookup_query = raw.stop_lookup_query;
  if (
    raw.run === "route" ||
    raw.run === "compute" ||
    raw.run === "search_map" ||
    raw.run === "reset_route" ||
    raw.run === "refresh_map" ||
    raw.run === "clear_map_highlight" ||
    raw.run === "none"
  ) {
    spec.run = raw.run;
  }

  return spec;
}
