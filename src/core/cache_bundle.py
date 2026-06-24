from __future__ import annotations

from pathlib import Path
import pickle
from typing import Any

import networkx as nx
import pandas as pd

from src.core.graph_loader import EDGE_COLUMNS, build_graphs_by_mode

CACHE_VERSION = 6
GRAPH_MODES = ("all", "all_mb", "metro", "rail", "tram", "bus", "other")


def _default_bundle_path(project_root: str | Path) -> Path:
    project_root = Path(project_root)
    if project_root.suffix == ".pkl":
        return project_root
    return project_root / "data" / "derived" / "routing" / "graph_bundle.pkl"


def _default_stop_popup_index_path(bundle_path: str | Path) -> Path:
    bundle_path = Path(bundle_path)
    return bundle_path.parent.parent / "stops" / "stop_popup_index.parquet"


def _split_lines(raw_value: Any) -> list[str]:
    text = str(raw_value or "").strip()
    if not text:
        return []
    return [part.strip() for part in text.split("|") if part.strip()]


def _load_stop_popup_index(path: str | Path) -> dict[str, dict[str, Any]]:
    df = pd.read_parquet(path)
    out: dict[str, dict[str, Any]] = {}
    for row in df.itertuples(index=False):
        stop_id = str(row.stop_id)
        out[stop_id] = {
            "stop_id": stop_id,
            "stop_name": str(row.stop_name or stop_id),
            "lat": float(row.lat),
            "lon": float(row.lon),
            "primary_mode": str(row.primary_mode or "other"),
            "modes_display": str(row.modes or ""),
            "lines": {
                "metro": _split_lines(row.metro_lines),
                "rail": _split_lines(row.rail_lines),
                "tram": _split_lines(row.tram_lines),
                "bus": _split_lines(row.bus_lines),
            },
            "connections_precomputed": int(row.connections or 0),
        }
    return out


def _node_attrs(
    stop_id: str,
    *,
    stop_popup_index: dict[str, dict[str, Any]],
    pos_all: dict[str, tuple[float, float]],
) -> dict[str, Any]:
    popup = dict(stop_popup_index.get(stop_id, {}))
    lon_lat = pos_all.get(stop_id)
    lon = None if lon_lat is None else float(lon_lat[0])
    lat = None if lon_lat is None else float(lon_lat[1])
    popup.setdefault("stop_id", stop_id)
    popup.setdefault("stop_name", stop_id)
    popup.setdefault("lat", lat)
    popup.setdefault("lon", lon)
    popup.setdefault("lines", {"metro": [], "rail": [], "tram": [], "bus": []})
    return popup


def _edge_has_enriched_format(edges_clean: list[dict[str, Any]]) -> bool:
    if not edges_clean:
        return False
    sample = edges_clean[0]
    if str(sample.get("edge_kind") or "").strip():
        return True
    return "a" in sample and "b" in sample


