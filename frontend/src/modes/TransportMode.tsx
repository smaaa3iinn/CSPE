import { useCallback, useEffect, useRef, useState } from "react";
import { getTransportStats, postRoute, postTransportMap, searchStops } from "../api/client";
import { useAppStore } from "../store";

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

  const refreshMap = useCallback(async () => {
    setLoadingMap(true);
    setMapErr(null);
    try {
      const { html } = await postTransportMap({
        mode: graphMode,
        use_lcc: useLcc,
        viz_mode: viz,
        path_stop_ids: pathIds,
        show_transfers: showTransfers,
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
  }, [graphMode, useLcc, viz, pathIds, showTransfers]);

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
        const q = searchQ.trim();
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
  }, [searchQ, graphMode, useLcc]);

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

  return (
    <div style={{ display: "flex", flex: 1, minHeight: 0 }}>
      <main style={{ flex: 1, minWidth: 0, position: "relative", background: "#0a0c0f" }}>
        {loadingMap && (
          <div className="muted" style={{ position: "absolute", top: 12, left: 12, zIndex: 2 }}>
            Loading map…
          </div>
        )}
        {mapErr && (
          <div style={{ color: "var(--danger)", padding: 16 }}>
            <strong>Map</strong>
            <p>{mapErr}</p>
          </div>
        )}
        {mapUrl && (
          <iframe title="Transport map" src={mapUrl} style={{ width: "100%", height: "100%", border: "none" }} />
        )}
      </main>
      <aside
        style={{
          width: "var(--right-w)",
          borderLeft: "1px solid var(--border)",
          background: "var(--bg-elevated)",
          overflowY: "auto",
          padding: 14,
        }}
      >
        <div className="panel-title">Graph</div>
        <div style={{ display: "flex", flexDirection: "column", gap: 10, marginBottom: 16 }}>
          <label className="muted">
            Mode
            <select
              style={{ width: "100%", marginTop: 4 }}
              value={graphMode}
              onChange={(e) => setGraphMode(e.target.value as typeof graphMode)}
            >
              {(["all", "metro", "rail", "tram", "bus", "other"] as const).map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </label>
          <label className="muted" style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <input type="checkbox" checked={useLcc} onChange={(e) => setUseLcc(e.target.checked)} />
            Largest connected component
          </label>
          <label className="muted">
            Visualization
            <select
              style={{ width: "100%", marginTop: 4 }}
              value={viz}
              onChange={(e) => setViz(e.target.value as typeof viz)}
            >
              <option value="geographic">Geographic Mapbox</option>
              <option value="network_3d">3D network</option>
            </select>
          </label>
          <label className="muted" style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <input type="checkbox" checked={showTransfers} onChange={(e) => setShowTransfers(e.target.checked)} />
            Show transfers on map
          </label>
          <button type="button" onClick={() => void refreshMap()}>
            Refresh map
          </button>
        </div>

        <div className="panel-title">Network stats</div>
        {stats ? (
          <p style={{ marginTop: 0 }}>
            Nodes <strong>{stats.nodes}</strong>
            <br />
            Edges <strong>{stats.edges}</strong>
          </p>
        ) : (
          <p className="muted">Unavailable</p>
        )}

        <div className="panel-title" style={{ marginTop: 20 }}>
          Route
        </div>
        <p className="muted">Type to search; pick from the list for start and end.</p>
        <input
          placeholder="Start stop…"
          value={qStart}
          onFocus={() => setRouteFocus("start")}
          onChange={(e) => setQStart(e.target.value)}
          style={{ width: "100%", marginBottom: 6 }}
        />
        <input
          placeholder="End stop…"
          value={qEnd}
          onFocus={() => setRouteFocus("end")}
          onChange={(e) => setQEnd(e.target.value)}
          style={{ width: "100%", marginBottom: 6 }}
        />
        {suggestions.length > 0 && (
          <div
            style={{
              border: "1px solid var(--border)",
              borderRadius: 6,
              maxHeight: 140,
              overflowY: "auto",
              marginBottom: 8,
            }}
          >
            {suggestions.map((s) => (
              <button
                key={`${routeFocus}-${s.stop_id}`}
                type="button"
                className="ghost"
                onClick={() => {
                  if (routeFocus === "start") {
                    setStartId(s.stop_id);
                    setQStart(`${s.stop_name ?? s.stop_id} | ${s.stop_id}`);
                  } else {
                    setEndId(s.stop_id);
                    setQEnd(`${s.stop_name ?? s.stop_id} | ${s.stop_id}`);
                  }
                  setSuggestions([]);
                }}
                style={{
                  display: "block",
                  width: "100%",
                  textAlign: "left",
                  border: "none",
                  borderBottom: "1px solid var(--border)",
                  borderRadius: 0,
                  fontSize: 12,
                }}
              >
                {s.stop_name ?? s.stop_id} ({s.stop_id})
              </button>
            ))}
          </div>
        )}
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button type="button" className="primary" onClick={() => void computeRoute()}>
            Compute
          </button>
          <button type="button" onClick={clearRoute}>
            Clear
          </button>
        </div>
        {(startId || endId) && (
          <p className="muted" style={{ marginTop: 8 }}>
            {startId && <>Start: {startId}</>}
            {startId && endId && <br />}
            {endId && <>End: {endId}</>}
          </p>
        )}
        {routeMeta && <p style={{ marginTop: 8 }}>{routeMeta}</p>}
        {routeErr && <p style={{ color: "var(--danger)", marginTop: 8 }}>{routeErr}</p>}
      </aside>
    </div>
  );
}
