"""
Transport / CSPE map rendering — graph bundle and plot_mapbox (shared with historical data pipeline).
"""

from __future__ import annotations

import os
import sys
import time
import uuid
import hashlib
import json
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path
from typing import Any

# Repo root = CSPE/ (parent of backend/)
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.station_layer import (
    StationLayerIndex,
    aggregate_station_edges,
    best_stop_path_between_stations,
    build_station_layer,
    station_geojson,
    station_path_from_stop_path,
    station_path_segment_geojson,
)

MAPBOX_ENV_VARS = ("MAPBOX_TOKEN", "MAPBOX_API_KEY", "MAPBOX_ACCESS_TOKEN")

BUNDLE_PATH = ROOT / "data" / "derived" / "routing" / "graph_bundle.pkl"
STOP_POPUP_INDEX_PATH = ROOT / "data" / "derived" / "stops" / "stop_popup_index.parquet"
NETWORK_MAPS_DIR = str(ROOT / "data" / "derived" / "maps")
POI_DATA_PATH = str(ROOT / "data" / "normalized" / "poi" / "poi.parquet")
POI_TREE_PATH = str(ROOT / "data" / "derived" / "indexes" / "poi_balltree.pkl")
POI_NPZ_PATH = str(ROOT / "data" / "derived" / "indexes" / "poi_balltree.npz")
RENDER_GRAPH_PATHS = {
    "all": str(ROOT / "data" / "derived" / "render_graphs" / "all.render_graph.json"),
    "bus": str(ROOT / "data" / "derived" / "render_graphs" / "bus.render_graph.json"),
    "metro": str(ROOT / "data" / "derived" / "render_graphs" / "metro.render_graph.json"),
    "rail": str(ROOT / "data" / "derived" / "render_graphs" / "rail.render_graph.json"),
    "tram": str(ROOT / "data" / "derived" / "render_graphs" / "tram.render_graph.json"),
}
GRAPH3D_SESSION_TTL_S = 30 * 60
_GRAPH3D_SESSIONS: dict[str, tuple[float, dict[str, Any]]] = {}
_GRAPH3D_SYNC: dict[str, tuple[float, str, str]] = {}
GRAPH3D_SYNC_TTL_S = 3600
_MAP_HTML_CACHE_MAX = 24
_MAP_HTML_CACHE: OrderedDict[tuple[Any, ...], tuple[str, str | None]] = OrderedDict()
_MAP_DISK_CACHE_VERSION = "map-html-v2"
MAP_HTML_CACHE_DIR = ROOT / "data" / "derived" / "product_shell" / "map_html_cache"
GRAPH3D_MODE_LAYER_Y = {
    "bus": -960.0,
    "tram": -480.0,
    "rail": 0.0,
    "metro": 480.0,
    "other": 960.0,
    "multi": 1440.0,
}
GRAPH3D_MODE_COLORS = {
    "bus": "#22c55e",
    "tram": "#a855f7",
    "rail": "#f59e0b",
    "metro": "#38bdf8",
    "other": "#94a3b8",
    "multi": "#f472b6",
}


def get_mapbox_token() -> tuple[str | None, str | None]:
    for env_name in MAPBOX_ENV_VARS:
        value = os.getenv(env_name)
        if value and str(value).strip():
            return str(value).strip(), env_name
    return None, None


@lru_cache(maxsize=1)
def get_bundle() -> dict[str, Any]:
    if not BUNDLE_PATH.is_file():
        raise FileNotFoundError(
            f"Graph bundle missing: {BUNDLE_PATH}. Build or download graph data first."
        )
    from src.core.cache_bundle import load_or_build_graph_bundle

    return load_or_build_graph_bundle(
        str(ROOT),
        cache_path=str(BUNDLE_PATH),
        stop_popup_index_path=str(STOP_POPUP_INDEX_PATH),
    )


@lru_cache(maxsize=1)
def _line_geometries():
    from src.viz.plot_mapbox import load_line_geometries

    if not os.path.exists(NETWORK_MAPS_DIR):
        return None
    return load_line_geometries(NETWORK_MAPS_DIR)


@lru_cache(maxsize=1)
def _render_graphs():
    from src.viz.plot_mapbox import load_render_graph

    graphs: dict[str, Any] = {}
    for mode_name, path in RENDER_GRAPH_PATHS.items():
        if os.path.exists(path):
            graphs[mode_name] = load_render_graph(path)
    return graphs or None


@lru_cache(maxsize=1)
def _poi_lookup():
    from src.core.poi_index import load_poi_lookup

    if not os.path.exists(POI_DATA_PATH):
        return None
    tree = POI_TREE_PATH if os.path.exists(POI_TREE_PATH) else None
    npz = POI_NPZ_PATH if os.path.exists(POI_NPZ_PATH) else None
    return load_poi_lookup(POI_DATA_PATH, tree_path=tree, npz_path=npz)


