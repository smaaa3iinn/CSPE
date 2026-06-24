import { useCallback, useEffect, useRef, useState } from "react";
import {
  getTransportStats,
  postRoute,
  postShellClientLog,
  postTransportExplorationOverlay,
  postTransportMap,
  searchStops,
  type TransportSearchMatch,
} from "../api/client";
import { postAgentEvent } from "../api/agentFeedback";
import { useAppStore } from "../store";
import { is2dPrimaryDisplay, useDisplaySessionStore } from "../displaySession/displaySessionStore";
import { lineSuffix, resolveEndpointFromMatches } from "../transport/atlasTransportResolve";
import {
  markTransportActionProcessed,
  wasTransportActionProcessed,
} from "../transport/atlasTransportDedupe";
import {
  enableGraph3dLiveSync,
  isGraph3dLiveSyncEnabled,
  pushGraph3dViewSync,
} from "../transport/graph3dSync";
import { createMapRefreshScheduler, type MapRefreshOpts } from "../transport/mapRefreshScheduler";
import type { ExplorationMapPayload } from "../transport/mapExplorationBridge";
import {
  postExplorationToMapIframe,
  subscribeMapIframeMessages,
} from "../transport/mapExplorationBridge";
import type { AtlasTransportActionSpec } from "../transport/atlasTransportTypes";
import { specKeysProvided } from "../transport/atlasTransportTypes";
import {
  buildTransportBaseMapBody,
  buildTransportExplorationOverlayBody,
  buildTransportMapBody,
  readTransportViewContext,
  transportViewFingerprint,
} from "../transport/transportViewState";
import "./transport.css";
import { AtlasFocusBar } from "../components/AtlasFocusBar";

const GRAPH_MODES = ["all", "all_mb", "metro", "rail", "tram", "bus", "other"] as const;

