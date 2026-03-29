from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
import re

import networkx as nx
import pandas as pd

# GTFS route_type (common mapping)
# 0 Tram/Streetcar, 1 Subway/Metro, 2 Rail, 3 Bus
ROUTE_TYPE_TO_MODE = {0: "tram", 1: "metro", 2: "rail", 3: "bus"}

MODE_SPEED_M_S = {
    "metro": 12.0,
    "rail": 16.0,
    "tram": 8.0,
    "bus": 5.0,
    "other": 6.0,
}
DEFAULT_WALKING_SPEED_M_S = 1.4
DEFAULT_TRANSFER_PENALTY_S = 180.0
DEFAULT_SAME_NAME_TRANSFER_M = 400.0
DEFAULT_NEARBY_TRANSFER_M = 200.0
EDGE_COLUMNS = ["a", "b", "edge_kind", "mode", "modes", "distance_m", "time_s", "cost", "weight_m"]


@dataclass
class GTFSData:
    stops: pd.DataFrame
    routes: pd.DataFrame
    trips: pd.DataFrame
    stop_times: pd.DataFrame


def load_gtfs(gtfs_dir: str | Path) -> GTFSData:
    gtfs_dir = Path(gtfs_dir)

    stops = pd.read_csv(
        gtfs_dir / "stops.txt",
        usecols=["stop_id", "stop_name", "stop_lat", "stop_lon"],
        dtype={
            "stop_id": "string",
            "stop_name": "string",
            "stop_lat": "float32",
            "stop_lon": "float32",
        },
    )

    route_cols = pd.read_csv(gtfs_dir / "routes.txt", nrows=0).columns.tolist()
    wanted_route_cols = ["route_id", "route_type", "route_short_name", "route_long_name"]
    use_route_cols = [col for col in wanted_route_cols if col in route_cols]
    route_dtypes = {
        "route_id": "string",
        "route_type": "Int16",
        "route_short_name": "string",
        "route_long_name": "string",
    }
    routes = pd.read_csv(
        gtfs_dir / "routes.txt",
        usecols=use_route_cols,
        dtype={k: v for k, v in route_dtypes.items() if k in use_route_cols},
    )

    trips = pd.read_csv(
        gtfs_dir / "trips.txt",
        usecols=["trip_id", "route_id"],
        dtype={
            "trip_id": "string",
            "route_id": "string",
        },
    )

    stop_times = pd.read_csv(
        gtfs_dir / "stop_times.txt",
        usecols=["trip_id", "stop_id", "stop_sequence"],
        dtype={
            "trip_id": "string",
            "stop_id": "string",
            "stop_sequence": "Int32",
        },
    )

    return GTFSData(stops=stops, routes=routes, trips=trips, stop_times=stop_times)


def build_pos_all(stops: pd.DataFrame) -> pd.DataFrame:
    cols = ["stop_id", "stop_name", "stop_lat", "stop_lon"]
    df = stops[cols].copy()
    df = df.dropna(subset=["stop_lat", "stop_lon"])
    df["stop_id"] = df["stop_id"].astype(str)
    df["stop_name"] = df["stop_name"].astype(str)
    df["stop_lat"] = df["stop_lat"].astype(float)
    df["stop_lon"] = df["stop_lon"].astype(float)
    return df


