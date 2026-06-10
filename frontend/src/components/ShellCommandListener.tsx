import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import type { StructuredOutput } from "../types/payloads";
import { postAgentEvent } from "../api/agentFeedback";
import { postShellClientLog } from "../api/client";
import { apiUrl } from "../api/config";
import { useAppStore } from "../store";
import type { AtlasTransportActionSpec, TransportExplorationView } from "../transport/atlasTransportTypes";
import { normalizeAtlasTransportSpec, transportActionSpecFingerprint } from "../transport/atlasTransportTypes";
import {
  enableGraph3dLiveSync,
  registerGraph3dSyncClientId,
} from "../transport/graph3dSync";

const POLL_MS = 300;
const POLL_BACKUP_MS = 2000;
const USE_SHELL_SSE = import.meta.env.VITE_SHELL_SSE !== "0";
const MAX_APPLIED_SHELL_SIGS = 512;

function shellCommandSignature(raw: Record<string, unknown>): string {
  return JSON.stringify(raw);
}

function clearTransportRouteState() {
  const s = useAppStore.getState();
  s.setTransportPathIds(null);
  s.setTransportStationPathIds(null);
  s.setTransportRouteLegs(null);
  s.setTransportRouteMeta(null);
  s.setTransportRouteError(null);
}

function clearTransportExplorationState() {
  useAppStore.getState().setTransportExploration(null);
}

function enqueueAtlasTransportAction(spec: AtlasTransportActionSpec) {
  const s = useAppStore.getState();
  const fp = transportActionSpecFingerprint(spec);
  const pending = s.atlasTransportActions[s.atlasTransportActions.length - 1];
  // Same center can repeat across follow-up explore turns (stops → POIs → filter).
  if (pending && transportActionSpecFingerprint(pending.spec) === fp && spec.run !== "exploration_map") {
    return;
  }
  const payload = s.enqueueAtlasTransportAction(spec);
  // eslint-disable-next-line no-console
  console.info("[atlas_transport] action enqueued", { seq: payload.seq, spec });
}

function applyOne(raw: Record<string, unknown>, navigate: ReturnType<typeof useNavigate>) {
  const kind = raw.kind;
  switch (kind) {
    case "set_mode": {
      const m = raw.mode;
      if (m === "transport" || m === "visual" || m === "memory" || m === "music") {
        useAppStore.getState().setMode(m);
      }
      break;
    }
    case "navigate": {
      const p = typeof raw.path === "string" ? raw.path : "";
      if (!p.startsWith("/")) return;
      navigate(p, { replace: Boolean(raw.replace) });
      break;
    }
    case "transport_graph_mode": {
      const gm = raw.graph_mode;
      if (gm === "all" || gm === "metro" || gm === "rail" || gm === "tram" || gm === "bus" || gm === "other") {
        const s = useAppStore.getState();
        if (s.transportGraphMode !== gm) {
          clearTransportRouteState();
        }
        s.setTransportGraphMode(gm);
      }
      break;
    }
    case "transport_options": {
      const s = useAppStore.getState();
      const routeContextChanged =
        (typeof raw.use_lcc === "boolean" && raw.use_lcc !== s.transportUseLcc) ||
        ((raw.graph_viz === "stop" || raw.graph_viz === "station" || raw.graph_viz === "hybrid") &&
          raw.graph_viz !== s.transportGraphViz);
      if (routeContextChanged) {
        clearTransportRouteState();
      }
      if (typeof raw.use_lcc === "boolean") s.setTransportUseLcc(raw.use_lcc);
      const vz = raw.viz;
      if (vz === "geographic" || vz === "network_3d" || vz === "graph3d") {
        s.setTransportViz(vz);
      }
      const gv = raw.graph_viz;
      if (gv === "stop" || gv === "station" || gv === "hybrid") s.setTransportGraphViz(gv);
      if (typeof raw.show_transfers === "boolean") s.setTransportShowTransfers(raw.show_transfers);
      break;
    }
    case "transport_exploration_view": {
      clearTransportRouteState();
      useAppStore.getState().setMode("transport");
      const center = raw.center;
      const view: TransportExplorationView = {
        center: center && typeof center === "object" && !Array.isArray(center)
          ? (center as Record<string, unknown>)
          : undefined,
        radius_m: typeof raw.radius_m === "number" ? raw.radius_m : undefined,
        counts:
          raw.counts && typeof raw.counts === "object" && !Array.isArray(raw.counts)
            ? (raw.counts as TransportExplorationView["counts"])
            : undefined,
        summary: typeof raw.summary === "string" ? raw.summary : undefined,
        nearby_stops: Array.isArray(raw.nearby_stops)
          ? (raw.nearby_stops as Array<Record<string, unknown>>)
          : [],
        nearby_pois: Array.isArray(raw.nearby_pois)
          ? (raw.nearby_pois as Array<Record<string, unknown>>)
          : [],
      };
      useAppStore.getState().setTransportExploration(view);
      useAppStore.getState().appendChatExploration(view);
      void postShellClientLog("exploration_view_applied", {
        stop_count: view.nearby_stops?.length ?? 0,
        poi_count: view.nearby_pois?.length ?? 0,
        radius_m: view.radius_m ?? null,
        exploration_seq: useAppStore.getState().transportExplorationSeq,
        summary_len: view.summary?.length ?? 0,
      });
      break;
    }
    case "transport_graph3d_sync": {
      const s = useAppStore.getState();
      s.setMode("transport");
      s.setTransportViz("graph3d");
      if (typeof raw.sync_client_id === "string" && raw.sync_client_id.trim()) {
        registerGraph3dSyncClientId(raw.sync_client_id);
      }
      if (raw.enabled !== false) {
        enableGraph3dLiveSync();
      }
      break;
    }
    case "transport_route_view": {
      const s = useAppStore.getState();
      const settingRoute = Array.isArray(raw.path_ids) && raw.path_ids.length > 0;
      if (settingRoute) {
        clearTransportExplorationState();
      }
      if (raw.clear_paths === true) {
        s.setTransportPathIds(null);
        s.setTransportStationPathIds(null);
      }
      if (Array.isArray(raw.path_ids)) {
        s.setTransportPathIds(raw.path_ids.map(String));
      } else if (raw.path_ids === null) {
        s.setTransportPathIds(null);
      }
      if (Array.isArray(raw.station_path_ids)) {
        s.setTransportStationPathIds(raw.station_path_ids.map(String));
      } else if (raw.station_path_ids === null) {
        s.setTransportStationPathIds(null);
      }
      if ("route_error" in raw) {
        s.setTransportRouteError(raw.route_error === null ? null : String(raw.route_error));
      }
      if ("route_meta" in raw) {
        s.setTransportRouteMeta(raw.route_meta === null ? null : String(raw.route_meta));
      }
      if (Array.isArray(raw.route_legs)) {
        s.setTransportRouteLegs(raw.route_legs as Parameters<typeof s.setTransportRouteLegs>[0]);
      } else if (raw.route_legs === null || raw.clear_paths === true) {
        s.setTransportRouteLegs(null);
      }
      break;
    }
    case "atlas_transport_action": {
      const specRaw = raw.spec;
      if (!specRaw || typeof specRaw !== "object" || Array.isArray(specRaw)) break;
      const spec = normalizeAtlasTransportSpec(specRaw as Record<string, unknown>);
      if (
        spec.run === "route" ||
        spec.run === "compute" ||
        spec.graph_mode !== undefined ||
        spec.use_lcc !== undefined ||
        spec.graph_viz !== undefined ||
        spec.routing_scope !== undefined
      ) {
        clearTransportRouteState();
      }
      if (spec.run === "route" || spec.run === "compute") {
        clearTransportExplorationState();
      }
      enqueueAtlasTransportAction(spec);
      break;
    }
    /** @deprecated Use atlas_transport_action; legacy keeps route-only without overwriting graph/LCC. */
    case "atlas_transport_intent": {
      const from_q = String(raw.from_query ?? "").trim();
      const to_q = String(raw.to_query ?? "").trim();
      if (from_q.length < 1 || to_q.length < 1) break;
      enqueueAtlasTransportAction({
        from_query: from_q,
        to_query: to_q,
        run: "route",
      });
      clearTransportRouteState();
      clearTransportExplorationState();
      break;
    }
    case "memory_project": {
      const id = raw.project_id;
      useAppStore.getState().setMemoryProjectId(id === null || id === undefined ? null : String(id));
      break;
    }
    case "apply_structured_outputs": {
      const outputs = (Array.isArray(raw.outputs) ? raw.outputs : []) as StructuredOutput[];
      const err = typeof raw.error === "string" ? raw.error : null;
      useAppStore.getState().applyChatResponse(outputs, err);
      break;
    }
    default:
      break;
  }
}