def default_basemap_style() -> str:
    from src.viz.plot_mapbox import DEFAULT_MAPBOX_BASEMAP_STYLE, normalize_mapbox_style_url

    return normalize_mapbox_style_url(
        os.getenv("MAPBOX_STYLE_URL", "").strip() or DEFAULT_MAPBOX_BASEMAP_STYLE
    )


def _map_cache_get(key: tuple[Any, ...]) -> tuple[str, str | None] | None:
    cached = _MAP_HTML_CACHE.get(key)
    if cached is None:
        return None
    _MAP_HTML_CACHE.move_to_end(key)
    return cached


def _map_cache_set(key: tuple[Any, ...], value: tuple[str, str | None]) -> None:
    _MAP_HTML_CACHE[key] = value
    _MAP_HTML_CACHE.move_to_end(key)
    while len(_MAP_HTML_CACHE) > _MAP_HTML_CACHE_MAX:
        _MAP_HTML_CACHE.popitem(last=False)


def _static_map_cacheable(
    *,
    path_stop_ids: list[str] | None,
    path_station_ids: list[str] | None,
    selected_stop_id: str | None,
    selected_station_id: str | None,
    expanded_station_id: str | None,
    poi_category_key: str | None,
) -> bool:
    return not any(
        [
            _tuple_or_empty(path_stop_ids),
            _tuple_or_empty(path_station_ids),
            (selected_stop_id or "").strip(),
            (selected_station_id or "").strip(),
            (expanded_station_id or "").strip(),
            poi_category_key and poi_category_key != "All",
        ]
    )


def _source_mtime_ns(path: str | Path) -> int:
    try:
        return Path(path).stat().st_mtime_ns
    except OSError:
        return 0


def _disk_map_cache_payload(
    cache_key: tuple[Any, ...],
    *,
    token: str,
    token_src: str | None,
) -> dict[str, Any]:
    return {
        "schema": _MAP_DISK_CACHE_VERSION,
        "key": cache_key,
        "token_src": token_src,
        "token_hash": hashlib.sha256(token.encode("utf-8")).hexdigest()[:16],
        "bundle_mtime_ns": _source_mtime_ns(BUNDLE_PATH),
        "render_graph_mtimes": {
            mode_name: _source_mtime_ns(path) for mode_name, path in RENDER_GRAPH_PATHS.items()
        },
    }


def _disk_map_cache_path(payload: dict[str, Any]) -> Path:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return MAP_HTML_CACHE_DIR / f"{digest}.json"


def _disk_map_cache_get(
    cache_key: tuple[Any, ...], *, token: str, token_src: str | None
) -> tuple[str, str | None] | None:
    payload = _disk_map_cache_payload(cache_key, token=token, token_src=token_src)
    path = _disk_map_cache_path(payload)
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    html = data.get("html")
    if not isinstance(html, str):
        return None
    src = data.get("token_src")
    return html, str(src) if src is not None else None


def _disk_map_cache_set(
    cache_key: tuple[Any, ...],
    value: tuple[str, str | None],
    *,
    token: str,
    token_src: str | None,
) -> None:
    payload = _disk_map_cache_payload(cache_key, token=token, token_src=token_src)
    path = _disk_map_cache_path(payload)
    try:
        MAP_HTML_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump({"html": value[0], "token_src": value[1]}, fh, ensure_ascii=False)
        tmp.replace(path)
    except OSError:
        return


def _tuple_or_empty(values: list[str] | None) -> tuple[str, ...]:
    return tuple(str(x) for x in (values or []) if str(x).strip())


def graph_for(mode: str, use_lcc: bool) -> Any:
    bundle = get_bundle()
    graphs = bundle["graphs"]
    graphs_lcc = bundle["graphs_lcc"]
    G = (graphs_lcc if use_lcc else graphs)[mode]
    return G


def _clean_graph3d_sessions(now: float | None = None) -> None:
    ts = time.time() if now is None else now
    expired = [sid for sid, (expires_at, _) in _GRAPH3D_SESSIONS.items() if expires_at <= ts]
    for sid in expired:
        _GRAPH3D_SESSIONS.pop(sid, None)


def _clean_graph3d_sync(now: float | None = None) -> None:
    ts = time.time() if now is None else now
    expired = [cid for cid, (expires_at, _, _) in _GRAPH3D_SYNC.items() if expires_at <= ts]
    for cid in expired:
        _GRAPH3D_SYNC.pop(cid, None)


def _node_label(attrs: dict[str, Any], fallback: str) -> str:
    for key in ("stop_name", "station_name", "name", "label"):
        value = attrs.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return fallback


