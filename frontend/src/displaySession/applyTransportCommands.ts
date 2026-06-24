import type { NavigateFunction } from "react-router-dom";
import type { StructuredOutput } from "../types/payloads";
import { postShellClientLog } from "../api/client";
import { useAppStore } from "../store";
import type { AtlasTransportActionSpec, TransportExplorationView } from "../transport/atlasTransportTypes";
import { normalizeAtlasTransportSpec, transportActionSpecFingerprint } from "../transport/atlasTransportTypes";
import {
  enableGraph3dLiveSync,
  pushGraph3dViewSync,
  registerGraph3dSyncClientId,
} from "../transport/graph3dSync";
import { commandKind } from "./uiCommandTypes";
import { useDisplaySessionStore } from "./displaySessionStore";

export type TransportCommandContext = {
  navigate?: NavigateFunction;
  /** When false, skip atlas action queue (VR viewer applies graph sync directly). */
  enqueueActions?: boolean;
  /** Push graph3d session after transport state changes. */
  syncGraph3d?: () => Promise<void>;
};

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
  if (pending && transportActionSpecFingerprint(pending.spec) === fp && spec.run !== "exploration_map") {
    return;
  }
  s.enqueueAtlasTransportAction(spec);
}

async function defaultGraph3dSync() {
  enableGraph3dLiveSync();
  await pushGraph3dViewSync(true);
}

