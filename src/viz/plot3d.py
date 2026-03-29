from __future__ import annotations

from collections import deque

import networkx as nx
import plotly.graph_objects as go


RIDE_EDGE_COLOR = "#3b82f6"
TRANSFER_EDGE_COLOR = "#f59e0b"
PATH_EDGE_COLOR = "#ef4444"
DEFAULT_NODE_COLOR = "#6b7280"
MULTI_MODE_COLOR = "#9ca3af"
MODE_COLORS = {
    "bus": "#2563eb",
    "metro": "#7c3aed",
    "rail": "#059669",
    "tram": "#db2777",
    "other": "#64748b",
    "transfer": "#f59e0b",
}


def _node_mode(attrs: dict) -> str:
    lines = attrs.get("lines") or {}
    present_modes = [mode for mode, values in lines.items() if values]
    if len(present_modes) == 1:
        return present_modes[0]
    if len(present_modes) > 1:
        return "multi"
    return "other"


def _node_color(attrs: dict) -> str:
    mode = _node_mode(attrs)
    if mode == "multi":
        return MULTI_MODE_COLOR
    return MODE_COLORS.get(mode, DEFAULT_NODE_COLOR)


def _node_height(degree: int) -> float:
    return float(degree) * 2.0


def _node_size(degree: int) -> float:
    return min(4.0 + float(degree), 18.0)


def _path_edge_set(path: list[str] | None) -> set[tuple[str, str]]:
    if not path or len(path) < 2:
        return set()
    return {
        tuple(sorted((str(path[i]), str(path[i + 1]))))
        for i in range(len(path) - 1)
    }


def _focus_subgraph(G: nx.Graph, path: list[str] | None, max_nodes: int = 5000, hops: int = 2) -> nx.Graph:
    if G.number_of_nodes() <= max_nodes:
        return G

    if not path:
        return G.subgraph(list(G.nodes())[:max_nodes]).copy()

    visited = set(str(node) for node in path if node in G)
    q = deque((str(node), 0) for node in visited)

    while q and len(visited) < max_nodes:
        node, depth = q.popleft()
        if depth >= hops:
            continue
        for nb in G.neighbors(node):
            nb = str(nb)
            if nb not in visited:
                visited.add(nb)
                q.append((nb, depth + 1))
            if len(visited) >= max_nodes:
                break

    return G.subgraph(visited).copy()


def _build_edge_trace(
    G: nx.Graph,
    pos: dict[str, tuple[float, float]],
    edge_pairs: list[tuple[str, str]],
    color: str,
    width: float,
    name: str,
):
    xs: list[float | None] = []
    ys: list[float | None] = []
    zs: list[float | None] = []

    for u, v in edge_pairs:
        if u not in pos or v not in pos:
            continue
        x1, y1 = pos[u]
        x2, y2 = pos[v]
        z1 = _node_height(int(G.degree[u]))
        z2 = _node_height(int(G.degree[v]))
        xs.extend([x1, x2, None])
        ys.extend([y1, y2, None])
        zs.extend([z1, z2, None])

    if not xs:
        return None

    return go.Scatter3d(
        x=xs,
        y=ys,
        z=zs,
        mode="lines",
        line={"color": color, "width": width},
        name=name,
        hoverinfo="skip",
    )


def plot_graph_3d(G: nx.Graph, pos: dict, path: list[str] | None = None):
    H = _focus_subgraph(G, path=path, max_nodes=5000, hops=2)
    path_edges = _path_edge_set(path)

    ride_edges: list[tuple[str, str]] = []
    transfer_edges: list[tuple[str, str]] = []
    highlight_edges: list[tuple[str, str]] = []

    for u, v, data in H.edges(data=True):
        pair = tuple(sorted((str(u), str(v))))
        if pair in path_edges:
            highlight_edges.append((str(u), str(v)))
            continue
        if data.get("edge_kind") == "transfer":
            transfer_edges.append((str(u), str(v)))
        else:
            ride_edges.append((str(u), str(v)))

    edge_traces = [
        _build_edge_trace(H, pos, ride_edges, RIDE_EDGE_COLOR, 2.0, "Ride edges"),
        _build_edge_trace(H, pos, transfer_edges, TRANSFER_EDGE_COLOR, 3.0, "Transfer edges"),
        _build_edge_trace(H, pos, highlight_edges, PATH_EDGE_COLOR, 6.0, "Selected route"),
    ]
    edge_traces = [trace for trace in edge_traces if trace is not None]

    node_x = []
    node_y = []
    node_z = []
    node_size = []
    node_color = []
    hover_text = []

    for node, attrs in H.nodes(data=True):
        sid = str(node)
        if sid not in pos:
            continue
        lon, lat = pos[sid]
        degree = int(H.degree[sid])
        stop_name = attrs.get("stop_name", sid)
        node_x.append(lon)
        node_y.append(lat)
        node_z.append(_node_height(degree))
        node_size.append(_node_size(degree))
        node_color.append(_node_color(attrs))
        hover_text.append(f"{stop_name} | connections: {degree}")

    node_trace = go.Scatter3d(
        x=node_x,
        y=node_y,
        z=node_z,
        mode="markers",
        name="Stops",
        hovertext=hover_text,
        hovertemplate="%{hovertext}<extra></extra>",
        marker={
            "size": node_size,
            "color": node_color,
            "opacity": 0.85,
            "line": {"width": 0.0},
        },
    )

    fig = go.Figure(data=edge_traces + [node_trace])
    fig.update_layout(
        margin={"l": 0, "r": 0, "t": 40, "b": 0},
        scene={
            "xaxis_title": "Longitude",
            "yaxis_title": "Latitude",
            "zaxis_title": "Node importance",
            "aspectmode": "data",
        },
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "left", "x": 0.0},
    )
    return fig
