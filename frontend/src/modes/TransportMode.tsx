import { useCallback, useEffect, useRef, useState } from "react";
import {
  getTransportStats,
  postTransportGraph3DSession,
  postRoute,
  postShellClientLog,
  postTransportMap,
  searchStops,
  type TransportSearchMatch,
} from "../api/client";
import { postAgentEvent } from "../api/agentFeedback";
import { getExternalApiBase, getGraphXRViewerBase } from "../api/config";
import { useAppStore } from "../store";
import { lineSuffix, resolveEndpointFromMatches } from "../transport/atlasTransportResolve";
import {
  markTransportActionProcessed,
  wasTransportActionProcessed,
} from "../transport/atlasTransportDedupe";
import type { AtlasTransportActionSpec } from "../transport/atlasTransportTypes";
import { specKeysProvided } from "../transport/atlasTransportTypes";
import "./transport.css";

const GRAPH_MODES = ["all", "metro", "rail", "tram", "bus", "other"] as const;

export function TransportMode() {
  const graphMode = useAppStore((s) => s.transportGraphMode);
  const useLcc = useAppStore((s) => s.transportUseLcc);
  const viz = useAppStore((s) => s.transportViz);
  const graphViz = useAppStore((s) => s.transportGraphViz);
  const pathIds = useAppStore((s) => s.transportPathIds);
  const pathStationIds = useAppStore((s) => s.transportStationPathIds);
  const showTransfers = useAppStore((s) => s.transportShowTransfers);
  const stats = useAppStore((s) => s.transportStats);
  const setGraphMode = useAppStore((s) => s.setTransportGraphMode);
  const setUseLcc = useAppStore((s) => s.setTransportUseLcc);
  const setViz = useAppStore((s) => s.setTransportViz);
  const setGraphViz = useAppStore((s) => s.setTransportGraphViz);
  const setPathIds = useAppStore((s) => s.setTransportPathIds);
  const setStationPathIds = useAppStore((s) => s.setTransportStationPathIds);
  const setShowTransfers = useAppStore((s) => s.setTransportShowTransfers);
  const setStats = useAppStore((s) => s.setTransportStats);
  const routeErr = useAppStore((s) => s.transportRouteError);
  const routeMeta = useAppStore((s) => s.transportRouteMeta);
  const setRouteErr = useAppStore((s) => s.setTransportRouteError);
  const setRouteMeta = useAppStore((s) => s.setTransportRouteMeta);
  const setMode = useAppStore((s) => s.setMode);

  const [mapUrl, setMapUrl] = useState<string | null>(null);
  const [mapErr, setMapErr] = useState<string | null>(null);
  const [loadingMap, setLoadingMap] = useState(false);
  const prevUrl = useRef<string | null>(null);
  const prevGraphViz = useRef<string | null>(null);

  const [qStart, setQStart] = useState("");
  const [qEnd, setQEnd] = useState("");
  const [startId, setStartId] = useState<string | null>(null);
  const [endId, setEndId] = useState<string | null>(null);
  const [routeFocus, setRouteFocus] = useState<"start" | "end">("start");
  const [suggestions, setSuggestions] = useState<TransportSearchMatch[]>([]);
  const searchQ = routeFocus === "start" ? qStart : qEnd;

  const [dockTab, setDockTab] = useState<"route" | "search">("route");
  const [stopLookupQ, setStopLookupQ] = useState("");
  const [stopLookupErr, setStopLookupErr] = useState<string | null>(null);
  const [mapSelectedStopId, setMapSelectedStopId] = useState<string | null>(null);
  const [mapSelectedStationId, setMapSelectedStationId] = useState<string | null>(null);
  const [graph3dErr, setGraph3dErr] = useState<string | null>(null);
  const [launchingGraph3d, setLaunchingGraph3d] = useState(false);
  const graph3dSessionCache = useRef<Map<string, string>>(new Map());
  /** Suppress route autocomplete while an Atlas `run: route` action is in flight. */
  const atlasRouteProcessingRef = useRef(false);
  const localUiRef = useRef({
    dockTab: "route" as "route" | "search",
    routeFocus: "start" as "start" | "end",
    qStart: "",
    qEnd: "",
    stopLookupQ: "",
  });
  localUiRef.current = { dockTab, routeFocus, qStart, qEnd, stopLookupQ };

  const stationFirst = graphViz === "station";

  const atlasTransportAction = useAppStore((s) => s.atlasTransportAction);
  const setAtlasTransportAction = useAppStore((s) => s.setAtlasTransportAction);

  const autocompleteQ = dockTab === "search" ? stopLookupQ : searchQ;

  const refreshMap = useCallback(
    async (opts?: { selectedStopId?: string | null; selectedStationId?: string | null }) => {
      const selStop =
        opts && "selectedStopId" in opts ? opts.selectedStopId ?? null : mapSelectedStopId;
      const selStation =
        opts && "selectedStationId" in opts ? opts.selectedStationId ?? null : mapSelectedStationId;
      setLoadingMap(true);
      setMapErr(null);
      try {
        const mapBody: Record<string, unknown> = {
          mode: graphMode,
          use_lcc: useLcc,
          viz_mode: viz,
          graph_viz_mode: graphViz,
          path_stop_ids: pathIds,
          show_transfers: showTransfers,
        };
        if (
          (graphViz === "station" || graphViz === "hybrid") &&
          pathStationIds &&
          pathStationIds.length > 0
        ) {
          mapBody.path_station_ids = pathStationIds;
        }
        if (selStation && graphViz !== "stop") {
          mapBody.selected_station_id = selStation;
        } else if (selStop) {
          mapBody.selected_stop_id = selStop;
        }
        const { html } = await postTransportMap(mapBody);
        const blob = new Blob([html], { type: "text/html;charset=utf-8" });
        const url = URL.createObjectURL(blob);
        if (prevUrl.current) URL.revokeObjectURL(prevUrl.current);
        prevUrl.current = url;
        setMapUrl(url);
      } catch (e) {
        setMapErr(e instanceof Error ? e.message : "Map failed");
      } finally {
        setLoadingMap(false);
      }
    },
    [
      graphMode,
      useLcc,
      viz,
      graphViz,
      pathIds,
      pathStationIds,
      showTransfers,
      mapSelectedStopId,
      mapSelectedStationId,
    ]
  );

  useEffect(() => {
    void refreshMap();
  }, [refreshMap]);

  useEffect(() => {
    if (prevGraphViz.current === null) {
      prevGraphViz.current = graphViz;
      return;
    }
    if (prevGraphViz.current === graphViz) {
      return;
    }
    prevGraphViz.current = graphViz;
    setPathIds(null);
    setStartId(null);
    setEndId(null);
    setQStart("");
    setQEnd("");
    setRouteErr(null);
    setRouteMeta(null);
    setMapSelectedStopId(null);
    setMapSelectedStationId(null);
    setStopLookupQ("");
  }, [graphViz, setPathIds, setStationPathIds, setRouteErr, setRouteMeta]);

  useEffect(() => {
    void (async () => {
      try {
        const s = await getTransportStats(graphMode, useLcc);
        setStats(s);
      } catch {
        setStats(null);
      }
    })();
  }, [graphMode, useLcc, setStats]);

  useEffect(() => {
    const t = window.setTimeout(() => {
      void (async () => {
        if (atlasRouteProcessingRef.current) return;
        const q = autocompleteQ.trim();
        if (q.length < 2) {
          setSuggestions([]);
          return;
        }
        try {
          const r = await searchStops(q, graphMode, useLcc, stationFirst);
          setSuggestions(r.matches);
        } catch {
          setSuggestions([]);
        }
      })();
    }, 200);
    return () => window.clearTimeout(t);
  }, [autocompleteQ, graphMode, useLcc, stationFirst]);

  type RouteResult = Awaited<ReturnType<typeof postRoute>>;

  const applyRouteResult = useCallback(
    (r: RouteResult) => {
      if (r.ok && r.path) {
        setPathIds(r.path);
        setStationPathIds(
          r.station_path && r.station_path.length > 0 ? r.station_path : null
        );
        const parts: string[] = [];
        if (r.routing_scope === "station" && r.station_names && r.station_names.length > 0) {
          parts.push(r.station_names.join(" → "));
        }
        if (r.result?.distance_m != null) {
          parts.push(
            r.result.distance_m >= 1000
              ? `Distance: ${(r.result.distance_m / 1000).toFixed(2)} km`
              : `Distance: ${r.result.distance_m.toFixed(0)} m`
          );
        }
        if (r.result?.time_s != null) parts.push(`Time: ${(r.result.time_s / 60).toFixed(1)} min`);
        if (r.result?.transfers != null) parts.push(`Transfers: ${r.result.transfers}`);
        if (
          r.routing_scope !== "station" &&
          r.station_path &&
          r.station_path.length > 0 &&
          (!r.station_names || r.station_names.length === 0)
        ) {
          parts.push(`Stations: ${r.station_path.length}`);
        }
        setRouteMeta(parts.join(" · "));
      } else {
        setPathIds(null);
        setStationPathIds(null);
        setRouteErr(r.error?.message ?? "Route failed");
      }
    },
    [setPathIds, setStationPathIds, setRouteErr, setRouteMeta]
  );

  const applyRouteResultRef = useRef(applyRouteResult);
  applyRouteResultRef.current = applyRouteResult;
  const refreshMapRef = useRef(refreshMap);
  refreshMapRef.current = refreshMap;

  async function computeRoute() {
    setRouteErr(null);
    setRouteMeta(null);
    if (!startId || !endId) {
      setRouteErr(stationFirst ? "Pick start and end stations." : "Pick start and end stops.");
      return;
    }
    try {
      const r = await postRoute(
        graphMode,
        useLcc,
        stationFirst
          ? { kind: "station", from_station_id: startId, to_station_id: endId }
          : { kind: "stop", from_stop_id: startId, to_stop_id: endId }
      );
      applyRouteResult(r);
    } catch (e) {
      setRouteErr(e instanceof Error ? e.message : "Route failed");
    }
  }

  function clearRoute() {
    setPathIds(null);
    setStationPathIds(null);
    setStartId(null);
    setEndId(null);
    setQStart("");
    setQEnd("");
    setRouteErr(null);
    setRouteMeta(null);
    setGraph3dErr(null);
  }

  async function openGraph3DViewer() {
    setGraph3dErr(null);
    setLaunchingGraph3d(true);
    try {
      const cacheKey = JSON.stringify({
        mode: graphMode,
        use_lcc: useLcc,
        graph_viz_mode: graphViz,
        path_stop_ids: pathIds ?? [],
        path_station_ids: pathStationIds ?? [],
      });
      const cachedUrl = graph3dSessionCache.current.get(cacheKey);
      if (cachedUrl) {
        window.open(cachedUrl, "cspe-graphxr", "noopener,noreferrer,width=1280,height=860");
        return;
      }
      const session = await postTransportGraph3DSession({
        mode: graphMode,
        use_lcc: useLcc,
        graph_viz_mode: graphViz,
        path_stop_ids: pathIds ?? [],
        path_station_ids: pathStationIds ?? [],
      });
      const viewer = new URL(getGraphXRViewerBase());
      viewer.searchParams.set("session", session.session_id);
      viewer.searchParams.set("api", getExternalApiBase());
      const nextUrl = viewer.toString();
      graph3dSessionCache.current.set(cacheKey, nextUrl);
      if (graph3dSessionCache.current.size > 12) {
        const firstKey = graph3dSessionCache.current.keys().next().value;
        if (firstKey) graph3dSessionCache.current.delete(firstKey);
      }
      window.open(nextUrl, "cspe-graphxr", "noopener,noreferrer,width=1280,height=860");
    } catch (e) {
      setGraph3dErr(e instanceof Error ? e.message : "Unable to open 3D/VR graph.");
    } finally {
      setLaunchingGraph3d(false);
    }
  }

  function applyAtlasTransportPatches(spec: AtlasTransportActionSpec) {
    if (spec.open_app_mode === "transport") setMode("transport");
    if (spec.graph_mode !== undefined) setGraphMode(spec.graph_mode);
    if (spec.use_lcc !== undefined) setUseLcc(spec.use_lcc);
    if (spec.viz !== undefined) setViz(spec.viz);
    if (spec.graph_viz !== undefined) {
      setGraphViz(spec.graph_viz);
    } else if (spec.routing_scope !== undefined) {
      setGraphViz(spec.routing_scope === "station" ? "station" : "stop");
    }
    if (spec.show_transfers !== undefined) setShowTransfers(spec.show_transfers);
    if (spec.dock_tab !== undefined) setDockTab(spec.dock_tab);
    if (spec.route_focus !== undefined) setRouteFocus(spec.route_focus);
    if (spec.from_query !== undefined) setQStart(spec.from_query);
    if (spec.to_query !== undefined) setQEnd(spec.to_query);
    if (spec.stop_lookup_query !== undefined) setStopLookupQ(spec.stop_lookup_query);
  }

  useEffect(() => {
    const action = atlasTransportAction;
    if (!action) return;
    const { seq: mySeq, spec } = action;
    if (wasTransportActionProcessed(mySeq)) return;
    markTransportActionProcessed(mySeq);
    setAtlasTransportAction(null);

    let cancelled = false;
    const uiSnap = localUiRef.current;

    const keys = specKeysProvided(spec);
    const zBefore = useAppStore.getState();
    const stateBefore = {
      app_mode: zBefore.mode,
      transportGraphMode: zBefore.transportGraphMode,
      transportUseLcc: zBefore.transportUseLcc,
      transportViz: zBefore.transportViz,
      transportGraphViz: zBefore.transportGraphViz,
      transportShowTransfers: zBefore.transportShowTransfers,
      local: {
        dockTab: uiSnap.dockTab,
        routeFocus: uiSnap.routeFocus,
        qStart: uiSnap.qStart,
        qEnd: uiSnap.qEnd,
        stopLookupQ: uiSnap.stopLookupQ,
      },
    };

    applyAtlasTransportPatches(spec);

    const zAfter = useAppStore.getState();
    const effFrom = spec.from_query !== undefined ? spec.from_query : uiSnap.qStart;
    const effTo = spec.to_query !== undefined ? spec.to_query : uiSnap.qEnd;

    const stateAfter = {
      app_mode: zAfter.mode,
      transportGraphMode: zAfter.transportGraphMode,
      transportUseLcc: zAfter.transportUseLcc,
      transportViz: zAfter.transportViz,
      transportGraphViz: zAfter.transportGraphViz,
      transportShowTransfers: zAfter.transportShowTransfers,
      effective_from_query: effFrom,
      effective_to_query: effTo,
      dock_tab: spec.dock_tab ?? uiSnap.dockTab,
    };

    void postShellClientLog("atlas_transport_action", {
      seq: mySeq,
      keys_provided: keys,
      spec,
      state_before: stateBefore,
      state_after: stateAfter,
    });

    const run = spec.run;
    if (!run || run === "none") {
      return;
    }

    if (run === "reset_route") {
      clearRoute();
      void postShellClientLog("atlas_transport_trigger", { seq: mySeq, trigger: "reset_route" });
      return;
    }
    if (run === "compute") {
      void postShellClientLog("atlas_transport_trigger", { seq: mySeq, trigger: "compute" });
      void (async () => {
        await computeRoute();
      })();
      return () => {
        cancelled = true;
      };
    }
    if (run === "refresh_map") {
      void refreshMapRef.current();
      void postShellClientLog("atlas_transport_trigger", { seq: mySeq, trigger: "refresh_map" });
      return;
    }
    if (run === "clear_map_highlight") {
      setStopLookupErr(null);
      setMapSelectedStopId(null);
      setMapSelectedStationId(null);
      setStopLookupQ("");
      void refreshMapRef.current({ selectedStopId: null, selectedStationId: null });
      void postShellClientLog("atlas_transport_trigger", { seq: mySeq, trigger: "clear_map_highlight" });
      return;
    }

    if (run === "search_map") {
      void (async () => {
        const st = useAppStore.getState();
        const gv = st.transportGraphViz;
        const sf = gv === "station";
        const qRaw =
          spec.stop_lookup_query !== undefined ? spec.stop_lookup_query : uiSnap.stopLookupQ;
        const q = (qRaw ?? "").trim();
        if (q.length < 2) {
          setStopLookupErr("Type at least 2 characters.");
          return;
        }
        setStopLookupErr(null);
        try {
          const r = await searchStops(q, st.transportGraphMode, st.transportUseLcc, sf);
          const first = r.matches[0];
          if (!first) {
            setStopLookupErr(sf ? "No station found for that query." : "No stop found for that query.");
            setMapSelectedStopId(null);
            setMapSelectedStationId(null);
            void refreshMapRef.current({ selectedStopId: null, selectedStationId: null });
            void postShellClientLog("atlas_transport_trigger", {
              seq: mySeq,
              trigger: "search_map",
              ok: false,
              matches: 0,
            });
            return;
          }
          if (sf && first.station_id) {
            setMapSelectedStationId(first.station_id);
            setMapSelectedStopId(null);
            const label = `${first.station_name ?? first.stop_name ?? ""}${lineSuffix(first.line)}`.trim();
            setStopLookupQ(label);
            setSuggestions([]);
            void refreshMapRef.current({ selectedStationId: first.station_id, selectedStopId: null });
          } else if (first.stop_id) {
            setMapSelectedStopId(first.stop_id);
            setMapSelectedStationId(null);
            setStopLookupQ(`${first.stop_name ?? first.stop_id} | ${first.stop_id}`);
            setSuggestions([]);
            void refreshMapRef.current({ selectedStopId: first.stop_id, selectedStationId: null });
          } else {
            setStopLookupErr("No resolvable stop or station for that query.");
          }
          void postShellClientLog("atlas_transport_trigger", {
            seq: mySeq,
            trigger: "search_map",
            ok: true,
            matches: r.matches.length,
          });
        } catch {
          setStopLookupErr("Search failed.");
          void postShellClientLog("atlas_transport_trigger", { seq: mySeq, trigger: "search_map", ok: false });
        }
      })();
      return () => {
        cancelled = true;
      };
    }

    if (run === "route") {
      void (async () => {
        atlasRouteProcessingRef.current = true;
        try {
        const st0 = useAppStore.getState();
        const gm = st0.transportGraphMode;
        const ulcc = st0.transportUseLcc;
        const gv = st0.transportGraphViz;
        const stationFirstIv = gv === "station";
        const fromQ = effFrom.trim();
        const toQ = effTo.trim();
        if (!fromQ || !toQ) {
          setRouteErr("Origin and destination are required for route.");
          void postShellClientLog("atlas_transport_trigger", {
            seq: mySeq,
            trigger: "route",
            ok: false,
            error: "missing_from_or_to",
          });
          return;
        }

        setDockTab("route");
        setRouteFocus("start");
        setStartId(null);
        setEndId(null);
        setRouteErr(null);
        setRouteMeta(null);
        setPathIds(null);
        setStationPathIds(null);
        setSuggestions([]);

        const fromSearch = await searchStops(fromQ, gm, ulcc, stationFirstIv);
        if (cancelled) return;

        const fromRes = resolveEndpointFromMatches(fromQ, fromSearch.matches, stationFirstIv);
        void postShellClientLog("from_resolved", {
          seq: mySeq,
          query: fromQ,
          matches_count: fromSearch.matches.length,
          result_kind: fromRes.kind,
        });

        if (fromRes.kind === "ambiguous") {
          setSuggestions(fromRes.candidates);
          setRouteErr(
            stationFirstIv
              ? "Multiple stations match the origin — pick one in the list below."
              : "Multiple stops match the origin — pick one in the list below."
          );
          return;
        }
        if (fromRes.kind === "none") {
          setRouteErr(
            stationFirstIv ? "No origin station found for that query." : "No origin stop found for that query."
          );
          return;
        }

        setStartId(fromRes.id);
        setQStart(fromRes.label);
        setRouteFocus("end");

        const toSearch = await searchStops(toQ, gm, ulcc, stationFirstIv);
        if (cancelled) return;

        const toRes = resolveEndpointFromMatches(toQ, toSearch.matches, stationFirstIv);
        void postShellClientLog("to_resolved", {
          seq: mySeq,
          query: toQ,
          matches_count: toSearch.matches.length,
          result_kind: toRes.kind,
        });

        if (toRes.kind === "ambiguous") {
          setSuggestions(toRes.candidates);
          setRouteErr(
            stationFirstIv
              ? "Multiple stations match the destination — pick one in the list below."
              : "Multiple stops match the destination — pick one in the list below."
          );
          return;
        }
        if (toRes.kind === "none") {
          setRouteErr(
            stationFirstIv
              ? "No destination station found for that query."
              : "No destination stop found for that query."
          );
          return;
        }

        setEndId(toRes.id);
        setQEnd(toRes.label);

        const routePayload = stationFirstIv
          ? {
              kind: "station" as const,
              from_station_id: fromRes.id,
              to_station_id: toRes.id,
            }
          : { kind: "stop" as const, from_stop_id: fromRes.id, to_stop_id: toRes.id };

        void postShellClientLog("ui_route_payload", {
          seq: mySeq,
          mode: gm,
          use_lcc: ulcc,
          payload: routePayload,
        });

        try {
          const r = await postRoute(gm, ulcc, routePayload);
          if (cancelled) return;
          void postShellClientLog("ui_route_result", {
            seq: mySeq,
            ok: r.ok,
            routing_scope: r.routing_scope,
            path_len: r.path?.length ?? 0,
            error: r.error?.message ?? null,
          });
          void postAgentEvent("transport.ui_route_result", {
            seq: mySeq,
            ok: r.ok,
            routing_scope: r.routing_scope,
            path_len: r.path?.length ?? 0,
            error: r.error?.message ?? null,
            result: r.result,
          });
          void postShellClientLog("atlas_transport_trigger", { seq: mySeq, trigger: "route", ok: r.ok });
          applyRouteResultRef.current(r);
        } catch (e) {
          setRouteErr(e instanceof Error ? e.message : "Route failed");
          void postShellClientLog("ui_route_result", {
            seq: mySeq,
            ok: false,
            error: e instanceof Error ? e.message : "Route failed",
          });
          void postAgentEvent("transport.ui_route_failed", {
            seq: mySeq,
            error: e instanceof Error ? e.message : "Route failed",
          });
          void postShellClientLog("atlas_transport_trigger", {
            seq: mySeq,
            trigger: "route",
            ok: false,
          });
        }
        } finally {
          atlasRouteProcessingRef.current = false;
        }
      })();
    }

    return () => {
      cancelled = true;
    };
  }, [atlasTransportAction, setAtlasTransportAction]);

  async function searchStopOnMap() {
    setStopLookupErr(null);
    const q = stopLookupQ.trim();
    if (q.length < 2) {
      setStopLookupErr("Type at least 2 characters.");
      return;
    }
    try {
      const r = await searchStops(q, graphMode, useLcc, stationFirst);
      const first = r.matches[0];
      if (!first) {
        setStopLookupErr(stationFirst ? "No station found for that query." : "No stop found for that query.");
        setMapSelectedStopId(null);
        setMapSelectedStationId(null);
        void refreshMap({ selectedStopId: null, selectedStationId: null });
        return;
      }
      if (stationFirst && first.station_id) {
        setMapSelectedStationId(first.station_id);
        setMapSelectedStopId(null);
        const label = `${first.station_name ?? first.stop_name ?? ""}${lineSuffix(first.line)}`.trim();
        setStopLookupQ(label);
        setSuggestions([]);
        void refreshMap({ selectedStationId: first.station_id, selectedStopId: null });
      } else if (first.stop_id) {
        setMapSelectedStopId(first.stop_id);
        setMapSelectedStationId(null);
        setStopLookupQ(`${first.stop_name ?? first.stop_id} | ${first.stop_id}`);
        setSuggestions([]);
        void refreshMap({ selectedStopId: first.stop_id, selectedStationId: null });
      } else {
        setStopLookupErr("No resolvable stop or station for that query.");
      }
    } catch {
      setStopLookupErr("Search failed.");
    }
  }

  function clearMapStopHighlight() {
    setStopLookupErr(null);
    setMapSelectedStopId(null);
    setMapSelectedStationId(null);
    setStopLookupQ("");
    void refreshMap({ selectedStopId: null, selectedStationId: null });
  }

  return (
    <div className="transport-root">
      <div className="transport-map-wrap">
        {loadingMap && <div className="transport-map-loading">Loading map…</div>}
        {mapErr && (
          <div className="transport-map-err">
            <strong>Map</strong>
            <p style={{ margin: "8px 0 0" }}>{mapErr}</p>
          </div>
        )}
        {mapUrl && <iframe title="Transport map" src={mapUrl} />}
      </div>

      <div className="transport-left-stack">
        <div className="transport-float transport-float--stack-panel">
          <div className="transport-section-label">Visualization</div>
          <div className="transport-pill-row">
            <button
              type="button"
              className={`transport-btn-viz${viz === "geographic" ? " active" : ""}`}
              onClick={() => setViz("geographic")}
            >
              Geographic
            </button>
            <button
              type="button"
              className={`transport-btn-viz${viz === "network_3d" ? " active" : ""}`}
              onClick={() => setViz("network_3d")}
            >
              3D network
            </button>
            <button
              type="button"
              className="transport-btn-viz"
              onClick={() => void openGraph3DViewer()}
              disabled={launchingGraph3d}
              title={
                pathIds && pathIds.length > 0
                  ? "Open the full graph in GraphXR with this route highlighted"
                  : "Open the full graph in GraphXR"
              }
            >
              {launchingGraph3d ? "Opening..." : "3D/VR graph"}
            </button>
          </div>
          {graph3dErr && <div className="transport-route-err">{graph3dErr}</div>}

          <div className="transport-section-label">Graph layer</div>
          <div className="transport-pill-row">
            <button
              type="button"
              className={`transport-btn-viz${graphViz === "stop" ? " active" : ""}`}
              onClick={() => setGraphViz("stop")}
              title="Stop-level markers (routing graph)"
            >
              Stops
            </button>
            <button
              type="button"
              className={`transport-btn-viz${graphViz === "station" ? " active" : ""}`}
              onClick={() => setGraphViz("station")}
              title="Station-first: one node per station, routes optimize across platforms"
            >
              Stations
            </button>
            <button
              type="button"
              className={`transport-btn-viz${graphViz === "hybrid" ? " active" : ""}`}
              onClick={() => setGraphViz("hybrid")}
              title="Stops and station overlay"
            >
              Both
            </button>
          </div>

          <div className="transport-section-label">Mode</div>
          <div className="transport-mode-grid">
            {GRAPH_MODES.map((m) => (
              <button
                key={m}
                type="button"
                className={`transport-btn-mode${graphMode === m ? " active" : ""}`}
                onClick={() => setGraphMode(m)}
              >
                {m}
              </button>
            ))}
          </div>

          <button type="button" className="transport-btn-refresh" onClick={() => void refreshMap()}>
            Refresh map
          </button>
        </div>

        <div className="transport-float transport-float--stack-panel transport-float--stack-panel--scroll">
          <div className="transport-section-label" style={{ marginTop: 0 }}>
            Graph
          </div>
          <div className="transport-graph-toggles">
            <button
              type="button"
              className={`transport-toggle-btn${useLcc ? " transport-toggle-btn--on" : ""}`}
              aria-pressed={useLcc}
              onClick={() => setUseLcc(!useLcc)}
            >
              Largest connected component
            </button>
            <button
              type="button"
              className={`transport-toggle-btn${showTransfers ? " transport-toggle-btn--on" : ""}`}
              aria-pressed={showTransfers}
              onClick={() => setShowTransfers(!showTransfers)}
            >
              Show transfer edges
            </button>
          </div>

          <section className="transport-network-stats" aria-label="Network statistics">
            <div className="transport-section-label">Network stats</div>
            {stats ? (
              <div className="transport-network-stats__grid">
                <div className="transport-network-stats__col">
                  <span className="transport-network-stats__label">Nodes</span>
                  <span className="transport-network-stats__value">{stats.nodes}</span>
                </div>
                <div className="transport-network-stats__col">
                  <span className="transport-network-stats__label">Edges</span>
                  <span className="transport-network-stats__value">{stats.edges}</span>
                </div>
              </div>
            ) : (
              <p className="transport-network-stats__empty">Stats unavailable</p>
            )}
          </section>

          <div className="transport-section-label">Route</div>
          <p className="transport-hint">
            {stationFirst
              ? "Station layer: search by name, pick stations (not platforms), then Compute — path picks best platforms."
              : "Use the bar below: search stops, pick from list, then Compute."}
          </p>
          {(startId || endId) && (
            <div className="transport-ids">
              {startId && (
                <div>
                  Start: {stationFirst ? qStart || startId : `${qStart || startId}`}
                </div>
              )}
              {endId && (
                <div>
                  End: {stationFirst ? qEnd || endId : `${qEnd || endId}`}
                </div>
              )}
            </div>
          )}
          {routeMeta && <div className="transport-route-meta">{routeMeta}</div>}
          {routeErr && <div className="transport-route-err">{routeErr}</div>}
        </div>
      </div>

      {suggestions.length > 0 && (
        <div className="transport-suggest-layer" role="listbox">
          {suggestions.map((s) => (
            <button
              key={`${dockTab}-${routeFocus}-${s.station_id ?? s.stop_id ?? "x"}-${s.line ?? ""}`}
              type="button"
              className="transport-suggest-item"
              onClick={() => {
                if (dockTab === "search") {
                  if (stationFirst && s.station_id) {
                    setMapSelectedStationId(s.station_id);
                    setMapSelectedStopId(null);
                    setStopLookupQ(
                      `${s.station_name ?? s.stop_name ?? ""}${lineSuffix(s.line)}`.trim()
                    );
                    setStopLookupErr(null);
                    setSuggestions([]);
                    void refreshMap({ selectedStationId: s.station_id, selectedStopId: null });
                  } else if (s.stop_id) {
                    setMapSelectedStopId(s.stop_id);
                    setMapSelectedStationId(null);
                    setStopLookupQ(`${s.stop_name ?? s.stop_id} | ${s.stop_id}`);
                    setStopLookupErr(null);
                    setSuggestions([]);
                    void refreshMap({ selectedStopId: s.stop_id, selectedStationId: null });
                  }
                } else if (stationFirst && s.station_id) {
                  if (routeFocus === "start") {
                    setStartId(s.station_id);
                    setQStart(
                      `${s.station_name ?? s.stop_name ?? ""}${lineSuffix(s.line)}`.trim()
                    );
                  } else {
                    setEndId(s.station_id);
                    setQEnd(
                      `${s.station_name ?? s.stop_name ?? ""}${lineSuffix(s.line)}`.trim()
                    );
                  }
                  setSuggestions([]);
                } else if (s.stop_id) {
                  if (routeFocus === "start") {
                    setStartId(s.stop_id);
                    setQStart(`${s.stop_name ?? s.stop_id} | ${s.stop_id}`);
                  } else {
                    setEndId(s.stop_id);
                    setQEnd(`${s.stop_name ?? s.stop_id} | ${s.stop_id}`);
                  }
                  setSuggestions([]);
                }
              }}
            >
              {stationFirst
                ? `${s.station_name ?? s.stop_name ?? s.station_id}${lineSuffix(s.line)}`
                : `${s.stop_name ?? s.stop_id}${s.line ? ` · L${s.line}` : ""}`}
            </button>
          ))}
        </div>
      )}

      <div className="transport-dock-cluster" aria-label="Route and search dock">
        <div className="transport-dock-main">
          {dockTab === "route" ? (
            <div className="transport-dock-row">
              <input
                className="transport-dock-input"
                placeholder={stationFirst ? "Start station" : "Start stop"}
                value={qStart}
                onFocus={() => setRouteFocus("start")}
                onChange={(e) => setQStart(e.target.value)}
                aria-label={stationFirst ? "Start station search" : "Start stop search"}
              />
              <input
                className="transport-dock-input"
                placeholder={stationFirst ? "End station" : "End stop"}
                value={qEnd}
                onFocus={() => setRouteFocus("end")}
                onChange={(e) => setQEnd(e.target.value)}
                aria-label={stationFirst ? "End station search" : "End stop search"}
              />
              <button type="button" className="transport-btn-compute" onClick={() => void computeRoute()}>
                Compute
              </button>
              <button type="button" className="transport-btn-clear" onClick={clearRoute}>
                Clear
              </button>
            </div>
          ) : (
            <div className="transport-dock-row transport-dock-row--search">
              <input
                className="transport-dock-input"
                placeholder={stationFirst ? "Search station by name" : "Search by stop name or ID"}
                value={stopLookupQ}
                onChange={(e) => setStopLookupQ(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    void searchStopOnMap();
                  }
                }}
                aria-label={stationFirst ? "Find station on map" : "Find stop on map"}
              />
              <button type="button" className="transport-btn-compute" onClick={() => void searchStopOnMap()}>
                Search
              </button>
              <button type="button" className="transport-btn-clear" onClick={clearMapStopHighlight}>
                Clear highlight
              </button>
              {stopLookupErr && <span className="transport-dock-search-err">{stopLookupErr}</span>}
              {!stopLookupErr && (stationFirst ? mapSelectedStationId : mapSelectedStopId) && (
                <span className="transport-dock-search-ok">
                  Selected:{" "}
                  {stationFirst && stopLookupQ.trim()
                    ? stopLookupQ
                    : stationFirst
                      ? mapSelectedStationId
                      : mapSelectedStopId}
                </span>
              )}
            </div>
          )}
        </div>
        <div className="transport-dock-mode-rail" role="tablist" aria-label="Dock mode">
          <button
            type="button"
            role="tab"
            aria-selected={dockTab === "route"}
            className={`transport-dock-tab transport-dock-tab--rail${dockTab === "route" ? " transport-dock-tab--active" : ""}`}
            onClick={() => {
              setDockTab("route");
              setSuggestions([]);
            }}
          >
            Route
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={dockTab === "search"}
            className={`transport-dock-tab transport-dock-tab--rail${dockTab === "search" ? " transport-dock-tab--active" : ""}`}
            onClick={() => {
              setDockTab("search");
              setSuggestions([]);
            }}
          >
            {stationFirst ? "Search station" : "Search stop"}
          </button>
        </div>
      </div>
    </div>
  );
}
