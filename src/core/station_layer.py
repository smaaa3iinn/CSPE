"""
Dual-layer transport model: stop-level graph (routing) + station grouping + aggregated station graph.

- Stations group platform/stop nodes via GTFS parent_station when available; otherwise
  transfer-edge connectivity and same normalized name within geographic proximity (never name alone).
- Routing stays on the stop graph; station paths are derived summaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import networkx as nx
import pandas as pd

from src.core.graph_loader import _haversine_m, _normalize_stop_name

# Max distance (m) to merge stops with same normalized name (when no parent_station)
DEFAULT_NAME_PROXIMITY_M = 260.0
# Grid step (~250m) for bucketing candidates
_GRID = 0.003


@dataclass
class StationLayerIndex:
    """station_id -> child stop_ids; each stop maps to exactly one station."""

    stop_to_station: dict[str, str]
    station_to_stops: dict[str, list[str]]
    station_label: dict[str, str]
    station_centroid: dict[str, tuple[float, float]]  # lon, lat
    parent_station_raw: dict[str, str] = field(default_factory=dict)  # stop_id -> parent id from GTFS if any


class UnionFind:
    def __init__(self, items: list[str]) -> None:
        self._p: dict[str, str] = {x: x for x in items}

    def find(self, x: str) -> str:
        if self._p[x] != x:
            self._p[x] = self.find(self._p[x])
        return self._p[x]

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            # stable: tie-break by string order
            if ra < rb:
                self._p[rb] = ra
            else:
                self._p[ra] = rb


def _load_parent_station_map(project_root: Path) -> dict[str, str]:
    """Load stop_id -> parent_station_id from normalized stops parquet if present."""
    candidates = [
        project_root / "data" / "normalized_gtfs" / "stops.parquet",
        project_root / "data" / "normalized" / "gtfs" / "stops.parquet",
    ]
    for path in candidates:
        if not path.is_file():
            continue
        try:
            df = pd.read_parquet(path)
        except Exception:
            continue
        if "stop_id" not in df.columns:
            continue
        out: dict[str, str] = {}
        has_parent = "parent_station" in df.columns
        for row in df.itertuples(index=False):
            sid = str(getattr(row, "stop_id"))
            if has_parent:
                ps = getattr(row, "parent_station", None)
                if ps is not None and str(ps).strip() and str(ps).strip().lower() != "nan":
                    out[sid] = str(ps).strip()
        if out:
            return out
    return {}


def _node_lon_lat(G: nx.Graph, stop_id: str) -> tuple[float, float] | None:
    if stop_id not in G.nodes:
        return None
    attrs = G.nodes[stop_id]
    lon = attrs.get("lon")
    lat = attrs.get("lat")
    if lon is None or lat is None:
        return None
    try:
        return float(lon), float(lat)
    except (TypeError, ValueError):
        return None


def build_station_layer(
    G: nx.Graph,
    *,
    project_root: Path | str | None = None,
    name_proximity_m: float = DEFAULT_NAME_PROXIMITY_M,
) -> StationLayerIndex:
    """
    Build station partition without collapsing the stop graph.

    1) If GTFS parent_station exists, merge each child with its parent key (parent may be synthetic).
    2) Union endpoints of transfer edges (same graph semantics as GTFS transfers / same-name links).
    3) Merge stops with identical normalized name within ``name_proximity_m`` meters.
    """
    project_root = Path(project_root) if project_root else Path(__file__).resolve().parents[2]
    parent_map = _load_parent_station_map(project_root)

    nodes = [str(n) for n in G.nodes()]
    uf = UnionFind(nodes)

    # --- parent_station (GTFS): merge all child stops that list the same parent ---
    by_parent: dict[str, list[str]] = {}
    for sid in nodes:
        p = parent_map.get(sid)
        if p:
            by_parent.setdefault(str(p), []).append(sid)
    for pkey, children in by_parent.items():
        ps = str(pkey)
        if ps in G:
            for c in children:
                uf.union(ps, c)
        if len(children) >= 2:
            base = children[0]
            for other in children[1:]:
                uf.union(base, other)

    # --- transfer connectivity (walk / same-name transfer edges in graph) ---
    for u, v, data in G.edges(data=True):
        ek = str(data.get("edge_kind") or "")
        modes = str(data.get("mode") or data.get("modes") or "")
        if ek == "transfer" or modes == "transfer":
            uf.union(str(u), str(v))

    # --- same normalized name + proximity (never merge on name alone) ---
    by_name: dict[str, list[str]] = {}
    for sid in nodes:
        name = str(G.nodes[sid].get("stop_name") or "")
        key = _normalize_stop_name(name) if name else sid
        by_name.setdefault(key, []).append(sid)

    for _key, group in by_name.items():
        if len(group) < 2:
            continue
        # Grid bucket to limit O(n^2)
        buckets: dict[tuple[int, int], list[str]] = {}
        for sid in group:
            ll = _node_lon_lat(G, sid)
            if ll is None:
                continue
            lon, lat = ll
            bx = int(lon / _GRID)
            by = int(lat / _GRID)
            buckets.setdefault((bx, by), []).append(sid)

        seen: set[tuple[str, str]] = set()
        for (bx, by), members in buckets.items():
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    other = buckets.get((bx + dx, by + dy))
                    if not other:
                        continue
                    for a in members:
                        for b in other:
                            if a >= b:
                                continue
                            pair = (a, b)
                            if pair in seen:
                                continue
                            seen.add(pair)
                            la = _node_lon_lat(G, a)
                            lb = _node_lon_lat(G, b)
                            if not la or not lb:
                                continue
                            d = _haversine_m(la[1], la[0], lb[1], lb[0])
                            if d <= name_proximity_m:
                                uf.union(a, b)

    # --- canonical station ids ---
    components: dict[str, list[str]] = {}
    for sid in nodes:
        root = uf.find(sid)
        components.setdefault(root, []).append(sid)
    for m in components.values():
        m.sort()

    stop_to_station: dict[str, str] = {}
    station_to_stops: dict[str, list[str]] = {}
    station_label: dict[str, str] = {}
    station_centroid: dict[str, tuple[float, float]] = {}

    for _root, members in components.items():
        station_id = f"st:{members[0]}"
        station_to_stops[station_id] = members
        for sid in members:
            stop_to_station[sid] = station_id
        labels = [str(G.nodes[s].get("stop_name") or s) for s in members]
        labels.sort()
        station_label[station_id] = labels[0] if labels else station_id
        acc_lon = acc_lat = 0.0
        npt = 0
        for sid in members:
            ll = _node_lon_lat(G, sid)
            if ll:
                lon, lat = ll
                acc_lon += lon
                acc_lat += lat
                npt += 1
        if npt:
            station_centroid[station_id] = (acc_lon / npt, acc_lat / npt)
        elif members:
            ll = _node_lon_lat(G, members[0])
            station_centroid[station_id] = ll if ll else (0.0, 0.0)

    return StationLayerIndex(
        stop_to_station=stop_to_station,
        station_to_stops=station_to_stops,
        station_label=station_label,
        station_centroid=station_centroid,
        parent_station_raw={k: v for k, v in parent_map.items() if k in stop_to_station},
    )


def aggregate_station_edges(G: nx.Graph, idx: StationLayerIndex) -> list[tuple[str, str, dict[str, Any]]]:
    """Undirected unique station pairs from underlying stop edges (non-ride collapsed to station link)."""
    seen: set[tuple[str, str]] = set()
    out: list[tuple[str, str, dict[str, Any]]] = []
    for u, v, data in G.edges(data=True):
        su, sv = idx.stop_to_station.get(str(u)), idx.stop_to_station.get(str(v))
        if not su or not sv or su == sv:
            continue
        a, b = (su, sv) if su < sv else (sv, su)
        if (a, b) in seen:
            continue
        seen.add((a, b))
        modes = str(data.get("mode") or data.get("modes") or "")
        ek = str(data.get("edge_kind") or "")
        out.append((a, b, {"mode": modes, "edge_kind": ek}))
    return out


def station_path_from_stop_path(path: list[str], idx: StationLayerIndex) -> list[str]:
    out: list[str] = []
    for p in path:
        st = idx.stop_to_station.get(str(p), f"st:{p}")
        if not out or out[-1] != st:
            out.append(st)
    return out


def _path_preference_key(G: nx.Graph, path: list[str]) -> tuple[int, float, float]:
    """Lower is better: hop count, then total distance_m, then time_s (aligned with unweighted SP + edge metrics)."""
    from src.core.queries import summarize_path

    if not path:
        return (0, 0.0, 0.0)
    summary = summarize_path(G, path)
    hops = max(0, len(path) - 1)
    dm = summary.get("distance_m")
    ts = summary.get("time_s")
    return (
        hops,
        float(dm) if dm is not None else float("inf"),
        float(ts) if ts is not None else float("inf"),
    )


def best_stop_path_between_stations(
    G: nx.Graph,
    idx: StationLayerIndex,
    from_station_id: str,
    to_station_id: str,
) -> dict[str, Any]:
    """
    Evaluate every candidate child stop pair (Cartesian product); pick the best path on the stop graph.
    Preference: fewest edges (same as nx.shortest_path on unweighted G), then lowest summed distance_m, then time_s.
    """
    from src.core.queries import shortest_path

    a_stops = [str(x) for x in idx.station_to_stops.get(from_station_id, []) if str(x) in G]
    b_stops = [str(x) for x in idx.station_to_stops.get(to_station_id, []) if str(x) in G]
    if not a_stops or not b_stops:
        return {"ok": False, "reason": "station_not_found", "path": None, "endpoint_pair": None}

    best: list[str] | None = None
    best_key: tuple[int, float, float] | None = None
    best_pair: tuple[str, str] | None = None

    for sa in a_stops:
        for sb in b_stops:
            res = shortest_path(G, sa, sb)
            if not res.get("ok"):
                continue
            pth = [str(x) for x in (res.get("path") or [])]
            key = _path_preference_key(G, pth)
            if best_key is None or key < best_key:
                best_key = key
                best = pth
                best_pair = (sa, sb)

    if not best or best_pair is None:
        return {"ok": False, "reason": "not_connected", "path": None, "endpoint_pair": None}

    return {
        "ok": True,
        "path": best,
        "endpoint_pair": best_pair,
        "reason": "ok",
    }


def station_geojson(
    idx: StationLayerIndex,
    *,
    edges: list[tuple[str, str, dict[str, Any]]],
    selected_station_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Point + line GeoJSON for station-level visualization."""
    sel = (selected_station_id or "").strip() or None
    point_feats: list[dict[str, Any]] = []
    for sid, (lon, lat) in idx.station_centroid.items():
        point_feats.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "station_id": sid,
                    "name": idx.station_label.get(sid, sid),
                    "kind": "station",
                    "is_selected": bool(sel and sid == sel),
                },
            }
        )
    line_feats: list[dict[str, Any]] = []
    for a, b, _meta in edges:
        ca = idx.station_centroid.get(a)
        cb = idx.station_centroid.get(b)
        if not ca or not cb:
            continue
        line_feats.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [list(ca), list(cb)],
                },
                "properties": {"a": a, "b": b},
            }
        )
    return (
        {"type": "FeatureCollection", "features": point_feats},
        {"type": "FeatureCollection", "features": line_feats},
    )