def _node_lon_lat(attrs: dict[str, Any]) -> tuple[float, float] | None:
    lon = attrs.get("lon", attrs.get("longitude"))
    lat = attrs.get("lat", attrs.get("latitude"))
    if lon is None or lat is None:
        return None
    try:
        return float(lon), float(lat)
    except (TypeError, ValueError):
        return None


def _scaled_positions(raw: list[tuple[str, float, float, int]]) -> dict[str, tuple[float, float, float]]:
    if not raw:
        return {}
    lons = [lon for _, lon, _, _ in raw]
    lats = [lat for _, _, lat, _ in raw]
    lon_mid = (min(lons) + max(lons)) / 2.0
    lat_mid = (min(lats) + max(lats)) / 2.0
    span = max(max(lons) - min(lons), max(lats) - min(lats), 0.0001)
    scale = 180.0 / span
    out: dict[str, tuple[float, float, float]] = {}
    for node_id, lon, lat, degree in raw:
        x = (lon - lon_mid) * scale
        z = -(lat - lat_mid) * scale
        y = min(18.0, max(0.0, float(degree) ** 0.5)) * 0.9
        out[node_id] = (x, y, z)
    return out


def _mode_layer_y(mode_name: str) -> float:
    return GRAPH3D_MODE_LAYER_Y.get(mode_name, GRAPH3D_MODE_LAYER_Y["other"])


def _line_modes(lines: Any) -> list[str]:
    if not isinstance(lines, dict):
        return []
    out: list[str] = []
    for mode_name in ("metro", "rail", "tram", "bus"):
        values = lines.get(mode_name)
        if isinstance(values, (list, tuple, set)) and len(values) > 0:
            out.append(mode_name)
        elif isinstance(values, str) and values.strip():
            out.append(mode_name)
    return out


def _primary_mode_from_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "other"
    winners = sorted(
        counts.items(),
        key=lambda kv: (-kv[1], ("metro", "rail", "tram", "bus", "other").index(kv[0]) if kv[0] in ("metro", "rail", "tram", "bus", "other") else 99),
    )
    return winners[0][0] if winners else "other"


def _node_transport_mode(attrs: dict[str, Any]) -> str:
    modes = _line_modes(attrs.get("lines"))
    if modes:
        return modes[0] if len(modes) == 1 else _primary_mode_from_counts({m: 1 for m in modes})
    mode_value = attrs.get("mode") or attrs.get("modes")
    if mode_value:
        first = str(mode_value).split("|")[0].strip()
        return first if first in GRAPH3D_MODE_LAYER_Y else "other"
    return "other"


def _station_transport_mode(G: Any, stop_ids: list[str]) -> str:
    counts: dict[str, int] = {}
    for stop_id in stop_ids:
        if stop_id not in G:
            continue
        for mode_name in _line_modes(dict(G.nodes[stop_id] or {}).get("lines")):
            counts[mode_name] = counts.get(mode_name, 0) + 1
    return _primary_mode_from_counts(counts)


def _fallback_positions(node_ids: list[str]) -> dict[str, tuple[float, float, float]]:
    import math

    total = max(1, len(node_ids))
    radius = max(30.0, min(160.0, total * 0.06))
    out: dict[str, tuple[float, float, float]] = {}
    for i, node_id in enumerate(node_ids):
        angle = (2.0 * math.pi * i) / total
        layer = (i % 7) - 3
        out[node_id] = (math.cos(angle) * radius, layer * 3.0, math.sin(angle) * radius)
    return out


def _edge_iter(G: Any):
    for item in G.edges(data=True):
        if len(item) == 3:
            u, v, data = item
            yield str(u), str(v), dict(data or {})


def _edge_route_key(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


def _jsonish(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple, set)):
        return [str(v) for v in value]
    return str(value)


def _base_graph3d_metadata(mode: str, use_lcc: bool, graph_viz_mode: str) -> dict[str, Any]:
    bundle = get_bundle()
    return {
        "source": "cspe",
        "mode": mode,
        "use_lcc": use_lcc,
        "graph_viz_mode": graph_viz_mode,
        "cache_version": bundle.get("cache_version"),
    }