const GRAPH_MODE_LABELS: Record<(typeof GRAPH_MODES)[number], string> = {
  all: "all",
  all_mb: "ALL-MB",
  metro: "metro",
  rail: "rail",
  tram: "tram",
  bus: "bus",
  other: "other",
};

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
  const routeLegs = useAppStore((s) => s.transportRouteLegs);
  const setRouteErr = useAppStore((s) => s.setTransportRouteError);
  const setRouteMeta = useAppStore((s) => s.setTransportRouteMeta);
  const setRouteLegs = useAppStore((s) => s.setTransportRouteLegs);
  const setMode = useAppStore((s) => s.setMode);

  const transportExplorationSeq = useAppStore((s) => s.transportExplorationSeq);
  const mapChromeHidden = useAppStore((s) => s.transportMapChromeHidden);
  const activeDisplayMode = useDisplaySessionStore((s) => s.activeDisplayMode);
  const openVrDevSession = useDisplaySessionStore((s) => s.openVrDevSession);
  const is2dDisplay = is2dPrimaryDisplay(activeDisplayMode);
  const vrDevActive = activeDisplayMode === "vr_dev";
  const setTransportExploration = useAppStore((s) => s.setTransportExploration);
  const mapSelectedStopId = useAppStore((s) => s.transportMapSelectionStopId);
  const mapSelectedStationId = useAppStore((s) => s.transportMapSelectionStationId);
  const setTransportMapSelection = useAppStore((s) => s.setTransportMapSelection);

  const [mapUrl, setMapUrl] = useState<string | null>(null);
  const [mapErr, setMapErr] = useState<string | null>(null);
  const [loadingMap, setLoadingMap] = useState(false);
  const prevUrl = useRef<string | null>(null);
  const mapFetchSeq = useRef(0);
  const explorationFetchSeq = useRef(0);
  const mapIframeRef = useRef<HTMLIFrameElement>(null);
  const mapBaseGeneration = useRef(0);
  const mapReadyGeneration = useRef(-1);
  const pendingExplorationRef = useRef<ExplorationMapPayload | null>(null);
  const lastExplorationPayloadRef = useRef<ExplorationMapPayload | null>(null);
  const pendingDeliveryTimersRef = useRef<number[]>([]);
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
  const mapSelectedStopIdRef = useRef<string | null>(null);
  const mapSelectedStationIdRef = useRef<string | null>(null);
  const loadingMapRef = useRef(false);
  const mapUrlRef = useRef<string | null>(null);
  mapSelectedStopIdRef.current = mapSelectedStopId;
  mapSelectedStationIdRef.current = mapSelectedStationId;
  loadingMapRef.current = loadingMap;
  mapUrlRef.current = mapUrl;
  const setMapSelection = useCallback(
    (payload: { stopId?: string | null; stationId?: string | null }) => {
      setTransportMapSelection(payload);
      if (payload.stopId !== undefined) {
        mapSelectedStopIdRef.current = payload.stopId;
      }
      if (payload.stationId !== undefined) {
        mapSelectedStationIdRef.current = payload.stationId;
      }
    },
    [setTransportMapSelection],
  );
  const [graph3dErr, setGraph3dErr] = useState<string | null>(null);
  const [launchingGraph3d, setLaunchingGraph3d] = useState(false);
  const [graph3dViewerUrl, setGraph3dViewerUrl] = useState<string | null>(null);
  const lastGraph3dSyncedFpRef = useRef<string | null>(null);
  const graph3dSyncTimerRef = useRef<number | null>(null);
  /** Suppress route autocomplete while an Atlas `run: route` action is in flight. */
  const atlasRouteProcessingRef = useRef(false);
  /** When false, agent filled search fields — hide debounced autocomplete until user types. */
  const [manualAutocomplete, setManualAutocomplete] = useState(true);

  const markAgentSearchAutofill = useCallback(() => {
    setManualAutocomplete(false);
    setSuggestions([]);
  }, []);

  const markManualSearchInput = useCallback(() => {
    setManualAutocomplete(true);
  }, []);
  const localUiRef = useRef({
    dockTab: "route" as "route" | "search",
    routeFocus: "start" as "start" | "end",
    qStart: "",
    qEnd: "",
    stopLookupQ: "",
  });
  localUiRef.current = { dockTab, routeFocus, qStart, qEnd, stopLookupQ };

  const stationFirst = graphViz === "station";

  const atlasTransportActions = useAppStore((s) => s.atlasTransportActions);
  const completeAtlasTransportAction = useAppStore((s) => s.completeAtlasTransportAction);
  const transportMapFocus = useAppStore((s) => s.transportMapFocus);
  const processingActionSeqRef = useRef<number | null>(null);

  const autocompleteQ = dockTab === "search" ? stopLookupQ : searchQ;

  const hasActiveExploration = useCallback((): boolean => {
    const exp = useAppStore.getState().transportExploration;
    return Boolean(exp?.center || exp?.nearby_stops?.length || exp?.nearby_pois?.length);
  }, []);

  const deliverExplorationPayload = useCallback((payload: ExplorationMapPayload | null) => {
    if (payload) {
      lastExplorationPayloadRef.current = payload;
      pendingExplorationRef.current = payload;
    } else {
      lastExplorationPayloadRef.current = null;
      pendingExplorationRef.current = null;
    }
    return postExplorationToMapIframe(mapIframeRef.current, payload);
  }, []);

  const clearPendingDeliveryTimers = useCallback(() => {
    for (const id of pendingDeliveryTimersRef.current) {
      window.clearTimeout(id);
    }
    pendingDeliveryTimersRef.current = [];
  }, []);

  const tryDeliverPendingExploration = useCallback((reason: string): boolean => {
    const pending = pendingExplorationRef.current ?? lastExplorationPayloadRef.current;
    if (!pending) return false;
    pendingExplorationRef.current = pending;
    const posted = postExplorationToMapIframe(mapIframeRef.current, pending);
    if (posted) {
      const exp = useAppStore.getState().transportExploration;
      void postShellClientLog("exploration_map_refresh", {
        phase: "overlay_deliver",
        reason,
        stop_count: exp?.nearby_stops?.length ?? 0,
        poi_count: exp?.nearby_pois?.length ?? 0,
        radius_m: exp?.radius_m ?? null,
        map_base_gen: mapBaseGeneration.current,
        map_ready_gen: mapReadyGeneration.current,
      });
    }
    return posted;
  }, []);

  const schedulePendingExplorationDelivery = useCallback(
    (fetchId?: number) => {
      clearPendingDeliveryTimers();
      for (const ms of [0, 100, 300, 800, 2000, 5000]) {
        const timerId = window.setTimeout(() => {
          if (fetchId !== undefined && fetchId !== explorationFetchSeq.current) {
            return;
          }
          tryDeliverPendingExploration(`retry_${ms}ms`);
        }, ms);
        pendingDeliveryTimersRef.current.push(timerId);
      }
    },
    [clearPendingDeliveryTimers, tryDeliverPendingExploration],
  );

  const scheduleBaseMapRefreshRef = useRef<(opts?: MapRefreshOpts) => void>(() => {});

  const executeBaseMapRefresh = useCallback(async (opts?: MapRefreshOpts) => {
      const fetchId = ++mapFetchSeq.current;
      const selStop =
        opts && "selectedStopId" in opts ? opts.selectedStopId ?? null : mapSelectedStopIdRef.current;
      const selStation =
        opts && "selectedStationId" in opts
          ? opts.selectedStationId ?? null
          : mapSelectedStationIdRef.current;
      setLoadingMap(true);
      setMapErr(null);
      try {
        const ctx = readTransportViewContext();
        const exp = useAppStore.getState().transportExploration;
        const embedExploration = Boolean(
          exp?.center || exp?.nearby_stops?.length || exp?.nearby_pois?.length,
        );
        const mapBody = (embedExploration ? buildTransportMapBody : buildTransportBaseMapBody)(ctx, {
          selectedStopId: selStop,
          selectedStationId: selStation,
        });
        const { html } = await postTransportMap(mapBody);
        if (fetchId !== mapFetchSeq.current) {
          return;
        }
        if (!html || html.trim().length < 32) {
          throw new Error("Map response was empty");
        }
        mapBaseGeneration.current += 1;
        mapReadyGeneration.current = -1;
        const blob = new Blob([html], { type: "text/html;charset=utf-8" });
        const url = URL.createObjectURL(blob);
        const prior = prevUrl.current;
        prevUrl.current = url;
        setMapUrl(url);
        if (prior) {
          window.setTimeout(() => URL.revokeObjectURL(prior), 4000);
        }
      } catch (e) {
        if (fetchId !== mapFetchSeq.current) return;
        setMapErr(e instanceof Error ? e.message : "Map failed");
      } finally {
        if (fetchId === mapFetchSeq.current) {
          setLoadingMap(false);
        }
      }
    }, []);

  const applyExplorationOverlay = useCallback(async () => {
    const fetchId = ++explorationFetchSeq.current;
    const overlayBody = buildTransportExplorationOverlayBody();
    if (!overlayBody) {
      clearPendingDeliveryTimers();
      deliverExplorationPayload(null);
      return;
    }

    try {
      const payload = await postTransportExplorationOverlay({
        exploration_overlay: overlayBody,
      });
      if (fetchId !== explorationFetchSeq.current) {
        return;
      }

      const posted = deliverExplorationPayload(payload);
      schedulePendingExplorationDelivery(fetchId);

      const hasIframe = Boolean(mapIframeRef.current?.contentWindow);
      const genReady =
        mapReadyGeneration.current === mapBaseGeneration.current && hasIframe;

      if (!hasIframe && !loadingMapRef.current) {
        scheduleBaseMapRefreshRef.current();
      }

      void postShellClientLog("exploration_map_refresh", {
        phase: posted && genReady ? "overlay_posted" : "overlay_queued",
        fetch_id: fetchId,
        reason: posted && genReady ? "await_iframe_ack" : "await_map",
        map_base_gen: mapBaseGeneration.current,
        map_ready_gen: mapReadyGeneration.current,
        base_in_flight: loadingMapRef.current || Boolean(mapUrlRef.current),
        stop_count: overlayBody.nearby_stops
          ? (overlayBody.nearby_stops as unknown[]).length
          : 0,
        poi_count: overlayBody.nearby_pois ? (overlayBody.nearby_pois as unknown[]).length : 0,
      });
    } catch (e) {
      void postShellClientLog("exploration_map_refresh", {
        phase: "overlay_error",
        fetch_id: fetchId,
        error: e instanceof Error ? e.message : "overlay fetch failed",
        map_base_gen: mapBaseGeneration.current,
      });
    }
  }, [
    clearPendingDeliveryTimers,
    deliverExplorationPayload,
    schedulePendingExplorationDelivery,
  ]);

  const executeBaseMapRefreshRef = useRef(executeBaseMapRefresh);
  executeBaseMapRefreshRef.current = executeBaseMapRefresh;
  const applyExplorationOverlayRef = useRef(applyExplorationOverlay);
  applyExplorationOverlayRef.current = applyExplorationOverlay;

  const mapSchedulerRef = useRef(
    createMapRefreshScheduler((opts) => executeBaseMapRefreshRef.current(opts)),
  );
  const explorationSchedulerRef = useRef(
    createMapRefreshScheduler(() => applyExplorationOverlayRef.current()),
  );

  const scheduleBaseMapRefresh = useCallback((opts?: MapRefreshOpts) => {
    mapSchedulerRef.current.schedule(opts);
  }, []);
  scheduleBaseMapRefreshRef.current = scheduleBaseMapRefresh;

  const scheduleExplorationOverlay = useCallback(() => {
    explorationSchedulerRef.current.schedule();
  }, []);

  /** Full base map reload (network, route, selection). */
  const scheduleMapRefresh = scheduleBaseMapRefresh;

  useEffect(() => {
    return subscribeMapIframeMessages((msg) => {
      if (msg.type === "cspe-map-exploration-applied") {
        pendingExplorationRef.current = null;
        clearPendingDeliveryTimers();
        void postShellClientLog("exploration_map_refresh", {
          phase: "overlay_applied",
          stop_count: useAppStore.getState().transportExploration?.nearby_stops?.length ?? 0,
          poi_count: useAppStore.getState().transportExploration?.nearby_pois?.length ?? 0,
        });
        return;
      }
      if (msg.type !== "cspe-map-ready") return;
      mapReadyGeneration.current = mapBaseGeneration.current;
      if (
        !pendingExplorationRef.current &&
        lastExplorationPayloadRef.current &&
        hasActiveExploration()
      ) {
        postExplorationToMapIframe(mapIframeRef.current, lastExplorationPayloadRef.current);
      }
      tryDeliverPendingExploration("map_ready");
      if (pendingExplorationRef.current) {
        schedulePendingExplorationDelivery();
      }
    });
  }, [
    clearPendingDeliveryTimers,
    hasActiveExploration,
    schedulePendingExplorationDelivery,
    tryDeliverPendingExploration,
  ]);

  const showMapbox = viz === "geographic" || viz === "network_3d";
  /** Embedded GraphXR in the main map is disabled — 3D/VR uses /vr-viewer in a separate tab. */
  const showGraph3d = false;

  useEffect(() => {
    if (!showMapbox) return;
    if (!hasActiveExploration()) {
      clearPendingDeliveryTimers();
      deliverExplorationPayload(null);
    }
  }, [
    transportExplorationSeq,
    showMapbox,
    hasActiveExploration,
    clearPendingDeliveryTimers,
    deliverExplorationPayload,
  ]);

  useEffect(() => {
    if (!mapUrl) return;
    schedulePendingExplorationDelivery();
  }, [mapUrl, schedulePendingExplorationDelivery]);

  useEffect(() => {
    if (!showMapbox || !is2dDisplay) return;
    scheduleBaseMapRefresh();
  }, [
    graphMode,
    useLcc,
    viz,
    graphViz,
    showTransfers,
    mapSelectedStopId,
    mapSelectedStationId,
    pathIds,
    pathStationIds,
    transportExplorationSeq,
    scheduleBaseMapRefresh,
    is2dDisplay,
  ]);

  const loadGraph3dViewer = useCallback(async (forceReload = false) => {
    setGraph3dErr(null);
    setLaunchingGraph3d(true);
    try {
      enableGraph3dLiveSync();
      const { viewerUrl, fingerprint } = await pushGraph3dViewSync(true);
      lastGraph3dSyncedFpRef.current = fingerprint;
      setGraph3dViewerUrl((prev) => (forceReload || !prev ? viewerUrl : prev));
    } catch (e) {
      setGraph3dErr(e instanceof Error ? e.message : "Unable to load 3D/VR graph.");
    } finally {
      setLaunchingGraph3d(false);
    }
  }, []);

  useEffect(() => {
    if (viz !== "graph3d") return;
    openVrDevSession();
    setViz("geographic");
  }, [viz, openVrDevSession, setViz]);

  useEffect(() => {
    if (!showGraph3d) return;
    void loadGraph3dViewer();
  }, [showGraph3d, loadGraph3dViewer]);

  const lastMapFocusSeq = useRef(0);
  useEffect(() => {
    if (!transportMapFocus || transportMapFocus.seq === lastMapFocusSeq.current) return;
    lastMapFocusSeq.current = transportMapFocus.seq;
    const { stationId, stopId, label } = transportMapFocus;
    const stationFirstNow = useAppStore.getState().transportGraphViz === "station";
    setDockTab("search");
    setStopLookupErr(null);
    markAgentSearchAutofill();
    if (label) setStopLookupQ(label);
    if (stationFirstNow && stationId) {
      setMapSelection({ stationId, stopId: null });
      scheduleMapRefresh({ selectedStationId: stationId, selectedStopId: null });
    } else if (stopId) {
      setMapSelection({ stopId, stationId: null });
      scheduleMapRefresh({ selectedStopId: stopId, selectedStationId: null });
    } else {
      scheduleMapRefresh();
    }
  }, [transportMapFocus, scheduleMapRefresh, markAgentSearchAutofill]);

  useEffect(() => {
    if (prevGraphViz.current === null) {
      prevGraphViz.current = graphViz;
      return;
    }
    if (prevGraphViz.current === graphViz) {
      return;
    }
    prevGraphViz.current = graphViz;
    if (showMapbox) {
      scheduleMapRefresh();
    }
  }, [graphViz, scheduleMapRefresh, showMapbox]);

  const lastViewFingerprint = useRef<string | null>(null);
  useEffect(() => {
    if (!showGraph3d) return;
    const fp = transportViewFingerprint(readTransportViewContext());
    if (lastViewFingerprint.current === fp) {
      return;
    }
    lastViewFingerprint.current = fp;

    if (!isGraph3dLiveSyncEnabled()) {
      return;
    }
    if (lastGraph3dSyncedFpRef.current === fp) {
      return;
    }

    if (graph3dSyncTimerRef.current) {
      window.clearTimeout(graph3dSyncTimerRef.current);
    }
    graph3dSyncTimerRef.current = window.setTimeout(() => {
      void (async () => {
        try {
          const { fingerprint } = await pushGraph3dViewSync(true);
          lastGraph3dSyncedFpRef.current = fingerprint;
        } catch {
          /* embedded viewer polls sync and reloads session internally */
        }
      })();
    }, 400);

    return () => {
      if (graph3dSyncTimerRef.current) {
        window.clearTimeout(graph3dSyncTimerRef.current);
      }
    };
  }, [
    showGraph3d,
    graphMode,
    useLcc,
    graphViz,
    pathIds,
    pathStationIds,
    showTransfers,
    mapSelectedStopId,
    mapSelectedStationId,
    transportExplorationSeq,
  ]);

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
        if (!manualAutocomplete) return;
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
  }, [autocompleteQ, graphMode, useLcc, stationFirst, manualAutocomplete]);

  type RouteResult = Awaited<ReturnType<typeof postRoute>>;

  const scheduleMapRefreshRef = useRef(scheduleMapRefresh);
  scheduleMapRefreshRef.current = scheduleMapRefresh;
  const scheduleExplorationOverlayRef = useRef(scheduleExplorationOverlay);
  scheduleExplorationOverlayRef.current = scheduleExplorationOverlay;

  const applyRouteResult = useCallback(
    (r: RouteResult) => {
      if (r.ok && r.path) {
        setPathIds(r.path);
        setStationPathIds(
          r.station_path && r.station_path.length > 0 ? r.station_path : null
        );
        setRouteLegs(r.path_legs && r.path_legs.length > 0 ? r.path_legs : null);
        const parts: string[] = [];
        if (r.result?.distance_m != null) {
          parts.push(
            r.result.distance_m >= 1000
              ? `Distance: ${(r.result.distance_m / 1000).toFixed(2)} km`
              : `Distance: ${r.result.distance_m.toFixed(0)} m`
          );
        }
        if (r.result?.time_s != null) parts.push(`Time: ${(r.result.time_s / 60).toFixed(1)} min`);
        if (r.result?.transfers != null) parts.push(`Transfers: ${r.result.transfers}`);
        setRouteMeta(parts.length > 0 ? parts.join(" · ") : null);
      } else {
        setPathIds(null);
        setStationPathIds(null);
        setRouteLegs(null);
        setRouteErr(r.error?.message ?? "Route failed");
      }
    },
    [setPathIds, setStationPathIds, setRouteErr, setRouteMeta, setRouteLegs]
  );

  const applyRouteResultRef = useRef(applyRouteResult);
  applyRouteResultRef.current = applyRouteResult;

  async function computeRoute() {
    setRouteErr(null);
    setRouteMeta(null);
    setRouteLegs(null);
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
    setRouteLegs(null);
    setStartId(null);
    setEndId(null);
    setQStart("");
    setQEnd("");
    setRouteErr(null);
    setRouteMeta(null);
    setGraph3dErr(null);
  }

  function clearRouteOverlay() {
    setPathIds(null);
    setStationPathIds(null);
    setRouteLegs(null);
    setRouteMeta(null);
    setRouteErr(null);
  }

  function clearTransportUi() {
    clearRoute();
    setTransportExploration(null);
    setMapSelection({ stopId: null, stationId: null });
    setStopLookupQ("");
    setStopLookupErr(null);
    setSuggestions([]);
    deliverExplorationPayload(null);
    setDockTab("route");
    void scheduleMapRefreshRef.current({ selectedStopId: null, selectedStationId: null });
  }

  function applyAtlasTransportPatches(spec: AtlasTransportActionSpec) {
    const current = useAppStore.getState();
    const routeContextChanged =
      (spec.graph_mode !== undefined && spec.graph_mode !== current.transportGraphMode) ||
      (spec.use_lcc !== undefined && spec.use_lcc !== current.transportUseLcc) ||
      (spec.graph_viz !== undefined && spec.graph_viz !== current.transportGraphViz) ||
      (spec.routing_scope !== undefined &&
        spec.graph_viz === undefined &&
        (spec.routing_scope === "station" ? "station" : "stop") !== current.transportGraphViz);
    if (routeContextChanged && spec.run !== "none") {
      clearRouteOverlay();
    }
    if (spec.run === "route" || spec.run === "compute") {
      setTransportExploration(null);
      deliverExplorationPayload(null);
    }
    if (spec.run === "exploration_map") {
      clearRouteOverlay();
    }
    if (spec.open_app_mode === "transport") setMode("transport");
    if (spec.graph_mode !== undefined) setGraphMode(spec.graph_mode);
    if (spec.use_lcc !== undefined) setUseLcc(spec.use_lcc);
    if (spec.viz !== undefined) {
      if (spec.viz === "graph3d") {
        openVrDevSession();
      } else {
        setViz(spec.viz);
      }
    }
    if (spec.graph_viz !== undefined) {
      setGraphViz(spec.graph_viz);
    } else if (spec.routing_scope !== undefined) {
      setGraphViz(spec.routing_scope === "station" ? "station" : "stop");
    }
    if (spec.show_transfers !== undefined) setShowTransfers(spec.show_transfers);
    if (spec.dock_tab !== undefined) setDockTab(spec.dock_tab);
    if (spec.route_focus !== undefined) setRouteFocus(spec.route_focus);
    const agentFilledSearch =
      spec.from_query !== undefined ||
      spec.to_query !== undefined ||
      spec.stop_lookup_query !== undefined;
    if (agentFilledSearch) {
      markAgentSearchAutofill();
    }
    if (spec.from_query !== undefined) setQStart(spec.from_query);
    if (spec.to_query !== undefined) setQEnd(spec.to_query);
    if (spec.stop_lookup_query !== undefined) setStopLookupQ(spec.stop_lookup_query);
  }

  useEffect(() => {
    const action = atlasTransportActions[0];
    if (!action) return;
    const { seq: mySeq, spec } = action;
    if (processingActionSeqRef.current === mySeq) return;
    if (wasTransportActionProcessed(mySeq)) {
      completeAtlasTransportAction(mySeq);
      return;
    }
    processingActionSeqRef.current = mySeq;
    markTransportActionProcessed(mySeq);

    const finishAction = () => {
      if (processingActionSeqRef.current === mySeq) {
        processingActionSeqRef.current = null;
      }
      completeAtlasTransportAction(mySeq);
    };
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
      finishAction();
      return;
    }

    if (run === "reset_route") {
      clearRoute();
      void postShellClientLog("atlas_transport_trigger", { seq: mySeq, trigger: "reset_route" });
      finishAction();
      return;
    }
    if (run === "clear_transport_ui") {
      clearTransportUi();
      void postShellClientLog("atlas_transport_trigger", {
        seq: mySeq,
        trigger: "clear_transport_ui",
      });
      finishAction();
      return;
    }
    if (run === "compute") {
      void postShellClientLog("atlas_transport_trigger", { seq: mySeq, trigger: "compute" });
      void (async () => {
        try {
          await computeRoute();
        } finally {
          finishAction();
        }
      })();
      return;
    }
    if (run === "refresh_map") {
      void scheduleMapRefreshRef.current();
      void postShellClientLog("atlas_transport_trigger", { seq: mySeq, trigger: "refresh_map" });
      finishAction();
      return;
    }
    if (run === "clear_map_highlight") {
      setStopLookupErr(null);
      setMapSelection({ stopId: null, stationId: null });
      setStopLookupQ("");
      void scheduleMapRefreshRef.current({ selectedStopId: null, selectedStationId: null });
      void postShellClientLog("atlas_transport_trigger", { seq: mySeq, trigger: "clear_map_highlight" });
      finishAction();
      return;
    }

    if (run === "exploration_map") {
      void (async () => {
        const readExp = () => useAppStore.getState().transportExploration;
        let exp = readExp();
        for (const delay of [0, 30, 80, 160]) {
          if (exp?.nearby_stops?.length || exp?.nearby_pois?.length) break;
          if (delay > 0) {
            await new Promise((resolve) => window.setTimeout(resolve, delay));
          }
          exp = readExp();
        }
        const st = useAppStore.getState();
        if (st.mode !== "transport") {
          st.setMode("transport");
        }
        const center = exp?.center;
        const label =
          (typeof spec.stop_lookup_query === "string" && spec.stop_lookup_query.trim()) ||
          String(
            center?.label ?? center?.station_name ?? center?.stop_name ?? "",
          ).trim();
        setDockTab("search");
        setStopLookupErr(null);
        if (label) {
          markAgentSearchAutofill();
          setStopLookupQ(label);
        }
        const stationId =
          (typeof spec.selected_station_id === "string" && spec.selected_station_id) ||
          (typeof center?.station_id === "string" ? center.station_id : null);
        const stopId =
          (typeof spec.selected_stop_id === "string" && spec.selected_stop_id) ||
          (typeof center?.stop_id === "string" ? center.stop_id : null);
        void postShellClientLog("exploration_map_trigger", {
          trigger: "exploration_map",
          seq: mySeq,
          stops: exp?.nearby_stops?.length ?? 0,
          pois: exp?.nearby_pois?.length ?? 0,
          selected_station_id: stationId,
          selected_stop_id: stopId,
          radius_m: exp?.radius_m ?? null,
          has_exploration: Boolean(exp),
        });
        void postShellClientLog("atlas_transport_trigger", {
          seq: mySeq,
          trigger: "exploration_map",
          ok: true,
          stops: exp?.nearby_stops?.length ?? 0,
          pois: exp?.nearby_pois?.length ?? 0,
        });
        if (showMapbox && exp) {
          scheduleMapRefreshRef.current();
        }
        finishAction();
      })();
      return;
    }

    if (run === "search_map") {
      void (async () => {
        markAgentSearchAutofill();
        const st = useAppStore.getState();
        const gv = st.transportGraphViz;
        const sf = gv === "station";
        const qRaw =
          spec.stop_lookup_query !== undefined ? spec.stop_lookup_query : uiSnap.stopLookupQ;
        const q = (qRaw ?? "").trim();
        if (q.length < 2) {
          setStopLookupErr("Type at least 2 characters.");
          finishAction();
          return;
        }
        setStopLookupErr(null);
        try {
          const r = await searchStops(q, st.transportGraphMode, st.transportUseLcc, sf);
          const first = r.matches[0];
          if (!first) {
            setStopLookupErr(sf ? "No station found for that query." : "No stop found for that query.");
            setMapSelection({ stopId: null, stationId: null });
            void scheduleMapRefreshRef.current({ selectedStopId: null, selectedStationId: null });
            void postShellClientLog("atlas_transport_trigger", {
              seq: mySeq,
              trigger: "search_map",
              ok: false,
              matches: 0,
            });
            finishAction();
            return;
          }
          if (sf && first.station_id) {
            setMapSelection({ stationId: first.station_id, stopId: null });
            const label = `${first.station_name ?? first.stop_name ?? ""}${lineSuffix(first.line)}`.trim();
            setStopLookupQ(label);
            setSuggestions([]);
            void scheduleMapRefreshRef.current({ selectedStationId: first.station_id, selectedStopId: null });
          } else if (first.stop_id) {
            setMapSelection({ stopId: first.stop_id, stationId: null });
            setStopLookupQ(`${first.stop_name ?? first.stop_id} | ${first.stop_id}`);
            setSuggestions([]);
            void scheduleMapRefreshRef.current({ selectedStopId: first.stop_id, selectedStationId: null });
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
        } finally {
          finishAction();
        }
      })();
      return;
    }

    if (run === "route") {
      void (async () => {
        atlasRouteProcessingRef.current = true;
        markAgentSearchAutofill();
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

        const fromRes = resolveEndpointFromMatches(fromQ, fromSearch.matches, stationFirstIv);
        void postShellClientLog("from_resolved", {
          seq: mySeq,
          query: fromQ,
          matches_count: fromSearch.matches.length,
          result_kind: fromRes.kind,
        });

        if (fromRes.kind === "ambiguous") {
          setManualAutocomplete(true);
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

        const toRes = resolveEndpointFromMatches(toQ, toSearch.matches, stationFirstIv);
        void postShellClientLog("to_resolved", {
          seq: mySeq,
          query: toQ,
          matches_count: toSearch.matches.length,
          result_kind: toRes.kind,
        });

        if (toRes.kind === "ambiguous") {
          setManualAutocomplete(true);
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
          markAgentSearchAutofill();
          finishAction();
        }
      })();
      return;
    }

    finishAction();
  }, [atlasTransportActions, completeAtlasTransportAction]);

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
        setMapSelection({ stopId: null, stationId: null });
        void scheduleMapRefresh({ selectedStopId: null, selectedStationId: null });
        return;
      }
      if (stationFirst && first.station_id) {
        setMapSelection({ stationId: first.station_id, stopId: null });
        const label = `${first.station_name ?? first.stop_name ?? ""}${lineSuffix(first.line)}`.trim();
        setStopLookupQ(label);
        setSuggestions([]);
        void scheduleMapRefresh({ selectedStationId: first.station_id, selectedStopId: null });
      } else if (first.stop_id) {
        setMapSelection({ stopId: first.stop_id, stationId: null });
        setStopLookupQ(`${first.stop_name ?? first.stop_id} | ${first.stop_id}`);
        setSuggestions([]);
        void scheduleMapRefresh({ selectedStopId: first.stop_id, selectedStationId: null });
      } else {
        setStopLookupErr("No resolvable stop or station for that query.");
      }
    } catch {
      setStopLookupErr("Search failed.");
    }
  }

  function clearMapStopHighlight() {
    setStopLookupErr(null);
    setMapSelection({ stopId: null, stationId: null });
    setStopLookupQ("");
    setTransportExploration(null);
    void scheduleMapRefresh({ selectedStopId: null, selectedStationId: null });
  }

  return (
    <div
      className={`transport-root${
        mapChromeHidden && !showGraph3d ? " transport-root--chrome-hidden" : ""
      }${showGraph3d ? " transport-root--graph3d-fullscreen" : ""}`}
    >
      <div className="transport-map-wrap">
        {showGraph3d ? (
          <>
            {launchingGraph3d && !graph3dViewerUrl && (
              <div className="transport-map-loading">Loading 3D graph…</div>
            )}
            {graph3dErr && !graph3dViewerUrl && (
              <div className="transport-map-err">
                <strong>3D/VR graph</strong>
                <p style={{ margin: "8px 0 0" }}>{graph3dErr}</p>
              </div>
            )}
            {graph3dViewerUrl && (
              <iframe
                title="Transport 3D/VR graph"
                className="transport-graph3d-iframe"
                src={graph3dViewerUrl}
                allow="xr-spatial-tracking; fullscreen"
              />
            )}
          </>
        ) : (
          <>
            {loadingMap && <div className="transport-map-loading">Loading map…</div>}
            {mapErr && (
              <div className="transport-map-err">
                <strong>Map</strong>
                <p style={{ margin: "8px 0 0" }}>{mapErr}</p>
              </div>
            )}
            {mapUrl && (
              <iframe
                ref={mapIframeRef}
                title="Transport map"
                src={mapUrl}
                onLoad={() => {
                  mapReadyGeneration.current = -1;
                  if (lastExplorationPayloadRef.current && hasActiveExploration()) {
                    pendingExplorationRef.current = lastExplorationPayloadRef.current;
                    postExplorationToMapIframe(mapIframeRef.current, lastExplorationPayloadRef.current);
                  }
                  schedulePendingExplorationDelivery();
                }}
              />
            )}
          </>
        )}
      </div>

      {showGraph3d && (
        <button
          type="button"
          className="transport-graph3d-exit"
          onClick={() => setViz("geographic")}
          title="Return to map view"
        >
          ← Map
        </button>
      )}

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
              title="Mapbox map with pitch and 3D buildings"
            >
              3D map
            </button>
            <button
              type="button"
              className={`transport-btn-viz${vrDevActive ? " active" : ""} transport-btn-graph3d`}
              onClick={() => openVrDevSession()}
              title="Open 3D/VR dev viewer in a new tab"
            >
              3D/VR graph
            </button>
          </div>
          {graph3dErr && viz === "graph3d" && <div className="transport-route-err">{graph3dErr}</div>}

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
                {GRAPH_MODE_LABELS[m]}
              </button>
            ))}
          </div>

          <button type="button" className="transport-btn-refresh" onClick={() => void scheduleMapRefresh()}>
            Refresh map
          </button>
        </div>

        <div className="transport-float transport-float--stack-panel transport-float--stack-panel--scroll">
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
          {routeLegs && routeLegs.length > 0 && (
            <div className="transport-route-legs" aria-label="Route breakdown">
              {routeLegs.map((leg, index) => (
                <div
                  key={`${leg.kind}-${index}-${leg.summary}`}
                  className={`transport-route-leg${leg.kind === "transfer" ? " transport-route-leg--transfer" : ""}`}
                  style={{ borderLeftColor: leg.color }}
                >
                  <div className="transport-route-leg__summary">{leg.summary}</div>
                </div>
              ))}
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
                    setMapSelection({ stationId: s.station_id, stopId: null });
                    setStopLookupQ(
                      `${s.station_name ?? s.stop_name ?? ""}${lineSuffix(s.line)}`.trim()
                    );
                    setStopLookupErr(null);
                    setSuggestions([]);
                    void scheduleMapRefresh({ selectedStationId: s.station_id, selectedStopId: null });
                  } else if (s.stop_id) {
                    setMapSelection({ stopId: s.stop_id, stationId: null });
                    setStopLookupQ(`${s.stop_name ?? s.stop_id} | ${s.stop_id}`);
                    setStopLookupErr(null);
                    setSuggestions([]);
                    void scheduleMapRefresh({ selectedStopId: s.stop_id, selectedStationId: null });
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
                onChange={(e) => {
                  markManualSearchInput();
                  setQStart(e.target.value);
                }}
                aria-label={stationFirst ? "Start station search" : "Start stop search"}
              />
              <input
                className="transport-dock-input"
                placeholder={stationFirst ? "End station" : "End stop"}
                value={qEnd}
                onFocus={() => setRouteFocus("end")}
                onChange={(e) => {
                  markManualSearchInput();
                  setQEnd(e.target.value);
                }}
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
                onChange={(e) => {
                  markManualSearchInput();
                  setStopLookupQ(e.target.value);
                }}
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

      {mapChromeHidden && !showGraph3d && <AtlasFocusBar />}
    </div>
  );
}
