import { useAppStore } from "../store";
import type { TransportExplorationView } from "../transport/atlasTransportTypes";

type Props = {
  exploration: TransportExplorationView;
};

/** Nearby stops/POIs inline in the Atlas chat thread. */
export function TransportExplorationPanel({ exploration }: Props) {
  const graphViz = useAppStore((s) => s.transportGraphViz);
  const requestTransportMapFocus = useAppStore((s) => s.requestTransportMapFocus);

  if (!exploration.nearby_stops?.length && !exploration.nearby_pois?.length) {
    return null;
  }

  const stationFirst = graphViz === "station";

  return (
    <div className="atlas-rail__exploration">
      <div className="atlas-rail__exploration-head">Nearby results</div>
      {exploration.summary && (
        <p className="atlas-rail__exploration-summary">{exploration.summary}</p>
      )}
      {exploration.nearby_stops && exploration.nearby_stops.length > 0 && (
        <>
          <div className="atlas-rail__exploration-label">Stops</div>
          <ul className="atlas-rail__exploration-list">
            {exploration.nearby_stops.map((row, i) => {
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
      {exploration.nearby_pois && exploration.nearby_pois.length > 0 && (
        <>
          <div className="atlas-rail__exploration-label">POIs</div>
          <ul className="atlas-rail__exploration-list">
            {exploration.nearby_pois.map((row, i) => {
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