@lru_cache(maxsize=24)
def _base_graph3d_project(mode: str, use_lcc: bool, graph_viz_mode: str) -> dict[str, Any]:
    gv = graph_viz_mode if graph_viz_mode in ("stop", "station", "hybrid") else "stop"
    G = graph_for(mode, use_lcc)
    idx = station_layer_for(mode, use_lcc)
    use_station_graph = gv == "station"
    layered_by_transport_mode = mode == "all"

    if use_station_graph:
        station_edges = aggregate_station_edges(G, idx)
        node_ids = sorted(idx.station_to_stops.keys())
        raw_positions = [
            (sid, lon, lat, len(idx.station_to_stops.get(sid, [])))
            for sid, (lon, lat) in idx.station_centroid.items()
            if sid in idx.station_to_stops
        ]
        positions = _scaled_positions(raw_positions) or _fallback_positions(node_ids)
        nodes = []
        for sid in node_ids:
            stop_count = len(idx.station_to_stops.get(sid, []))
            transport_mode = _station_transport_mode(G, idx.station_to_stops.get(sid, []))
            x, y, z = positions.get(sid, (0.0, 0.0, 0.0))
            if layered_by_transport_mode:
                y = _mode_layer_y(transport_mode)
            nodes.append(
                {
                    "id": sid,
                    "label": idx.station_label.get(sid, sid),
                    "x": x,
                    "y": y,
                    "z": z,
                    "color": GRAPH3D_MODE_COLORS.get(transport_mode, GRAPH3D_MODE_COLORS["other"]),
                    "kind": "station",
                    "transport_mode": transport_mode,
                    "layer_y": y,
                    "stop_count": stop_count,
                }
            )
        edges = [
            {
                "id": f"{a}-{b}",
                "source": a,
                "target": b,
                "weight": attrs.get("weight", 1),
                "kind": "station_link",
                "mode": _jsonish(attrs.get("mode")),
                "color": GRAPH3D_MODE_COLORS.get(str(attrs.get("mode") or "other").split("|")[0], "#8b5cf6"),
            }
            for a, b, attrs in station_edges
            if a in positions and b in positions
        ]
    else:
        node_ids = [str(n) for n in G.nodes()]
        raw_positions = []
        for node_id, attrs in G.nodes(data=True):
            sid = str(node_id)
            lon_lat = _node_lon_lat(dict(attrs or {}))
            if lon_lat:
                raw_positions.append((sid, lon_lat[0], lon_lat[1], int(G.degree(node_id))))
        positions = _scaled_positions(raw_positions) or _fallback_positions(node_ids)
        nodes = []
        for node_id, attrs in G.nodes(data=True):
            sid = str(node_id)
            attr = dict(attrs or {})
            x, y, z = positions.get(sid, (0.0, 0.0, 0.0))
            transport_mode = _node_transport_mode(attr)
            if layered_by_transport_mode:
                y = _mode_layer_y(transport_mode)
            nodes.append(
                {
                    "id": sid,
                    "label": _node_label(attr, sid),
                    "x": x,
                    "y": y,
                    "z": z,
                    "color": GRAPH3D_MODE_COLORS.get(transport_mode, GRAPH3D_MODE_COLORS["other"]),
                    "kind": "stop",
                    "transport_mode": transport_mode,
                    "layer_y": y,
                    "station_id": idx.stop_to_station.get(sid),
                    "line": _jsonish(attr.get("line")),
                    "mode": _jsonish(attr.get("mode")),
                }
            )
        edges = []
        for u, v, attrs in _edge_iter(G):
            if u not in positions or v not in positions:
                continue
            edge_mode = str(attrs.get("mode") or attrs.get("modes") or "other").split("|")[0]
            edges.append(
                {
                    "id": f"{u}-{v}",
                    "source": u,
                    "target": v,
                    "weight": attrs.get("weight", attrs.get("distance_m", 1)),
                    "kind": _jsonish(attrs.get("kind")),
                    "mode": _jsonish(attrs.get("mode")),
                    "color": GRAPH3D_MODE_COLORS.get(edge_mode, "#8b5cf6"),
                    "route_ids": _jsonish(attrs.get("route_ids")),
                }
            )

    metadata = _base_graph3d_metadata(mode, use_lcc, gv)
    metadata.update(
        {
            "nodes": len(nodes),
            "edges": len(edges),
            "layout": "cached_geo_3d",
            "large_graph": len(nodes) > 5000 or len(edges) > 10000,
            "layered_by_transport_mode": layered_by_transport_mode,
            "mode_layer_axis": "y",
            "mode_layer_y": GRAPH3D_MODE_LAYER_Y if layered_by_transport_mode else {},
        }
    )
    return {
        "id": f"cspe-{mode}-{gv}-{'lcc' if use_lcc else 'full'}",
        "name": f"CSPE {mode} {gv} graph",
        "metadata": metadata,
        "algorithm": "cached_geo_3d",
        "source_file_name": "CSPE transport graph",
        "graph_data": {"nodes": nodes, "edges": edges, "metadata": metadata},
    }