def _collapse_station_path_for_overlay(
    station_path: list[str], idx: StationLayerIndex
) -> list[str]:
    """Keep order; skip unknown ids; drop consecutive duplicates."""
    out: list[str] = []
    prev: str | None = None
    for raw in station_path:
        sid = str(raw).strip()
        if not sid or sid not in idx.station_centroid:
            continue
        if prev == sid:
            continue
        out.append(sid)
        prev = sid
    return out


def station_path_segment_geojson(
    idx: StationLayerIndex,
    station_path: list[str],
    *,
    selected_station_id: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Station overlay limited to an ordered route: centroids + lines between consecutive stations.
    Used after a path is computed so the map does not show the full station graph.
    """
    collapsed = _collapse_station_path_for_overlay(station_path, idx)
    sel = (selected_station_id or "").strip() or None
    point_feats: list[dict[str, Any]] = []
    for sid in collapsed:
        lon_lat = idx.station_centroid.get(sid)
        if not lon_lat:
            continue
        lon, lat = lon_lat
        point_feats.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "station_id": sid,
                    "name": idx.station_label.get(sid, sid),
                    "kind": "station",
                    "is_selected": bool(sel and sid == sel),
                },
            }
        )
    line_feats: list[dict[str, Any]] = []
    for a, b in zip(collapsed, collapsed[1:]):
        ca = idx.station_centroid.get(a)
        cb = idx.station_centroid.get(b)
        if not ca or not cb:
            continue
        line_feats.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [list(ca), list(cb)],
                },
                "properties": {"a": a, "b": b, "kind": "path_segment"},
            }
        )
    return (
        {"type": "FeatureCollection", "features": point_feats},
        {"type": "FeatureCollection", "features": line_feats},
    )
