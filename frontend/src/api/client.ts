import type { StructuredOutput } from "../types/payloads";
import { apiUrl } from "./config";

export async function postAtlasInputMode(mode: "text" | "voice"): Promise<void> {
  const r = await fetch(apiUrl("/api/atlas/input-mode"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode }),
  });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(t || `atlas input-mode ${r.status}`);
  }
}

export async function fetchAtlasUi(): Promise<{
  ui: Record<string, unknown>;
  structured_outputs: StructuredOutput[];
}> {
  const r = await fetch(apiUrl("/api/atlas/ui"));
  if (!r.ok) throw new Error(`atlas ui ${r.status}`);
  return r.json() as Promise<{ ui: Record<string, unknown>; structured_outputs: StructuredOutput[] }>;
}

export async function postChat(message: string): Promise<{
  structured_outputs: StructuredOutput[];
  error: string | null;
  ui_commands: {
    command_id: string;
    commands: unknown[];
    target?: "active_display" | "2d" | "vr_dev" | "vr_real";
    session_id?: string | null;
    source?: string;
    created_at?: string | null;
  } | null;
  ui_sync: "inline" | "queued" | "none";
}> {
  const r = await fetch(apiUrl("/api/chat"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
  if (!r.ok) throw new Error(`chat ${r.status}`);
  const data = (await r.json()) as {
    structured_outputs?: unknown[];
    error?: string | null;
    ui_commands?: {
      command_id: string;
      commands: unknown[];
      target?: "active_display" | "2d" | "vr_dev" | "vr_real";
      session_id?: string | null;
      source?: string;
      created_at?: string | null;
    } | null;
    ui_sync?: "inline" | "queued" | "none";
  };
  return {
    structured_outputs: (data.structured_outputs ?? []) as StructuredOutput[],
    error: data.error ?? null,
    ui_commands: data.ui_commands ?? null,
    ui_sync: data.ui_sync ?? "none",
  };
}

export async function postTransportMap(body: Record<string, unknown>): Promise<{ html: string }> {
  const r = await fetch(apiUrl("/api/transport/map"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const t = await r.text();
    let msg: string | null = null;
    try {
      const j = JSON.parse(t) as { detail?: unknown };
      const d = j.detail;
      if (typeof d === "string") msg = d;
      else if (Array.isArray(d))
        msg = d.map((x) => (typeof x === "object" && x && "msg" in x ? String((x as { msg: string }).msg) : String(x))).join("; ");
    } catch {
      /* not JSON */
    }
    throw new Error(msg || t || `map ${r.status}`);
  }
  return r.json();
}

export async function postTransportExplorationOverlay(body: {
  exploration_overlay: Record<string, unknown> | null;
}): Promise<{
  exploration: Record<string, unknown>;
  view: { lat: number; lon: number; zoom: number } | null;
}> {
  const r = await fetch(apiUrl("/api/transport/map/exploration-overlay"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(t || `exploration overlay ${r.status}`);
  }
  return r.json();
}

export async function postTransportRouteOverlay(body: {
  route_overlay: Record<string, unknown> | null;
}): Promise<{
  route: Record<string, unknown>;
  view: { lat: number; lon: number; zoom: number } | null;
}> {
  const r = await fetch(apiUrl("/api/transport/map/route-overlay"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(t || `route overlay ${r.status}`);
  }
  return r.json();
}

export async function postTransportGraph3DSession(body: Record<string, unknown>): Promise<{
  session_id: string;
  graph_url: string;
  expires_in_s: number;
  metadata: Record<string, unknown>;
}> {
  const r = await fetch(apiUrl("/api/transport/graph3d/session"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(t || `graph3d session ${r.status}`);
  }
  return r.json();
}

export async function postTransportGraph3DSync(body: Record<string, unknown>): Promise<{
  session_id: string;
  fingerprint: string;
  expires_in_s: number;
}> {
  const r = await fetch(apiUrl("/api/transport/graph3d/sync"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) {
    const t = await r.text();
    throw new Error(t || `graph3d sync ${r.status}`);
  }
  return r.json();
}

export async function getTransportGraph3DSync(
  clientId: string,
  fingerprint?: string | null,
): Promise<{
  changed: boolean;
  session_id?: string | null;
  fingerprint?: string | null;
}> {
  const q = new URLSearchParams();
  if (fingerprint) q.set("fingerprint", fingerprint);
  const suffix = q.toString() ? `?${q.toString()}` : "";
  const r = await fetch(apiUrl(`/api/transport/graph3d/sync/${encodeURIComponent(clientId)}${suffix}`));
  if (!r.ok) {
    const t = await r.text();
    throw new Error(t || `graph3d sync peek ${r.status}`);
  }
  return r.json();
}

export async function getTransportStats(mode: string, useLcc: boolean) {
  const q = new URLSearchParams({ mode, use_lcc: String(useLcc) });
  const r = await fetch(apiUrl(`/api/transport/stats?${q}`));
  if (!r.ok) throw new Error(`stats ${r.status}`);
  return r.json() as Promise<{ nodes: number; edges: number }>;
}

export type TransportSearchMatch = {
  stop_id: string | null;
  stop_name?: string;
  line?: string | null;
  station_id?: string;
  station_name?: string;
  stop_ids?: string[];
};

export async function searchStops(
  q: string,
  mode: string,
  useLcc: boolean,
  stationFirst = false
) {
  const params = new URLSearchParams({
    q,
    mode,
    use_lcc: String(useLcc),
    limit: "40",
    station_first: String(stationFirst),
  });
  const r = await fetch(apiUrl(`/api/transport/stops/search?${params}`));
  if (!r.ok) throw new Error(`stops ${r.status}`);
  return r.json() as Promise<{ matches: TransportSearchMatch[] }>;
}

export async function postRoute(
  mode: string,
  useLcc: boolean,
  endpoints:
    | { kind: "stop"; from_stop_id: string; to_stop_id: string }
    | { kind: "station"; from_station_id: string; to_station_id: string }
) {
  const body =
    endpoints.kind === "stop"
      ? { mode, use_lcc: useLcc, from_stop_id: endpoints.from_stop_id, to_stop_id: endpoints.to_stop_id }
      : {
          mode,
          use_lcc: useLcc,
          from_station_id: endpoints.from_station_id,
          to_station_id: endpoints.to_station_id,
        };
  const r = await fetch(apiUrl("/api/transport/route"), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`route ${r.status}`);
  return r.json() as Promise<{
    ok: boolean;
    routing_scope?: "stop" | "station";
    path: string[] | null;
    station_path?: string[] | null;
    station_names?: string[] | null;
    path_legs?: TransportRouteLeg[] | null;
    path_summary?: string[] | null;
    result: { distance_m?: number; time_s?: number; transfers?: number } | null;
    detail?: { entry_stop_id?: string | null; exit_stop_id?: string | null } | null;
    error: { message: string; details?: string[] } | null;
  }>;
}

export type TransportRouteLeg = {
  kind: "ride" | "transfer";
  mode: string;
  line_label: string;
  color: string;
  summary: string;
  stops: {
    stop_id: string;
    stop_name: string;
    station_id?: string | null;
    station_name?: string | null;
  }[];
  distance_m?: number | null;
  time_s?: number | null;
};

/** Structured logs for Atlas-driven transport (see logs/activity.log on the API host). */
export async function postShellClientLog(event: string, data: Record<string, unknown>): Promise<void> {
  try {
    await fetch(apiUrl("/api/shell/client-log"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ event, data }),
    });
  } catch {
    /* offline */
  }
}