def create_graph3d_session(
    *,
    mode: str,
    use_lcc: bool,
    graph_viz_mode: str,
    path_stop_ids: list[str] | None,
    path_station_ids: list[str] | None,
    selected_stop_id: str | None = None,
    selected_station_id: str | None = None,
    view_fingerprint: str | None = None,
) -> dict[str, Any]:
    gv = graph_viz_mode if graph_viz_mode in ("stop", "station", "hybrid") else "stop"
    base = _base_graph3d_project(mode, use_lcc, gv)
    stop_path = [str(x) for x in (path_stop_ids or []) if str(x).strip()]
    station_path = [str(x) for x in (path_station_ids or []) if str(x).strip()]
    route_ids = station_path if gv == "station" else stop_path
    route_node_set = set(route_ids)
    route_node_order = {node_id: idx for idx, node_id in enumerate(route_ids)}
    route_edge_order = {
        _edge_route_key(a, b): idx for idx, (a, b) in enumerate(zip(route_ids, route_ids[1:]))
    }

    sel_stop = (selected_stop_id or "").strip() or None
    sel_station = (selected_station_id or "").strip() or None
    select_ids: set[str] = set()
    if gv == "station":
        if sel_station:
            select_ids.add(sel_station)
        elif sel_stop:
            idx = station_layer_for(mode, use_lcc)
            mapped = idx.stop_to_station.get(sel_stop)
            if mapped:
                select_ids.add(mapped)
    else:
        if sel_stop:
            select_ids.add(sel_stop)
        elif sel_station and gv == "hybrid":
            idx = station_layer_for(mode, use_lcc)
            for stop_id in idx.station_to_stops.get(sel_station, []):
                select_ids.add(str(stop_id))

    graph_data = base["graph_data"]
    nodes = []
    for node in graph_data["nodes"]:
        item = dict(node)
        node_id = str(item.get("id") or "")
        on_route = node_id in route_node_set
        is_selected = node_id in select_ids and not on_route
        if on_route:
            item["is_route"] = True
            item["route_index"] = route_node_order.get(node_id, 0)
            item["color"] = "#f97316"
        elif is_selected:
            item["is_selected"] = True
            item["color"] = "#ef4444"
        nodes.append(item)

    edges = []
    for edge in graph_data["edges"]:
        item = dict(edge)
        key = _edge_route_key(str(item["source"]), str(item["target"]))
        if key in route_edge_order:
            item["is_route"] = True
            item["route_index"] = route_edge_order[key]
            item["color"] = "#f97316"
            item["weight"] = max(float(item.get("weight") or 1), 4.0)
        edges.append(item)

    metadata = dict(base["metadata"])
    metadata.update(
        {
            "route_node_count": len(route_ids),
            "route_edge_count": len(route_edge_order),
            "has_route": bool(route_ids),
            "selected_stop_id": sel_stop,
            "selected_station_id": sel_station,
            "selected_node_count": len(select_ids),
        }
    )
    if view_fingerprint:
        metadata["view_fingerprint"] = view_fingerprint
    project = {
        **base,
        "id": f"{base['id']}-{uuid.uuid4().hex[:8]}",
        "metadata": metadata,
        "graph_data": {"nodes": nodes, "edges": edges, "metadata": metadata},
    }

    now = time.time()
    _clean_graph3d_sessions(now)
    session_id = uuid.uuid4().hex
    _GRAPH3D_SESSIONS[session_id] = (now + GRAPH3D_SESSION_TTL_S, project)
    return {"session_id": session_id, "project": project, "expires_in_s": GRAPH3D_SESSION_TTL_S}


def get_graph3d_session(session_id: str) -> dict[str, Any] | None:
    _clean_graph3d_sessions()
    row = _GRAPH3D_SESSIONS.get(str(session_id).strip())
    if not row:
        return None
    return row[1]


def push_graph3d_sync(
    *,
    client_id: str,
    fingerprint: str,
    mode: str,
    use_lcc: bool,
    graph_viz_mode: str,
    path_stop_ids: list[str] | None,
    path_station_ids: list[str] | None,
    selected_stop_id: str | None = None,
    selected_station_id: str | None = None,
) -> dict[str, Any]:
    fp = (fingerprint or "").strip()
    cid = (client_id or "").strip()
    if not cid or not fp:
        raise ValueError("client_id and fingerprint are required for graph3d sync")
    session = create_graph3d_session(
        mode=mode,
        use_lcc=use_lcc,
        graph_viz_mode=graph_viz_mode,
        path_stop_ids=path_stop_ids,
        path_station_ids=path_station_ids,
        selected_stop_id=selected_stop_id,
        selected_station_id=selected_station_id,
        view_fingerprint=fp,
    )
    now = time.time()
    _clean_graph3d_sync(now)
    _GRAPH3D_SYNC[cid] = (now + GRAPH3D_SYNC_TTL_S, session["session_id"], fp)
    return {
        "session_id": session["session_id"],
        "fingerprint": fp,
        "expires_in_s": GRAPH3D_SYNC_TTL_S,
    }


def peek_graph3d_sync(client_id: str, fingerprint: str | None = None) -> dict[str, Any]:
    cid = (client_id or "").strip()
    if not cid:
        return {"changed": False}
    _clean_graph3d_sync()
    row = _GRAPH3D_SYNC.get(cid)
    if not row:
        return {"changed": False}
    _, session_id, fp = row
    known = (fingerprint or "").strip()
    if known and known == fp:
        return {"changed": False, "session_id": session_id, "fingerprint": fp}
    return {"changed": True, "session_id": session_id, "fingerprint": fp}


