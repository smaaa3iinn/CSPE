import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import type { StructuredOutput } from "../types/payloads";
import { apiUrl } from "../api/config";
import { useAppStore } from "../store";

const POLL_MS = 600;

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
        useAppStore.getState().setTransportGraphMode(gm);
      }
      break;
    }
    case "transport_options": {
      const s = useAppStore.getState();
      if (typeof raw.use_lcc === "boolean") s.setTransportUseLcc(raw.use_lcc);
      const vz = raw.viz;
      if (vz === "geographic" || vz === "network_3d") s.setTransportViz(vz);
      const gv = raw.graph_viz;
      if (gv === "stop" || gv === "station" || gv === "hybrid") s.setTransportGraphViz(gv);
      if (typeof raw.show_transfers === "boolean") s.setTransportShowTransfers(raw.show_transfers);
      break;
    }
    case "transport_route_view": {
      const s = useAppStore.getState();
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
    const tick = async () => {
      if (cancelled) return;
      try {
        const r = await fetch(apiUrl("/api/shell/poll"));
        if (!r.ok) return;
        const data = (await r.json()) as { commands?: unknown[] };
        const cmds = Array.isArray(data.commands) ? data.commands : [];
        for (const c of cmds) {
          if (c && typeof c === "object" && !Array.isArray(c)) {
            applyOne(c as Record<string, unknown>, navRef.current);
          }
        }
      } catch {
        /* offline or API down */
      }
    };
    const id = window.setInterval(() => void tick(), POLL_MS);
    void tick();
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  return null;
}
