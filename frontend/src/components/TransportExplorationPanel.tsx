import { useAppStore } from "../store";

/** Nearby stops/POIs list shown in the Atlas rail (not over the map). */
export function TransportExplorationPanel() {
  const transportExploration = useAppStore((s) => s.transportExploration);
  const graphViz = useAppStore((s) => s.transportGraphViz);
  const requestTransportMapFocus = useAppStore((s) => s.requestTransportMapFocus);

  if (
    !transportExploration ||
    (!transportExploration.nearby_stops?.length && !transportExploration.nearby_pois?.length)
  ) {
    return null;
  }

  const stationFirst = graphViz === "station";

  return (
    <div className="atlas-rail__exploration">
      <div className="atlas-rail__exploration-head">Nearby results</div>
      {transportExploration.summary && (
        <p className="atlas-rail__exploration-summary">{transportExploration.summary}</p>
      )}
      {transportExploration.nearby_stops && transportExploration.nearby_stops.length > 0 && (
        <>
          <div className="atlas-rail__exploration-label">Stops</div>
          <ul className="atlas-rail__exploration-list">
            {transportExploration.nearby_stops.map((row, i) => {
              const name = String(row.station_name ?? row.stop_name ?? row.station_id ?? "?");
              const dist = row.distance_m != null ? `${Math.round(Number(row.distance_m))} m` : "";
              const sid = typeof row.station_id === "string" ? row.station_id : null;
              const stopId = typeof row.stop_id === "string" ? row.stop_id : null;
              return (
                <li key={`stop-${sid ?? stopId ?? i}`}>
                  <button
                    type="button"
                    className="atlas-rail__exploration-item"
                    onClick={() => {
                      if (stationFirst && sid) {
                        requestTransportMapFocus({ stationId: sid, stopId: null, label: name });
                      } else if (stopId) {
                        requestTransportMapFocus({ stopId, stationId: null, label: name });
                      }
                    }}
                  >
                    <span>{name}</span>
                    {dist && <span className="atlas-rail__exploration-dist">{dist}</span>}
                  </button>
                </li>
              );
            })}
          </ul>
        </>
      )}
      {transportExploration.nearby_pois && transportExploration.nearby_pois.length > 0 && (
        <>
          <div className="atlas-rail__exploration-label">POIs</div>
          <ul className="atlas-rail__exploration-list">
            {transportExploration.nearby_pois.map((row, i) => {
              const name = String(row.name ?? row.type ?? "POI");
              const dist = row.distance_m != null ? `${Math.round(Number(row.distance_m))} m` : "";
              const cat = row.type ? String(row.type) : "";
              return (
                <li key={`poi-${name}-${i}`}>
                  <span className="atlas-rail__exploration-item atlas-rail__exploration-item--poi">
                    <span>{name}</span>
                    <span className="atlas-rail__exploration-dist">
                      {[cat, dist].filter(Boolean).join(" · ")}
                    </span>
                  </span>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </div>
  );
}
