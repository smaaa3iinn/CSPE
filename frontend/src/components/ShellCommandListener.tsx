import { useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import type { StructuredOutput } from "../types/payloads";
import { postAgentEvent } from "../api/agentFeedback";
import { apiUrl } from "../api/config";
import { useAppStore } from "../store";
import type { AtlasTransportActionSpec } from "../transport/atlasTransportTypes";
import { normalizeAtlasTransportSpec, transportActionSpecFingerprint } from "../transport/atlasTransportTypes";

const POLL_MS = 600;
const USE_SHELL_SSE = import.meta.env.VITE_SHELL_SSE === "1";

function enqueueAtlasTransportAction(spec: AtlasTransportActionSpec) {
  const s = useAppStore.getState();
  const fp = transportActionSpecFingerprint(spec);
  const pending = s.atlasTransportAction;
  if (pending && transportActionSpecFingerprint(pending.spec) === fp) return;
  const nextSeq = (pending?.seq ?? 0) + 1;
  // eslint-disable-next-line no-console
  console.info("[atlas_transport] action enqueued", { seq: nextSeq, spec });
  s.setAtlasTransportAction({ seq: nextSeq, spec });
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
    case "atlas_transport_action": {
      const specRaw = raw.spec;
      if (!specRaw || typeof specRaw !== "object" || Array.isArray(specRaw)) break;
      const spec = normalizeAtlasTransportSpec(specRaw as Record<string, unknown>);
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

    const drainCommands = (cmds: unknown[]) => {
      for (const c of cmds) {
        if (c && typeof c === "object" && !Array.isArray(c)) {
          applyOne(c as Record<string, unknown>, navRef.current);
        }
      }
      if (cmds.length > 0) {
        void postAgentEvent("shell.commands_applied", { count: cmds.length });
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
    if (!USE_SHELL_SSE) void tick();

    return () => {
      cancelled = true;
      if (id !== undefined) window.clearInterval(id);
      es?.close();
    };
  }, []);

  return null;
}