/**
 * Drains /api/shell/poll and applies Atlas-issued UI commands to the Zustand shell.
 */
export function ShellCommandListener() {
  const navigate = useNavigate();
  const navRef = useRef(navigate);
  navRef.current = navigate;

  useEffect(() => {
    let cancelled = false;
    const applied = new Set<string>();
    const appliedOrder: string[] = [];

    const rememberApplied = (sig: string) => {
      if (applied.has(sig)) return false;
      applied.add(sig);
      appliedOrder.push(sig);
      if (appliedOrder.length > MAX_APPLIED_SHELL_SIGS) {
        const drop = appliedOrder.shift();
        if (drop) applied.delete(drop);
      }
      return true;
    };

    const drainCommands = (cmds: unknown[]) => {
      let appliedCount = 0;
      for (const c of cmds) {
        if (!c || typeof c !== "object" || Array.isArray(c)) continue;
        const raw = c as Record<string, unknown>;
        const sig = shellCommandSignature(raw);
        if (!rememberApplied(sig)) continue;
        applyOne(raw, navRef.current);
        appliedCount += 1;
      }
      if (appliedCount > 0) {
        void postAgentEvent("shell.commands_applied", { count: appliedCount });
      }
    };

    const tick = async () => {
      if (cancelled) return;
      try {
        const r = await fetch(apiUrl("/api/shell/poll"));
        if (!r.ok) return;
        const data = (await r.json()) as { commands?: unknown[] };
        const cmds = Array.isArray(data.commands) ? data.commands : [];
        drainCommands(cmds);
      } catch {
        /* offline or API down */
      }
    };

    let es: EventSource | null = null;
    if (USE_SHELL_SSE) {
      try {
        es = new EventSource(apiUrl("/api/shell/stream"));
        es.addEventListener("commands", (ev) => {
          if (cancelled) return;
          try {
            const data = JSON.parse((ev as MessageEvent).data) as { commands?: unknown[] };
            drainCommands(Array.isArray(data.commands) ? data.commands : []);
          } catch {
            /* bad payload */
          }
        });
      } catch {
        /* EventSource unsupported */
      }
    }

    const id = USE_SHELL_SSE ? undefined : window.setInterval(() => void tick(), POLL_MS);
    const backupId = USE_SHELL_SSE
      ? window.setInterval(() => void tick(), POLL_BACKUP_MS)
      : undefined;
    if (!USE_SHELL_SSE) void tick();
    else void tick();

    return () => {
      cancelled = true;
      if (id !== undefined) window.clearInterval(id);
      if (backupId !== undefined) window.clearInterval(backupId);
      es?.close();
    };
  }, []);

  return null;
}