/** Apply one legacy shell command to Zustand transport state (2D or VR dev store). */
export async function applyTransportUiCommand(
  raw: Record<string, unknown>,
  ctx: TransportCommandContext = {},
): Promise<boolean> {
  const kind = commandKind(raw);
  const enqueueActions = ctx.enqueueActions !== false;
  const syncGraph3d = ctx.syncGraph3d ?? defaultGraph3dSync;

  switch (kind) {
    case "set_display_mode": {
      const mode = String(raw.mode ?? raw.display_mode ?? "").trim();
      if (mode === "vr_dev" || mode === "3d_vr" || mode === "vr") {
        useDisplaySessionStore.getState().openVrDevSession();
        return true;
      }
      if (mode === "vr_real" || mode === "quest") {
        useDisplaySessionStore.getState().openVrRealSession(
          typeof raw.session_id === "string" ? raw.session_id : undefined,
        );
        return true;
      }
      if (mode === "2d") {
        useDisplaySessionStore.getState().returnTo2d();
        return true;
      }
      return false;
    }
    case "return_to_2d": {
      useDisplaySessionStore.getState().returnTo2d();
      return true;
    }
    case "set_mode": {
      if (raw.mode === "transport") useAppStore.getState().setMode("transport");
      return true;
    }
    case "navigate": {
      if (!ctx.navigate) return false;
      const p = typeof raw.path === "string" ? raw.path : "";
      if (!p.startsWith("/")) return false;
      ctx.navigate(p, { replace: Boolean(raw.replace) });
      return true;
    }
    case "transport_graph_mode": {
      const gm = raw.graph_mode;
      if (gm === "all" || gm === "all_mb" || gm === "metro" || gm === "rail" || gm === "tram" || gm === "bus" || gm === "other") {
        const s = useAppStore.getState();
        if (s.transportGraphMode !== gm) clearTransportRouteState();
        s.setTransportGraphMode(gm);
        if (useDisplaySessionStore.getState().activeDisplayMode !== "2d") {
          await syncGraph3d();
        }
      }
      return true;
    }
    case "transport_options": {
      const s = useAppStore.getState();
      const routeContextChanged =
        (typeof raw.use_lcc === "boolean" && raw.use_lcc !== s.transportUseLcc) ||
        ((raw.graph_viz === "stop" || raw.graph_viz === "station" || raw.graph_viz === "hybrid") &&
          raw.graph_viz !== s.transportGraphViz);
      if (routeContextChanged) clearTransportRouteState();
      if (typeof raw.use_lcc === "boolean") s.setTransportUseLcc(raw.use_lcc);
      const vz = raw.viz;
      if (vz === "geographic" || vz === "network_3d") {
        s.setTransportViz(vz);
      } else if (vz === "graph3d") {
        useDisplaySessionStore.getState().openVrDevSession();
        return true;
      }
      const gv = raw.graph_viz;
      if (gv === "stop" || gv === "station" || gv === "hybrid") s.setTransportGraphViz(gv);
      if (typeof raw.show_transfers === "boolean") s.setTransportShowTransfers(raw.show_transfers);
      if (useDisplaySessionStore.getState().activeDisplayMode !== "2d") {
        await syncGraph3d();
      }
      return true;
    }
    case "transport_exploration_view": {
      clearTransportRouteState();
      useAppStore.getState().setMode("transport");
      const center = raw.center;
      const view: TransportExplorationView = {
        center:
          center && typeof center === "object" && !Array.isArray(center)
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
      if (useDisplaySessionStore.getState().activeDisplayMode === "2d") {
        useAppStore.getState().appendChatExploration(view);
      }
      void postShellClientLog("exploration_view_applied", {
        stop_count: view.nearby_stops?.length ?? 0,
        poi_count: view.nearby_pois?.length ?? 0,
        radius_m: view.radius_m ?? null,
        display_mode: useDisplaySessionStore.getState().activeDisplayMode,
      });
      if (useDisplaySessionStore.getState().activeDisplayMode !== "2d") {
        await syncGraph3d();
      }
      return true;
    }
    case "transport_graph3d_sync": {
      useDisplaySessionStore.getState().openVrDevSession();
      if (typeof raw.sync_client_id === "string" && raw.sync_client_id.trim()) {
        registerGraph3dSyncClientId(raw.sync_client_id);
      }
      if (raw.enabled !== false) enableGraph3dLiveSync();
      return true;
    }
    case "transport_route_view": {
      const s = useAppStore.getState();
      const settingRoute = Array.isArray(raw.path_ids) && raw.path_ids.length > 0;
      if (settingRoute) clearTransportExplorationState();
      const gm = raw.graph_mode;
      if (
        gm === "all" ||
        gm === "all_mb" ||
        gm === "metro" ||
        gm === "rail" ||
        gm === "tram" ||
        gm === "bus" ||
        gm === "other"
      ) {
        s.setTransportGraphMode(gm);
      }
      if (typeof raw.use_lcc === "boolean") {
        s.setTransportUseLcc(raw.use_lcc);
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
      if (useDisplaySessionStore.getState().activeDisplayMode !== "2d") {
        await syncGraph3d();
      }
      return true;
    }
    case "atlas_transport_action": {
      if (!enqueueActions) return false;
      const specRaw = raw.spec;
      if (!specRaw || typeof specRaw !== "object" || Array.isArray(specRaw)) return false;
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
      if (spec.run === "route" || spec.run === "compute") clearTransportExplorationState();
      enqueueAtlasTransportAction(spec);
      return true;
    }
    case "atlas_transport_intent": {
      if (!enqueueActions) return false;
      const from_q = String(raw.from_query ?? "").trim();
      const to_q = String(raw.to_query ?? "").trim();
      if (from_q.length < 1 || to_q.length < 1) return false;
      enqueueAtlasTransportAction({ from_query: from_q, to_query: to_q, run: "route" });
      clearTransportRouteState();
      clearTransportExplorationState();
      return true;
    }
    case "apply_structured_outputs": {
      const outputs = (Array.isArray(raw.outputs) ? raw.outputs : []) as StructuredOutput[];
      const err = typeof raw.error === "string" ? raw.error : null;
      useAppStore.getState().applyChatResponse(outputs, err);
      return true;
    }
    default:
      return false;
  }
}

export async function applyTransportUiCommands(
  commands: unknown[],
  ctx: TransportCommandContext = {},
): Promise<number> {
  let n = 0;
  for (const c of commands) {
    if (!c || typeof c !== "object" || Array.isArray(c)) continue;
    if (await applyTransportUiCommand(c as Record<string, unknown>, ctx)) n += 1;
  }
  return n;
}