@lru_cache(maxsize=32)
def station_layer_for(mode: str, use_lcc: bool) -> StationLayerIndex:
    """Cached station grouping for the active stop graph (routing stays stop-level)."""
    G = graph_for(mode, use_lcc)
    return build_station_layer(G, project_root=ROOT)


def render_transport_map_html(
    *,
    mode: str,
    use_lcc: bool,
    viz_mode: str,
    path_stop_ids: list[str] | None,
    selected_stop_id: str | None = None,
    selected_station_id: str | None = None,
    show_transfers: bool,
    poi_radius_m: int,
    poi_limit: int,
    poi_category_key: str | None,
    graph_viz_mode: str = "stop",
    expanded_station_id: str | None = None,
    path_station_ids: list[str] | None = None,
    exploration_overlay: dict[str, Any] | None = None,
) -> tuple[str, str | None]:
    from src.viz.plot_mapbox import render_mapbox_gl_html

    gv_cache = (graph_viz_mode or "stop").strip().lower()
    if gv_cache not in ("stop", "station", "hybrid"):
        gv_cache = "stop"
    cache_key = (
        mode,
        bool(use_lcc),
        viz_mode,
        _tuple_or_empty(path_stop_ids),
        (selected_stop_id or "").strip(),
        (selected_station_id or "").strip(),
        bool(show_transfers),
        int(poi_radius_m),
        int(poi_limit),
        poi_category_key or "",
        gv_cache,
        (expanded_station_id or "").strip(),
        _tuple_or_empty(path_station_ids),
        default_basemap_style(),
        str(exploration_overlay or ""),
    )
    cached = _map_cache_get(cache_key)
    if cached is not None:
        return cached

    token, token_src = get_mapbox_token()
    if not token:
        raise RuntimeError(
            "Mapbox token missing: set MAPBOX_TOKEN, MAPBOX_API_KEY, or MAPBOX_ACCESS_TOKEN."
        )

    use_disk_cache = _static_map_cacheable(
        path_stop_ids=path_stop_ids,
        path_station_ids=path_station_ids,
        selected_stop_id=selected_stop_id,
        selected_station_id=selected_station_id,
        expanded_station_id=expanded_station_id,
        poi_category_key=poi_category_key,
    )
    if exploration_overlay:
        use_disk_cache = False
    if use_disk_cache:
        disk_cached = _disk_map_cache_get(cache_key, token=token, token_src=token_src)
        if disk_cached is not None:
            _map_cache_set(cache_key, disk_cached)
            return disk_cached

    G = graph_for(mode, use_lcc)
    idx = station_layer_for(mode, use_lcc)
    gv = (graph_viz_mode or "stop").strip().lower()
    if gv not in ("stop", "station", "hybrid"):
        gv = "stop"
    path_st = [str(x).strip() for x in (path_station_ids or []) if str(x).strip()]
    route_focus = bool(path_st)
    if gv == "stop":
        st_pts = {"type": "FeatureCollection", "features": []}
        st_lines = {"type": "FeatureCollection", "features": []}
    else:
        st_sel = (selected_station_id or "").strip() or None
        if path_st:
            st_pts, st_lines = station_path_segment_geojson(
                idx, path_st, selected_station_id=st_sel
            )
        else:
            st_edges = aggregate_station_edges(G, idx)
            st_pts, st_lines = station_geojson(idx, edges=st_edges, selected_station_id=st_sel)
    pitched = viz_mode == "network_3d"
    cat = None if not poi_category_key or poi_category_key == "All" else poi_category_key

    sel = (selected_stop_id or "").strip() or None

    map_html, _dbg = render_mapbox_gl_html(
        G,
        mapbox_token=token,
        mode=mode,
        path=path_stop_ids,
        selected_stop_id=sel,
        selected_station_id=(selected_station_id or "").strip() or None,
        show_transfers=show_transfers,
        title=f"Mode: {mode} {'(LCC)' if use_lcc else ''}",
        basemap_style=default_basemap_style(),
        line_geometries=_line_geometries(),
        render_graphs_by_mode=_render_graphs(),
        poi_lookup=_poi_lookup(),
        poi_radius_m=float(poi_radius_m if not pitched else poi_radius_m),
        poi_limit=int(poi_limit if not pitched else poi_limit),
        poi_category_key=cat,
        pitched_view=pitched,
        show_3d_buildings=pitched,
        height_px=1100,
        overlay_controls_html="",
        graph_viz_mode=gv,
        expanded_station_id=(expanded_station_id or "").strip() or None,
        station_network_points=st_pts,
        station_network_lines=st_lines,
        suppress_stop_markers=(gv == "station") or bool(exploration_overlay),
        suppress_base_network=route_focus,
        station_layer_index=idx if gv != "stop" else None,
        exploration_overlay=exploration_overlay,
    )
    result = (map_html, token_src)
    _map_cache_set(cache_key, result)
    if use_disk_cache:
        _disk_map_cache_set(cache_key, result, token=token, token_src=token_src)
    return result


