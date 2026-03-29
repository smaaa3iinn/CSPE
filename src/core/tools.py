from __future__ import annotations

import math
import networkx as nx


def top_hubs(G: nx.Graph, k: int = 10):
    deg = sorted(G.degree, key=lambda x: x[1], reverse=True)[:k]
    out = []
    for n, d in deg:
        name = G.nodes[n].get("stop_name", "")
        out.append({"stop_id": str(n), "stop_name": str(name), "degree": int(d)})
    return out


def show_network(G: nx.Graph, pos: dict, max_edges: int = 60000):
    edges = []
    for i, (a, b, data) in enumerate(G.edges(data=True)):
        if i >= max_edges:
            break
        edges.append(
            {
                "a": str(a),
                "b": str(b),
                "edge_kind": data.get("edge_kind", "ride"),
                "mode": data.get("mode", ""),
                "modes": data.get("modes", ""),
                "distance_m": data.get("distance_m", data.get("weight_m", float("nan"))),
                "time_s": data.get("time_s", float("nan")),
                "cost": data.get("cost", float("nan")),
                "weight_m": data.get("weight_m", float("nan")),
            }
        )

    nodes = []
    for n in G.nodes():
        if n in pos:
            x, y = pos[n]
            nodes.append({"id": str(n), "x": float(x), "y": float(y)})

    return {"nodes": nodes, "edges": edges}


def export_graphxr(
    G: nx.Graph,
    max_nodes: int | None = None,
    max_edges: int = 120000,
    include_lon_lat: bool = True,
):
    nodes_iter = list(G.nodes())
    if max_nodes is not None and len(nodes_iter) > max_nodes:
        nodes_iter = nodes_iter[:max_nodes]
        H = G.subgraph(nodes_iter).copy()
    else:
        H = G

    nodes = []
    for n in H.nodes():
        attrs = H.nodes[n]
        label = attrs.get("stop_name", str(n))

        node_obj = {"id": str(n), "label": str(label), "degree": int(H.degree[n])}

        if include_lon_lat:
            lon = attrs.get("lon", None)
            lat = attrs.get("lat", None)
            if lon is not None and lat is not None:
                node_obj["x"] = float(lon)
                node_obj["y"] = float(lat)
                node_obj["lon"] = float(lon)
                node_obj["lat"] = float(lat)

        nodes.append(node_obj)

    links = []
    for i, (a, b, data) in enumerate(H.edges(data=True)):
        if i >= max_edges:
            break

        w = data.get("weight_m", float("nan"))
        links.append(
            {
                "source": str(a),
                "target": str(b),
                "edge_kind": data.get("edge_kind", "ride"),
                "mode": data.get("mode", ""),
                "modes": data.get("modes", ""),
                "distance_m": _clean_number(data.get("distance_m", w)),
                "time_s": _clean_number(data.get("time_s")),
                "cost": _clean_number(data.get("cost")),
                "weight_m": (float(w) if w is not None and not _is_nan(w) else None),
            }
        )

    return {"nodes": nodes, "links": links}


def _is_nan(x) -> bool:
    try:
        return math.isnan(float(x))
    except Exception:
        return False


def _clean_number(x):
    if x is None or _is_nan(x):
        return None
    return float(x)