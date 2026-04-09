"""
Transport / CSPE map rendering — reuses graph bundle and plot_mapbox (same pipeline as Streamlit).
"""

from __future__ import annotations

import os
import sys
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


def graph_for(mode: str, use_lcc: bool) -> Any:
    bundle = get_bundle()
    graphs = bundle["graphs"]
    graphs_lcc = bundle["graphs_lcc"]
    G = (graphs_lcc if use_lcc else graphs)[mode]
    return G


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
) -> tuple[str, str | None]:
    from src.viz.plot_mapbox import render_mapbox_gl_html

    token, token_src = get_mapbox_token()
    if not token:
        raise RuntimeError(
            "Mapbox token missing: set MAPBOX_TOKEN, MAPBOX_API_KEY, or MAPBOX_ACCESS_TOKEN."
        )

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
        suppress_stop_markers=(gv == "station"),
        suppress_base_network=route_focus,
    )
    return map_html, token_src


def search_stops(
    q: str, *, limit: int, mode: str, use_lcc: bool, station_first: bool = False
) -> list[dict[str, Any]]:
    from src.core.queries import search_stations_autocomplete

    G = graph_for(mode, use_lcc)
    idx = station_layer_for(mode, use_lcc)
    matches = search_stations_autocomplete(
        G,
        idx,
        (q or "").strip(),
        limit=limit,
        mode=mode,
        station_compact=station_first,
    )
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
        return {
            "ok": True,
            "routing_scope": "stop",
            "path": path,
            "station_path": station_path,
            "station_names": station_names,
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
        return {
            "ok": True,
            "routing_scope": "station",
            "path": path,
            "station_path": station_path,
            "station_names": station_names,
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