def build_transport_route_overlay(
    *,
    mode: str,
    use_lcc: bool,
    graph_viz_mode: str = "stop",
    path_stop_ids: list[str] | None = None,
    path_station_ids: list[str] | None = None,
    selected_stop_id: str | None = None,
    selected_station_id: str | None = None,
) -> dict[str, Any]:
    """Lightweight route payload for patching a live Mapbox iframe."""
    from src.viz.plot_mapbox import _center_and_zoom_for_stop_path, _path_feature_collection

    G = graph_for(mode, use_lcc)
    stop_path = [str(x).strip() for x in (path_stop_ids or []) if str(x).strip()]
    station_path = [str(x).strip() for x in (path_station_ids or []) if str(x).strip()]
    gv = (graph_viz_mode or "stop").strip().lower()
    if gv not in ("stop", "station", "hybrid"):
        gv = "stop"

    path_source, _path_debug = _path_feature_collection(
        G,
        stop_path,
        mode,
        _line_geometries(),
    )
    station_points: dict[str, Any] = {"type": "FeatureCollection", "features": []}
    station_lines: dict[str, Any] = {"type": "FeatureCollection", "features": []}
    if station_path and gv != "stop":
        idx = station_layer_for(mode, use_lcc)
        station_points, station_lines = station_path_segment_geojson(
            idx,
            station_path,
            selected_station_id=(selected_station_id or "").strip() or None,
        )

    fit = _center_and_zoom_for_stop_path(G, stop_path)
    view = None
    if fit:
        center, zoom = fit
        view = {"lat": float(center["lat"]), "lon": float(center["lon"]), "zoom": float(zoom)}

    return {
        "route": {
            "path": path_source,
            "station_network_points": station_points,
            "station_network_lines": station_lines,
            "selected_stop_id": (selected_stop_id or "").strip() or None,
            "selected_station_id": (selected_station_id or "").strip() or None,
            "path_stop_count": len(stop_path),
            "path_station_count": len(station_path),
        },
        "view": view,
    }


def search_stops(
    q: str,
    *,
    limit: int,
    mode: str,
    use_lcc: bool,
    station_first: bool = False,
    fallback_lcc: bool = True,
    mode_fallback: bool = True,
) -> list[dict[str, Any]]:
    from src.core.queries import search_stations_autocomplete

    def _run(search_mode: str, lcc: bool) -> list[dict[str, Any]]:
        G = graph_for(search_mode, lcc)
        idx = station_layer_for(search_mode, lcc)
        matches = search_stations_autocomplete(
            G,
            idx,
            (q or "").strip(),
            limit=limit,
            mode=search_mode if search_mode != "all" else mode,
            station_compact=station_first,
        )
        return _format_search_matches(matches, station_first=station_first)

    lcc_order: list[bool] = []
    if use_lcc:
        lcc_order.append(True)
    if fallback_lcc or not use_lcc:
        lcc_order.append(False)
    if not lcc_order:
        lcc_order = [False]

    for lcc in lcc_order:
        out = _run(mode, lcc)
        if out:
            return out

    if mode not in ("all", "") and mode_fallback:
        for lcc in lcc_order:
            out = _run("all", lcc)
            if out:
                return out
    return []


def _format_search_matches(
    matches: list[dict[str, Any]], *, station_first: bool
) -> list[dict[str, Any]]:
    out = []
    for m in matches:
        if not isinstance(m, dict):
            continue
        row = {
            "stop_id": m.get("stop_id"),
            "stop_name": m.get("stop_name"),
            "line": m.get("line"),
            "station_id": m.get("station_id"),
            "station_name": m.get("station_name"),
            "primary_stop_id": m.get("primary_stop_id"),
            "stop_ids": m.get("stop_ids"),
        }
        if station_first:
            row.pop("primary_stop_id", None)
            row["stop_id"] = None
        out.append(row)
    return out


def _route_path_details(
    G: Any,
    path: list[str],
    *,
    mode: str,
    idx: Any | None = None,
) -> dict[str, Any]:
    from src.core.path_legs import describe_path_legs

    detail = describe_path_legs(G, path, station_idx=idx, current_mode=mode)
    return {
        "path_legs": detail["legs"],
        "path_summary": detail["text_lines"],
    }