def to_pos_dict(pos_all: pd.DataFrame) -> dict[str, tuple[float, float]]:
    return dict(zip(pos_all["stop_id"], zip(pos_all["stop_lon"], pos_all["stop_lat"])))


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (math.sin(dphi / 2) ** 2) + math.cos(phi1) * math.cos(phi2) * (math.sin(dlambda / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


def _empty_edges_df() -> pd.DataFrame:
    return pd.DataFrame(columns=EDGE_COLUMNS)


def _normalize_stop_name(name: str) -> str:
    return re.sub(r"\s+", " ", str(name).strip().lower())


def _distance_lookup(pos_all: pd.DataFrame) -> dict[str, tuple[float, float]]:
    if pos_all is None or pos_all.empty:
        return {}
    coords = pos_all[["stop_id", "stop_lat", "stop_lon"]].copy()
    coords["stop_id"] = coords["stop_id"].astype(str)
    coords["stop_lat"] = coords["stop_lat"].astype(float)
    coords["stop_lon"] = coords["stop_lon"].astype(float)
    return dict(zip(coords["stop_id"], zip(coords["stop_lat"], coords["stop_lon"])))


def _compute_distances_for_pairs(edges_df: pd.DataFrame, coords: dict[str, tuple[float, float]]) -> list[float]:
    distances: list[float] = []
    for row in edges_df.itertuples(index=False):
        a_coords = coords.get(str(row.a))
        b_coords = coords.get(str(row.b))
        if a_coords is None or b_coords is None:
            distances.append(float("nan"))
            continue
        distances.append(_haversine_m(a_coords[0], a_coords[1], b_coords[0], b_coords[1]))
    return distances


def _estimate_ride_time(distance_m: float, modes: list[str]) -> float:
    if pd.isna(distance_m):
        return float("nan")
    speeds = [MODE_SPEED_M_S.get(mode, MODE_SPEED_M_S["other"]) for mode in modes if mode]
    if not speeds:
        speeds = [MODE_SPEED_M_S["other"]]
    best_speed = max(speeds)
    return float(distance_m) / float(best_speed) if best_speed > 0 else float("nan")


def _estimate_transfer_time(distance_m: float, walking_speed_m_s: float) -> float:
    if pd.isna(distance_m) or walking_speed_m_s <= 0:
        return float("nan")
    return float(distance_m) / float(walking_speed_m_s)


def _iter_bucketed_candidate_pairs(
    records: list[dict[str, float | str]],
    radius_m: float,
):
    if radius_m <= 0:
        return
    cell_deg = max(radius_m / 111_320.0, 1e-6)
    buckets: dict[tuple[int, int], list[dict[str, float | str]]] = {}

    for record in sorted(records, key=lambda item: str(item["stop_id"])):
        lat = float(record["stop_lat"])
        lon = float(record["stop_lon"])
        key = (int(math.floor(lat / cell_deg)), int(math.floor(lon / cell_deg)))
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for other in buckets.get((key[0] + dx, key[1] + dy), []):
                    yield other, record
        buckets.setdefault(key, []).append(record)


def build_ride_edges(data: GTFSData, pos_all: pd.DataFrame | None = None) -> pd.DataFrame:
    if pos_all is None:
        pos_all = build_pos_all(data.stops)

    st = data.stop_times[["trip_id", "stop_id", "stop_sequence"]].copy()
    st["trip_id"] = st["trip_id"].astype(str)
    st["stop_id"] = st["stop_id"].astype(str)

    trips = data.trips[["trip_id", "route_id"]].copy()
    trips["trip_id"] = trips["trip_id"].astype(str)
    trips["route_id"] = trips["route_id"].astype(str)

    routes = data.routes[["route_id", "route_type"]].copy()
    routes["route_id"] = routes["route_id"].astype(str)

    merged = st.merge(trips, on="trip_id", how="left").merge(routes, on="route_id", how="left")
    merged = merged.dropna(subset=["route_type"])
    merged["route_type"] = merged["route_type"].astype(int)
    merged["mode"] = merged["route_type"].map(ROUTE_TYPE_TO_MODE).fillna("other")

    merged = merged.sort_values(["trip_id", "stop_sequence"])
    merged["next_stop_id"] = merged.groupby("trip_id")["stop_id"].shift(-1)

    edges = merged.dropna(subset=["next_stop_id"])[["stop_id", "next_stop_id", "mode"]].copy()
    edges = edges[edges["stop_id"] != edges["next_stop_id"]]
    edges.rename(columns={"stop_id": "a", "next_stop_id": "b"}, inplace=True)
    edges["a"] = edges["a"].astype(str)
    edges["b"] = edges["b"].astype(str)
    edges["u"] = edges[["a", "b"]].min(axis=1)
    edges["v"] = edges[["a", "b"]].max(axis=1)

    agg = (
        edges.groupby(["u", "v"])["mode"]
        .agg(lambda s: sorted(set(str(v) for v in s if pd.notna(v))))
        .reset_index()
        .rename(columns={"u": "a", "v": "b", "mode": "mode_list"})
    )

    if agg.empty:
        return _empty_edges_df()

    coords = _distance_lookup(pos_all)
    agg["distance_m"] = _compute_distances_for_pairs(agg[["a", "b"]], coords)
    agg["time_s"] = [
        _estimate_ride_time(distance_m, mode_list)
        for distance_m, mode_list in zip(agg["distance_m"], agg["mode_list"])
    ]
    agg["cost"] = agg["time_s"]
    agg["weight_m"] = agg["distance_m"]
    agg["edge_kind"] = "ride"
    agg["modes"] = agg["mode_list"].apply(lambda items: "|".join(items))
    agg["mode"] = agg["mode_list"].apply(lambda items: items[0] if len(items) == 1 else "multi")

    return agg[EDGE_COLUMNS].reset_index(drop=True)


def build_transfer_edges(
    data: GTFSData,
    pos_all: pd.DataFrame | None = None,
    ride_edges: pd.DataFrame | None = None,
    same_name_transfer_m: float = DEFAULT_SAME_NAME_TRANSFER_M,
    nearby_transfer_m: float = DEFAULT_NEARBY_TRANSFER_M,
    walking_speed_m_s: float = DEFAULT_WALKING_SPEED_M_S,
    transfer_penalty_s: float = DEFAULT_TRANSFER_PENALTY_S,
) -> pd.DataFrame:
    if pos_all is None:
        pos_all = build_pos_all(data.stops)
    if pos_all is None or pos_all.empty:
        return _empty_edges_df()

    stops = pos_all[["stop_id", "stop_name", "stop_lat", "stop_lon"]].copy()
    stops["stop_id"] = stops["stop_id"].astype(str)
    stops["stop_name"] = stops["stop_name"].astype(str)
    stops["normalized_name"] = stops["stop_name"].map(_normalize_stop_name)

    ride_pairs = set()
    if ride_edges is not None and not ride_edges.empty:
        ride_pairs = {
            tuple(sorted((str(row.a), str(row.b))))
            for row in ride_edges[["a", "b"]].itertuples(index=False)
        }

    seen_pairs: set[tuple[str, str]] = set()
    transfer_rows: list[dict[str, float | str]] = []

    def add_transfer(a: str, b: str, distance_m: float):
        u, v = sorted((str(a), str(b)))
        if u == v:
            return
        pair = (u, v)
        if pair in ride_pairs or pair in seen_pairs:
            return
        seen_pairs.add(pair)

        time_s = _estimate_transfer_time(distance_m, walking_speed_m_s)
        cost = time_s + transfer_penalty_s if not pd.isna(time_s) else float("nan")
        transfer_rows.append(
            {
                "a": u,
                "b": v,
                "edge_kind": "transfer",
                "mode": "transfer",
                "modes": "transfer",
                "distance_m": float(distance_m),
                "time_s": float(time_s) if not pd.isna(time_s) else float("nan"),
                "cost": float(cost) if not pd.isna(cost) else float("nan"),
                "weight_m": float(distance_m),
            }
        )

    stop_records = stops.to_dict("records")

    if same_name_transfer_m > 0:
        for _, group in stops.groupby("normalized_name"):
            if len(group) < 2:
                continue
            records = group.to_dict("records")
            for left, right in _iter_bucketed_candidate_pairs(records, same_name_transfer_m):
                distance_m = _haversine_m(
                    float(left["stop_lat"]),
                    float(left["stop_lon"]),
                    float(right["stop_lat"]),
                    float(right["stop_lon"]),
                )
                if distance_m <= same_name_transfer_m:
                    add_transfer(str(left["stop_id"]), str(right["stop_id"]), distance_m)

    if nearby_transfer_m > 0:
        for left, right in _iter_bucketed_candidate_pairs(stop_records, nearby_transfer_m):
            distance_m = _haversine_m(
                float(left["stop_lat"]),
                float(left["stop_lon"]),
                float(right["stop_lat"]),
                float(right["stop_lon"]),
            )
            if distance_m <= nearby_transfer_m:
                add_transfer(str(left["stop_id"]), str(right["stop_id"]), distance_m)

    if not transfer_rows:
        return _empty_edges_df()

    transfer_edges = pd.DataFrame(transfer_rows, columns=EDGE_COLUMNS)
    transfer_edges = transfer_edges.sort_values(["a", "b"]).reset_index(drop=True)
    return transfer_edges


def combine_edges(ride_edges: pd.DataFrame, transfer_edges: pd.DataFrame) -> pd.DataFrame:
    parts = [df[EDGE_COLUMNS].copy() for df in (ride_edges, transfer_edges) if df is not None and not df.empty]
    if not parts:
        return _empty_edges_df()
    combined = pd.concat(parts, ignore_index=True)
    combined["a"] = combined["a"].astype(str)
    combined["b"] = combined["b"].astype(str)
    return combined.sort_values(["edge_kind", "a", "b"]).reset_index(drop=True)


def build_edges_enriched(
    data: GTFSData,
    pos_all: pd.DataFrame | None = None,
    same_name_transfer_m: float = DEFAULT_SAME_NAME_TRANSFER_M,
    nearby_transfer_m: float = DEFAULT_NEARBY_TRANSFER_M,
    walking_speed_m_s: float = DEFAULT_WALKING_SPEED_M_S,
    transfer_penalty_s: float = DEFAULT_TRANSFER_PENALTY_S,
) -> pd.DataFrame:
    """Preferred edge-building entry point with ride and transfer edges."""
    if pos_all is None:
        pos_all = build_pos_all(data.stops)

    ride_edges = build_ride_edges(data, pos_all=pos_all)
    transfer_edges = build_transfer_edges(
        data,
        pos_all=pos_all,
        ride_edges=ride_edges,
        same_name_transfer_m=same_name_transfer_m,
        nearby_transfer_m=nearby_transfer_m,
        walking_speed_m_s=walking_speed_m_s,
        transfer_penalty_s=transfer_penalty_s,
    )
    return combine_edges(ride_edges, transfer_edges)


def build_edges_clean(data: GTFSData, pos_all: pd.DataFrame | None = None, compute_weights: bool = False) -> pd.DataFrame:
    """Backward-compatible wrapper around the enriched edge pipeline."""
    _ = compute_weights  # kept for compatibility with the old caller signature
    return build_edges_enriched(data, pos_all=pos_all)


def _route_label(mode: str, short: str | None, long: str | None) -> str:
    """Return a human-friendly label for a route (UI only)."""
    s = ("" if short is None else str(short)).strip()
    l = ("" if long is None else str(long)).strip()

    if mode == "metro":
        if s:
            return f"Line {s}"
        return l or "Line"

    if mode == "rail":
        if s and len(s) == 1 and s.isalpha():
            return f"RER {s.upper()}"
        if "rer" in l.lower():
            return l
        if s:
            return f"Rail {s}"
        return l or "Rail"

    if mode == "tram":
        if s:
            return f"Tram {s}"
        return l or "Tram"

    if mode == "bus":
        if s:
            return f"Bus {s}"
        return l or "Bus"

    return s or l or mode


def build_stop_lines(data: GTFSData) -> dict[str, dict[str, list[str]]]:
    """Map each stop_id -> {mode: [line labels]} for UI disambiguation."""
    st = data.stop_times[["trip_id", "stop_id"]].copy()
    st["trip_id"] = st["trip_id"].astype(str)
    st["stop_id"] = st["stop_id"].astype(str)

    trips = data.trips[["trip_id", "route_id"]].copy()
    trips["trip_id"] = trips["trip_id"].astype(str)
    trips["route_id"] = trips["route_id"].astype(str)

    routes_cols = ["route_id", "route_type"]
    if "route_short_name" in data.routes.columns:
        routes_cols.append("route_short_name")
    if "route_long_name" in data.routes.columns:
        routes_cols.append("route_long_name")

    routes = data.routes[routes_cols].copy()
    routes["route_id"] = routes["route_id"].astype(str)
    routes["route_type"] = routes["route_type"].astype(int)

    merged = st.merge(trips, on="trip_id", how="left").merge(routes, on="route_id", how="left")
    merged = merged.dropna(subset=["route_type"])

    merged["mode"] = merged["route_type"].map(ROUTE_TYPE_TO_MODE).fillna("other")
    if "route_short_name" not in merged.columns:
        merged["route_short_name"] = ""
    if "route_long_name" not in merged.columns:
        merged["route_long_name"] = ""

    merged["route_short_name"] = merged["route_short_name"].astype(str)
    merged["route_long_name"] = merged["route_long_name"].astype(str)

    merged = merged[["stop_id", "mode", "route_short_name", "route_long_name"]].drop_duplicates()

    out: dict[str, dict[str, set[str]]] = {}
    for r in merged.itertuples(index=False):
        sid = str(r.stop_id)
        mode = str(r.mode)
        label = _route_label(mode, r.route_short_name, r.route_long_name)
        out.setdefault(sid, {}).setdefault(mode, set()).add(label)

    return {sid: {m: sorted(list(labels)) for m, labels in by_mode.items()} for sid, by_mode in out.items()}


def _filter_edges_for_mode(edges_clean: pd.DataFrame, mode: str | None) -> pd.DataFrame:
    if mode is None or edges_clean.empty:
        return edges_clean.copy()

    mode_pattern = rf"(?:^|\|){re.escape(mode)}(?:\||$)"
    ride_mask = (edges_clean["edge_kind"] == "ride") & edges_clean["modes"].fillna("").str.contains(mode_pattern, regex=True)
    ride_df = edges_clean[ride_mask].copy()
    if ride_df.empty:
        return ride_df

    allowed_nodes = set(ride_df["a"]).union(set(ride_df["b"]))
    transfer_mask = (
        (edges_clean["edge_kind"] == "transfer")
        & edges_clean["a"].isin(allowed_nodes)
        & edges_clean["b"].isin(allowed_nodes)
    )
    transfer_df = edges_clean[transfer_mask].copy()
    return pd.concat([ride_df, transfer_df], ignore_index=True)


def _safe_float(value) -> float:
    if pd.isna(value):
        return float("nan")
    return float(value)


def _resolve_edge_attributes(row, selected_mode: str | None) -> dict[str, float | str]:
    distance_m = _safe_float(row.distance_m)
    modes = str(row.modes)
    edge_mode = str(row.mode)
    time_s = _safe_float(row.time_s)
    cost = _safe_float(row.cost)

    if row.edge_kind == "ride" and selected_mode is not None:
        edge_mode = selected_mode
        time_s = _estimate_ride_time(distance_m, [selected_mode])
        cost = time_s

    return {
        "edge_kind": str(row.edge_kind),
        "mode": edge_mode,
        "modes": modes,
        "distance_m": distance_m,
        "time_s": time_s,
        "cost": cost,
        "weight_m": distance_m,
    }


def build_graph(
    edges_clean: pd.DataFrame,
    pos_all: pd.DataFrame | None = None,
    mode: str | None = None,
    stop_lines: dict[str, dict[str, list[str]]] | None = None,
) -> nx.Graph:
    G = nx.Graph()

    df = _filter_edges_for_mode(edges_clean, mode)

    for row in df.itertuples(index=False):
        G.add_edge(str(row.a), str(row.b), **_resolve_edge_attributes(row, mode))

    if pos_all is not None and not pos_all.empty:
        sub = pos_all[pos_all["stop_id"].isin(G.nodes)].copy()
        for r in sub.itertuples(index=False):
            G.nodes[str(r.stop_id)]["stop_name"] = str(r.stop_name)
            G.nodes[str(r.stop_id)]["lat"] = float(r.stop_lat)
            G.nodes[str(r.stop_id)]["lon"] = float(r.stop_lon)

    if stop_lines:
        for sid in list(G.nodes()):
            if sid in stop_lines:
                G.nodes[sid]["lines"] = stop_lines[sid]

    return G


def largest_component(G: nx.Graph) -> nx.Graph:
    if G.number_of_nodes() == 0:
        return G
    comp = max(nx.connected_components(G), key=len)
    return G.subgraph(comp).copy()


def build_graphs_by_mode(edges_clean: pd.DataFrame, pos_all: pd.DataFrame | None = None):
    modes = ["bus", "metro", "rail", "tram", "other"]
    graphs = {"all": build_graph(edges_clean, pos_all=pos_all, mode=None)}
    for m in modes:
        graphs[m] = build_graph(edges_clean, pos_all=pos_all, mode=m)

    graphs_lcc = {k: largest_component(g) for k, g in graphs.items()}
    return graphs, graphs_lcc


def build_graphs_by_mode_with_lines(
    data: GTFSData,
    edges_clean: pd.DataFrame,
    pos_all: pd.DataFrame | None = None,
):
    """Same as build_graphs_by_mode, but enrich nodes with per-mode line labels."""
    stop_lines = build_stop_lines(data)
    modes = ["bus", "metro", "rail", "tram", "other"]
    graphs = {"all": build_graph(edges_clean, pos_all=pos_all, mode=None, stop_lines=stop_lines)}
    for m in modes:
        graphs[m] = build_graph(edges_clean, pos_all=pos_all, mode=m, stop_lines=stop_lines)

    graphs_lcc = {k: largest_component(g) for k, g in graphs.items()}
    return graphs, graphs_lcc