def _edges_list_to_dataframe(edges_clean: list[dict[str, Any]]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for edge in edges_clean:
        a = str(edge.get("a") or edge.get("source") or "")
        b = str(edge.get("b") or edge.get("target") or "")
        if not a or not b or a == b:
            continue
        edge_kind = str(edge.get("edge_kind") or "ride")
        mode = str(edge.get("mode") or edge.get("edge_mode") or "other")
        modes = str(edge.get("modes") or mode)
        route_ids = edge.get("route_ids")
        if route_ids is None and edge.get("route_id"):
            route_ids = [str(edge.get("route_id"))]
        if not isinstance(route_ids, list):
            route_ids = []
        route_labels = edge.get("route_labels")
        if not isinstance(route_labels, list):
            route_labels = []
        route_refs = edge.get("route_refs")
        if not isinstance(route_refs, list):
            route_refs = []
        rows.append(
            {
                "a": a,
                "b": b,
                "edge_kind": edge_kind,
                "mode": mode,
                "modes": modes,
                "route_ids": route_ids,
                "route_labels": route_labels,
                "route_refs": route_refs,
                "distance_m": edge.get("distance_m", float("nan")),
                "time_s": edge.get("time_s", float("nan")),
                "cost": edge.get("cost", float("nan")),
                "weight_m": edge.get("weight_m", edge.get("distance_m", float("nan"))),
            }
        )
    if not rows:
        return pd.DataFrame(columns=EDGE_COLUMNS)
    return pd.DataFrame(rows, columns=EDGE_COLUMNS)


def _pos_dict_to_dataframe(
    pos_all: dict[str, tuple[float, float]],
    stop_popup_index: dict[str, dict[str, Any]],
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for stop_id, coords in pos_all.items():
        popup = stop_popup_index.get(str(stop_id), {})
        rows.append(
            {
                "stop_id": str(stop_id),
                "stop_name": str(popup.get("stop_name") or stop_id),
                "stop_lat": float(coords[1]),
                "stop_lon": float(coords[0]),
            }
        )
    return pd.DataFrame(rows)


def _apply_popup_index_to_graphs(
    graphs: dict[str, nx.Graph],
    *,
    stop_popup_index: dict[str, dict[str, Any]],
    pos_all: dict[str, tuple[float, float]],
) -> None:
    for graph in graphs.values():
        for stop_id in list(graph.nodes()):
            graph.nodes[stop_id].update(
                _node_attrs(str(stop_id), stop_popup_index=stop_popup_index, pos_all=pos_all)
            )


def _edge_aggregates(edges_clean: list[dict[str, Any]]) -> dict[str, dict[tuple[str, str], dict[str, Any]]]:
    aggregates: dict[str, dict[tuple[str, str], dict[str, Any]]] = {mode: {} for mode in GRAPH_MODES}

    for edge in edges_clean:
        source = str(edge.get("a") or edge.get("source") or "")
        target = str(edge.get("b") or edge.get("target") or "")
        if str(edge.get("edge_kind") or "ride") != "ride":
            continue
        mode = str(edge.get("mode") or "other")
        route_id = str(edge.get("route_id") or "").strip()
        route_ids = edge.get("route_ids") or []
        if not route_id and isinstance(route_ids, list) and route_ids:
            route_id = str(route_ids[0])
        if not source or not target or source == target:
            continue

        key = tuple(sorted((source, target)))
        buckets = ["all"]
        if mode != "bus":
            buckets.append("all_mb")
        if mode not in buckets:
            buckets.append(mode)
        for bucket in buckets:
            aggregate = aggregates[bucket].setdefault(
                key,
                {
                    "modes": set(),
                    "route_ids": set(),
                    "route_refs": [],
                },
            )
            aggregate["modes"].add(mode)
            if route_id:
                aggregate["route_ids"].add(route_id)
                route_ref = {
                    "mode": mode,
                    "route_id": route_id,
                    "route_short_name": "",
                    "route_long_name": "",
                    "route_label": "",
                }
                if route_ref not in aggregate["route_refs"]:
                    aggregate["route_refs"].append(route_ref)

    return aggregates


def _build_graph(
    adjacency: dict[str, list[str]],
    *,
    mode: str,
    stop_popup_index: dict[str, dict[str, Any]],
    pos_all: dict[str, tuple[float, float]],
    edge_aggregates: dict[tuple[str, str], dict[str, Any]],
) -> nx.Graph:
    G = nx.Graph()

    for stop_id in adjacency:
        stop_id = str(stop_id)
        G.add_node(stop_id, **_node_attrs(stop_id, stop_popup_index=stop_popup_index, pos_all=pos_all))

    for source, neighbors in adjacency.items():
        source = str(source)
        if source not in G:
            G.add_node(source, **_node_attrs(source, stop_popup_index=stop_popup_index, pos_all=pos_all))
        for target in neighbors:
            target = str(target)
            if target not in G:
                G.add_node(target, **_node_attrs(target, stop_popup_index=stop_popup_index, pos_all=pos_all))
            key = tuple(sorted((source, target)))
            aggregate = edge_aggregates.get(key, {"modes": {mode}, "route_ids": set(), "route_refs": []})
            modes = sorted(str(value) for value in aggregate["modes"])
            edge_mode = modes[0] if len(modes) == 1 else ("multi" if len(modes) > 1 else mode)
            G.add_edge(
                source,
                target,
                edge_kind="ride",
                mode=edge_mode,
                modes="|".join(modes) if modes else edge_mode,
                route_ids=sorted(str(value) for value in aggregate["route_ids"]),
                route_labels=[],
                route_refs=[dict(ref) for ref in aggregate["route_refs"]],
                distance_m=float("nan"),
                time_s=float("nan"),
                cost=float("nan"),
                weight_m=float("nan"),
            )

    return G


def _build_graphs_from_enriched_edges(
    edges_clean: list[dict[str, Any]],
    *,
    stop_popup_index: dict[str, dict[str, Any]],
    pos_all: dict[str, tuple[float, float]],
) -> tuple[dict[str, nx.Graph], dict[str, nx.Graph]]:
    edges_df = _edges_list_to_dataframe(edges_clean)
    pos_df = _pos_dict_to_dataframe(pos_all, stop_popup_index)
    graphs, graphs_lcc = build_graphs_by_mode(edges_df, pos_df)
    _apply_popup_index_to_graphs(graphs, stop_popup_index=stop_popup_index, pos_all=pos_all)
    _apply_popup_index_to_graphs(graphs_lcc, stop_popup_index=stop_popup_index, pos_all=pos_all)
    return graphs, graphs_lcc


def _build_bundle(bundle_path: str | Path, stop_popup_index_path: str | Path) -> dict[str, Any]:
    with Path(bundle_path).open("rb") as fh:
        raw_bundle = pickle.load(fh)

    pos_all = {str(stop_id): (float(coords[0]), float(coords[1])) for stop_id, coords in (raw_bundle.get("pos_all") or {}).items()}
    edges_clean = [dict(edge) for edge in list(raw_bundle.get("edges_clean") or [])]
    stop_popup_index = _load_stop_popup_index(stop_popup_index_path)

    if _edge_has_enriched_format(edges_clean):
        graphs, graphs_lcc = _build_graphs_from_enriched_edges(
            edges_clean,
            stop_popup_index=stop_popup_index,
            pos_all=pos_all,
        )
    else:
        raw_graphs = raw_bundle.get("graphs") or {}
        edge_aggregates = _edge_aggregates(edges_clean)
        graphs = {}
        for mode in GRAPH_MODES:
            adjacency = raw_graphs.get(mode) or {}
            graphs[mode] = _build_graph(
                adjacency,
                mode=mode,
                stop_popup_index=stop_popup_index,
                pos_all=pos_all,
                edge_aggregates=edge_aggregates.get(mode, {}),
            )
        graphs_lcc = {mode: _largest_connected_component_graph(graph) for mode, graph in graphs.items()}

    return {
        "cache_version": CACHE_VERSION,
        "pos_all": pos_all,
        "edges_clean": edges_clean,
        "graphs": graphs,
        "graphs_lcc": graphs_lcc,
    }


def _largest_connected_component_graph(G: nx.Graph) -> nx.Graph:
    if G.number_of_nodes() == 0:
        return G.copy()
    components = list(nx.connected_components(G))
    if not components:
        return G.copy()
    largest = max(components, key=len)
    return G.subgraph(largest).copy()


def load_or_build_graph_bundle(
    project_root_or_bundle_path: str | Path,
    cache_path: str | Path | None = None,
    force_rebuild: bool = False,
    stop_popup_index_path: str | Path | None = None,
) -> dict[str, Any]:
    del force_rebuild

    bundle_path = Path(cache_path) if cache_path is not None else _default_bundle_path(project_root_or_bundle_path)
    popup_path = Path(stop_popup_index_path) if stop_popup_index_path is not None else _default_stop_popup_index_path(bundle_path)
    return _build_bundle(bundle_path, popup_path)