def compute_route(
    from_stop_id: str, to_stop_id: str, *, mode: str, use_lcc: bool
) -> dict[str, Any]:
    from src.core.queries import component_info, shortest_path

    G = graph_for(mode, use_lcc)
    idx = station_layer_for(mode, use_lcc)
    a, b = str(from_stop_id).strip(), str(to_stop_id).strip()
    a_info = component_info(G, a)
    b_info = component_info(G, b)
    res = shortest_path(G, a, b)
    if res["ok"]:
        path = res.get("path") or []
        station_path = station_path_from_stop_path([str(x) for x in path], idx) if path else []
        station_names = [idx.station_label.get(sid, sid) for sid in station_path]
        path_details = _route_path_details(G, [str(x) for x in path], mode=mode, idx=idx)
        return {
            "ok": True,
            "routing_scope": "stop",
            "path": path,
            "station_path": station_path,
            "station_names": station_names,
            "path_legs": path_details["path_legs"],
            "path_summary": path_details["path_summary"],
            "result": {
                "distance_m": res.get("distance_m"),
                "time_s": res.get("time_s"),
                "transfers": res.get("transfers"),
            },
            "detail": None,
            "error": None,
        }
    details: list[str] = []
    message = "Path computation failed."
    reason = res.get("reason")
    if reason == "not_connected":
        message = "No path: the two stops are not connected in this graph."
        details = [
            f"Start component size: {a_info.get('component_size', 0)}",
            f"End component size: {b_info.get('component_size', 0)}",
        ]
    elif reason == "start_not_found":
        message = "Start stop not found in the current graph."
    elif reason == "end_not_found":
        message = "End stop not found in the current graph."
    return {
        "ok": False,
        "routing_scope": "stop",
        "path": None,
        "station_path": None,
        "station_names": None,
        "result": None,
        "detail": None,
        "error": {"message": message, "details": details, "reason": reason},
    }


def compute_route_stations(
    from_station_id: str, to_station_id: str, *, mode: str, use_lcc: bool
) -> dict[str, Any]:
    from src.core.queries import component_info, summarize_path

    G = graph_for(mode, use_lcc)
    idx = station_layer_for(mode, use_lcc)
    fs, ts = str(from_station_id).strip(), str(to_station_id).strip()

    a_stops = [s for s in idx.station_to_stops.get(fs, []) if s in G]
    b_stops = [s for s in idx.station_to_stops.get(ts, []) if s in G]
    if not a_stops:
        return {
            "ok": False,
            "routing_scope": "station",
            "path": None,
            "station_path": None,
            "station_names": None,
            "result": None,
            "detail": None,
            "error": {
                "message": "Start station not found in the current graph.",
                "details": [],
                "reason": "start_station_not_found",
            },
        }
    if not b_stops:
        return {
            "ok": False,
            "routing_scope": "station",
            "path": None,
            "station_path": None,
            "station_names": None,
            "result": None,
            "detail": None,
            "error": {
                "message": "End station not found in the current graph.",
                "details": [],
                "reason": "end_station_not_found",
            },
        }

    a0, b0 = sorted(a_stops)[0], sorted(b_stops)[0]
    a_info, b_info = component_info(G, a0), component_info(G, b0)

    res = best_stop_path_between_stations(G, idx, fs, ts)
    if res.get("ok"):
        path = res.get("path") or []
        pair = res.get("endpoint_pair") or (None, None)
        summary = summarize_path(G, [str(x) for x in path])
        station_path = station_path_from_stop_path([str(x) for x in path], idx)
        station_names = [idx.station_label.get(sid, sid) for sid in station_path]
        entry, exit_ = (pair[0], pair[1]) if pair and pair[0] and pair[1] else (None, None)
        path_details = _route_path_details(G, [str(x) for x in path], mode=mode, idx=idx)
        return {
            "ok": True,
            "routing_scope": "station",
            "path": path,
            "station_path": station_path,
            "station_names": station_names,
            "path_legs": path_details["path_legs"],
            "path_summary": path_details["path_summary"],
            "result": {
                "distance_m": summary.get("distance_m"),
                "time_s": summary.get("time_s"),
                "transfers": summary.get("transfers"),
            },
            "detail": {"entry_stop_id": entry, "exit_stop_id": exit_},
            "error": None,
        }

    reason = res.get("reason")
    details: list[str] = []
    message = "Path computation failed."
    if reason == "not_connected":
        message = "No path: the two stations are not connected in this graph."
        details = [
            f"Start component size: {a_info.get('component_size', 0)}",
            f"End component size: {b_info.get('component_size', 0)}",
        ]
    return {
        "ok": False,
        "routing_scope": "station",
        "path": None,
        "station_path": None,
        "station_names": None,
        "result": None,
        "detail": None,
        "error": {"message": message, "details": details, "reason": reason or "not_connected"},
    }


def graph_stats(mode: str, use_lcc: bool) -> tuple[int, int]:
    G = graph_for(mode, use_lcc)
    return G.number_of_nodes(), G.number_of_edges()
