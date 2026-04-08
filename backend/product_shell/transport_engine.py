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
    from src.viz.plot_mapbox import normalize_mapbox_style_url

    return normalize_mapbox_style_url(
        os.getenv("MAPBOX_STYLE_URL", "").strip() or "mapbox://styles/smaaa3iin/cmnkb703u002001sh48945ojt"
    )


def graph_for(mode: str, use_lcc: bool) -> Any:
    bundle = get_bundle()
    graphs = bundle["graphs"]
    graphs_lcc = bundle["graphs_lcc"]
    G = (graphs_lcc if use_lcc else graphs)[mode]
    return G


def render_transport_map_html(
    *,
    mode: str,
    use_lcc: bool,
    viz_mode: str,
    path_stop_ids: list[str] | None,
    show_transfers: bool,
    poi_radius_m: int,
    poi_limit: int,
    poi_category_key: str | None,
) -> tuple[str, str | None]:
    from src.viz.plot_mapbox import render_mapbox_gl_html

    token, token_src = get_mapbox_token()
    if not token:
        raise RuntimeError(
            "Mapbox token missing: set MAPBOX_TOKEN, MAPBOX_API_KEY, or MAPBOX_ACCESS_TOKEN."
        )

    G = graph_for(mode, use_lcc)
    pitched = viz_mode == "network_3d"
    cat = None if not poi_category_key or poi_category_key == "All" else poi_category_key

    map_html, _dbg = render_mapbox_gl_html(
        G,
        mapbox_token=token,
        mode=mode,
        path=path_stop_ids,
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
    )
    return map_html, token_src


def search_stops(q: str, *, limit: int, mode: str, use_lcc: bool) -> list[dict[str, Any]]:
    from src.core.queries import search_stops_autocomplete

    G = graph_for(mode, use_lcc)
    matches = search_stops_autocomplete(G, (q or "").strip(), limit=limit, mode=mode)
    out = []
    for m in matches:
        if not isinstance(m, dict):
            continue
        out.append(
            {
                "stop_id": m.get("stop_id"),
                "stop_name": m.get("stop_name"),
                "line": m.get("line"),
            }
        )
    return out


def compute_route(
    from_stop_id: str, to_stop_id: str, *, mode: str, use_lcc: bool
) -> dict[str, Any]:
    from src.core.queries import component_info, shortest_path

    G = graph_for(mode, use_lcc)
    a, b = str(from_stop_id).strip(), str(to_stop_id).strip()
    a_info = component_info(G, a)
    b_info = component_info(G, b)
    res = shortest_path(G, a, b)
    if res["ok"]:
        return {
            "ok": True,
            "path": res.get("path"),
            "result": {
                "distance_m": res.get("distance_m"),
                "time_s": res.get("time_s"),
                "transfers": res.get("transfers"),
            },
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
        "path": None,
        "result": None,
        "error": {"message": message, "details": details, "reason": reason},
    }


def graph_stats(mode: str, use_lcc: bool) -> tuple[int, int]:
    G = graph_for(mode, use_lcc)
    return G.number_of_nodes(), G.number_of_edges()
