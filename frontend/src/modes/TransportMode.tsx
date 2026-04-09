import { useCallback, useEffect, useRef, useState } from "react";
import { getTransportStats, postRoute, postTransportMap, searchStops, type TransportSearchMatch } from "../api/client";
import { useAppStore } from "../store";
import "./transport.css";

const GRAPH_MODES = ["all", "metro", "rail", "tram", "bus", "other"] as const;

/** One line → " · L7"; several (comma-separated from API) → " · Lines 7, 14". */
function lineSuffix(line: string | null | undefined): string {
  const t = line != null ? String(line).trim() : "";
  if (!t) return "";
  if (t.includes(",")) return ` · Lines ${t}`;
  return ` · L${t}`;
}

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

  const stationFirst = graphViz === "station";

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
  }

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
          </div>

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
