import { useCallback, useEffect, useRef, useState } from "react";
import { getTransportStats, postRoute, postTransportMap, searchStops } from "../api/client";
import { useAppStore } from "../store";
import "./transport.css";

const GRAPH_MODES = ["all", "metro", "rail", "tram", "bus", "other"] as const;

export function TransportMode() {
  const graphMode = useAppStore((s) => s.transportGraphMode);
  const useLcc = useAppStore((s) => s.transportUseLcc);
  const viz = useAppStore((s) => s.transportViz);
  const pathIds = useAppStore((s) => s.transportPathIds);
  const showTransfers = useAppStore((s) => s.transportShowTransfers);
  const stats = useAppStore((s) => s.transportStats);
  const setGraphMode = useAppStore((s) => s.setTransportGraphMode);
  const setUseLcc = useAppStore((s) => s.setTransportUseLcc);
  const setViz = useAppStore((s) => s.setTransportViz);
  const setPathIds = useAppStore((s) => s.setTransportPathIds);
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

  const [qStart, setQStart] = useState("");
  const [qEnd, setQEnd] = useState("");
  const [startId, setStartId] = useState<string | null>(null);
  const [endId, setEndId] = useState<string | null>(null);
  const [routeFocus, setRouteFocus] = useState<"start" | "end">("start");
  const [suggestions, setSuggestions] = useState<{ stop_id: string; stop_name?: string; line?: string }[]>([]);
  const searchQ = routeFocus === "start" ? qStart : qEnd;

  const [dockTab, setDockTab] = useState<"route" | "search">("route");
  const [stopLookupQ, setStopLookupQ] = useState("");
  const [stopLookupErr, setStopLookupErr] = useState<string | null>(null);
  const [mapSelectedStopId, setMapSelectedStopId] = useState<string | null>(null);

  const autocompleteQ = dockTab === "search" ? stopLookupQ : searchQ;

  const refreshMap = useCallback(
    async (opts?: { selectedStopId?: string | null }) => {
      const selected =
        opts && "selectedStopId" in opts ? opts.selectedStopId ?? null : mapSelectedStopId;
      setLoadingMap(true);
      setMapErr(null);
      try {
        const { html } = await postTransportMap({
          mode: graphMode,
          use_lcc: useLcc,
          viz_mode: viz,
          path_stop_ids: pathIds,
          show_transfers: showTransfers,
          ...(selected ? { selected_stop_id: selected } : {}),
        });
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
    [graphMode, useLcc, viz, pathIds, showTransfers, mapSelectedStopId]
  );

  useEffect(() => {
    void refreshMap();
  }, [refreshMap]);

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
          const r = await searchStops(q, graphMode, useLcc);
          setSuggestions(r.matches);
        } catch {
          setSuggestions([]);
        }
      })();
    }, 200);
    return () => window.clearTimeout(t);
  }, [autocompleteQ, graphMode, useLcc]);

  async function computeRoute() {
    setRouteErr(null);
    setRouteMeta(null);
    if (!startId || !endId) {
      setRouteErr("Pick start and end stops.");
      return;
    }
    try {
      const r = await postRoute(startId, endId, graphMode, useLcc);
      if (r.ok && r.path) {
        setPathIds(r.path);
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
        setRouteMeta(parts.join(" · "));
      } else {
        setPathIds(null);
        setRouteErr(r.error?.message ?? "Route failed");
      }
    } catch (e) {
      setRouteErr(e instanceof Error ? e.message : "Route failed");
    }
  }

  function clearRoute() {
    setPathIds(null);
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
      const r = await searchStops(q, graphMode, useLcc);
      const first = r.matches[0];
      if (!first) {
        setStopLookupErr("No stop found for that query.");
        setMapSelectedStopId(null);
        void refreshMap({ selectedStopId: null });
        return;
      }
      setMapSelectedStopId(first.stop_id);
      setStopLookupQ(`${first.stop_name ?? first.stop_id} | ${first.stop_id}`);
      setSuggestions([]);
      void refreshMap({ selectedStopId: first.stop_id });
    } catch {
      setStopLookupErr("Search failed.");
    }
  }

  function clearMapStopHighlight() {
    setStopLookupErr(null);
    setMapSelectedStopId(null);
    setStopLookupQ("");
    void refreshMap({ selectedStopId: null });
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
          <p className="transport-hint">Use the bar below: search stops, pick from list, then Compute.</p>
          {(startId || endId) && (
            <div className="transport-ids">
              {startId && <div>Start: {startId}</div>}
              {endId && <div>End: {endId}</div>}
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
              key={`${dockTab}-${routeFocus}-${s.stop_id}`}
              type="button"
              className="transport-suggest-item"
              onClick={() => {
                if (dockTab === "search") {
                  setMapSelectedStopId(s.stop_id);
                  setStopLookupQ(`${s.stop_name ?? s.stop_id} | ${s.stop_id}`);
                  setStopLookupErr(null);
                  setSuggestions([]);
                  void refreshMap({ selectedStopId: s.stop_id });
                } else if (routeFocus === "start") {
                  setStartId(s.stop_id);
                  setQStart(`${s.stop_name ?? s.stop_id} | ${s.stop_id}`);
                  setSuggestions([]);
                } else {
                  setEndId(s.stop_id);
                  setQEnd(`${s.stop_name ?? s.stop_id} | ${s.stop_id}`);
                  setSuggestions([]);
                }
              }}
            >
              {s.stop_name ?? s.stop_id} ({s.stop_id})
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
                placeholder="Start stop"
                value={qStart}
                onFocus={() => setRouteFocus("start")}
                onChange={(e) => setQStart(e.target.value)}
                aria-label="Start stop search"
              />
              <input
                className="transport-dock-input"
                placeholder="End stop"
                value={qEnd}
                onFocus={() => setRouteFocus("end")}
                onChange={(e) => setQEnd(e.target.value)}
                aria-label="End stop search"
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
                placeholder="Search by stop name or ID"
                value={stopLookupQ}
                onChange={(e) => setStopLookupQ(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    void searchStopOnMap();
                  }
                }}
                aria-label="Find stop on map"
              />
              <button type="button" className="transport-btn-compute" onClick={() => void searchStopOnMap()}>
                Search
              </button>
              <button type="button" className="transport-btn-clear" onClick={clearMapStopHighlight}>
                Clear highlight
              </button>
              {stopLookupErr && <span className="transport-dock-search-err">{stopLookupErr}</span>}
              {mapSelectedStopId && !stopLookupErr && (
                <span className="transport-dock-search-ok">Selected: {mapSelectedStopId}</span>
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
            Search stop
          </button>
        </div>
      </div>
    </div>
  );
}
