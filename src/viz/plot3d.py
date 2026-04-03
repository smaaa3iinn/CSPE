from __future__ import annotations

from collections import deque
import math

import networkx as nx
import plotly.graph_objects as go

MODE_COLORS = {
    "bus": "#2563eb",
    "tram": "#db2777",
    "metro": "#7c3aed",
    "rail": "#059669",
    "other": "#64748b",
    "multi": "#94a3b8",
    "transfer": "#f59e0b",
    "path": "#ef4444",
    "focus": "#facc15",
}

MODE_LAYERS_Z = {
    "bus": 0.0,
    "tram": 0.8,
    "metro": 1.8,
    "rail": 2.8,
    "other": 0.4,
    "multi": 2.2,
    "transfer": 0.6,
}


def _split_modes(raw_modes: str | None) -> list[str]:
    if raw_modes is None:
        return []
    return [part for part in str(raw_modes).split("|") if part]


def _path_edge_set(path: list[str] | None) -> set[tuple[str, str]]:
    if not path or len(path) < 2:
        return set()
    return {
        tuple(sorted((str(path[idx]), str(path[idx + 1]))))
        for idx in range(len(path) - 1)
    }


def _local_map_positions(
    H: nx.Graph,
    pos: dict[str, tuple[float, float]],
) -> dict[str, tuple[float, float]]:
    visible_points: list[tuple[str, float, float]] = []
    for node in H.nodes():
        sid = str(node)
        if sid not in pos:
            continue
        lon, lat = pos[sid]
        visible_points.append((sid, float(lon), float(lat)))

    if not visible_points:
        return {}

    center_lon = sum(lon for _sid, lon, _lat in visible_points) / len(visible_points)
    center_lat = sum(lat for _sid, _lon, lat in visible_points) / len(visible_points)

    lat_km_per_deg = 111.32
    lon_km_per_deg = 111.32 * max(0.2, abs(math.cos(math.radians(center_lat))))

    local_pos: dict[str, tuple[float, float]] = {}
    for sid, lon, lat in visible_points:
        x = (lon - center_lon) * lon_km_per_deg
        y = (lat - center_lat) * lat_km_per_deg
        local_pos[sid] = (x, y)

    return local_pos


def _seed_nodes(G: nx.Graph, focus_nodes: list[str] | None = None, path: list[str] | None = None) -> list[str]:
    seeds: list[str] = []

    for source in (focus_nodes or []):
        node = str(source)
        if node in G and node not in seeds:
            seeds.append(node)

    for source in (path or []):
        node = str(source)
        if node in G and node not in seeds:
            seeds.append(node)

    if seeds:
        return seeds

    hubs = sorted(G.degree, key=lambda item: item[1], reverse=True)[:3]
    return [str(node) for node, _degree in hubs]


def _focus_subgraph(
    G: nx.Graph,
    focus_nodes: list[str] | None = None,
    path: list[str] | None = None,
    max_nodes: int = 4000,
    hops: int = 2,
) -> nx.Graph:
    if G.number_of_nodes() <= max_nodes:
        return G

    seeds = _seed_nodes(G, focus_nodes=focus_nodes, path=path)
    if not seeds:
        return G.subgraph([]).copy()

    visited = set(seeds)
    q = deque((seed, 0) for seed in seeds)

    while q and len(visited) < max_nodes:
        node, depth = q.popleft()
        if depth >= hops:
            continue

        neighbors = sorted(G.neighbors(node), key=lambda nb: G.degree[nb], reverse=True)
        for neighbor in neighbors:
            neighbor = str(neighbor)
            if neighbor in visited:
                continue
            visited.add(neighbor)
            q.append((neighbor, depth + 1))
            if len(visited) >= max_nodes:
                break

    return G.subgraph(visited).copy()


def _visible_node_mode(G: nx.Graph, node_id: str) -> str:
    visible_modes: set[str] = set()
    for _u, _v, data in G.edges(node_id, data=True):
        if data.get("edge_kind") == "transfer":
            continue
        edge_modes = _split_modes(data.get("modes"))
        edge_modes = [mode for mode in edge_modes if mode != "transfer"]
        if not edge_modes:
            mode = str(data.get("mode") or "other")
            if mode != "transfer":
                edge_modes = [mode]
        visible_modes.update(edge_modes)

    if len(visible_modes) == 1:
        return next(iter(visible_modes))
    if len(visible_modes) > 1:
        return "multi"
    return "other"


def _node_z(G: nx.Graph, node_id: str) -> float:
    mode = _visible_node_mode(G, node_id)
    base = MODE_LAYERS_Z.get(mode, MODE_LAYERS_Z["other"])
    local_lift = min(float(G.degree[node_id]) * 0.05, 0.8)
    return base + local_lift


def _node_color(G: nx.Graph, node_id: str) -> str:
    return MODE_COLORS.get(_visible_node_mode(G, node_id), MODE_COLORS["other"])


def _node_size(G: nx.Graph, node_id: str, emphasize: bool = False) -> float:
    base = 4.0 + min(float(G.degree[node_id]) * 0.35, 8.0)
    return base + (4.0 if emphasize else 0.0)


def _edge_mode(data: dict) -> str:
    if data.get("edge_kind") == "transfer":
        return "transfer"
    modes = [mode for mode in _split_modes(data.get("modes")) if mode != "transfer"]
    if len(set(modes)) == 1:
        return modes[0]
    if len(modes) > 1:
        return "multi"
    mode = str(data.get("mode") or "other")
    return mode if mode != "transfer" else "transfer"


def _line_summary(attrs: dict, max_items: int = 4) -> str:
    lines = attrs.get("lines") or {}
    parts: list[str] = []
    for mode in ("metro", "rail", "tram", "bus"):
        values = list(lines.get(mode, []))
        if values:
            parts.append(f"{mode}: {', '.join(values[:max_items])}")
    return " | ".join(parts)


def _build_edge_trace(
    H: nx.Graph,
    local_pos: dict[str, tuple[float, float]],
    edge_pairs: list[tuple[str, str]],
    *,
    color: str,
    width: float,
    opacity: float,
    name: str,
):
    xs: list[float | None] = []
    ys: list[float | None] = []
    zs: list[float | None] = []

    for u, v in edge_pairs:
        if u not in local_pos or v not in local_pos:
            continue
        x1, y1 = local_pos[u]
        x2, y2 = local_pos[v]
        xs.extend([x1, x2, None])
        ys.extend([y1, y2, None])
        zs.extend([_node_z(H, u), _node_z(H, v), None])

    if not xs:
        return None

    return go.Scatter3d(
        x=xs,
        y=ys,
        z=zs,
        mode="lines",
        line={"color": color, "width": width},
        opacity=opacity,
        name=name,
        hoverinfo="skip",
    )


def plot_graph_3d(
    G: nx.Graph,
    pos: dict[str, tuple[float, float]],
    path: list[str] | None = None,
    *,
    focus_nodes: list[str] | None = None,
    highlight_mode: str | None = None,
    max_nodes: int = 4000,
    focus_hops: int = 2,
    show_transfers: bool = True,
):
    H = _focus_subgraph(G, focus_nodes=focus_nodes, path=path, max_nodes=max_nodes, hops=focus_hops)
    local_pos = _local_map_positions(H, pos)
    path_edges = _path_edge_set(path)
    path_nodes = {str(node) for node in (path or []) if str(node) in H}
    focus_node_set = {str(node) for node in (focus_nodes or []) if str(node) in H}

    grouped_edges: dict[str, list[tuple[str, str]]] = {}
    highlighted_edges: list[tuple[str, str]] = []

    for u, v, data in H.edges(data=True):
        pair = tuple(sorted((str(u), str(v))))
        if pair in path_edges:
            highlighted_edges.append((str(u), str(v)))
            continue

        mode = _edge_mode(data)
        if mode == "transfer" and not show_transfers:
            continue
        grouped_edges.setdefault(mode, []).append((str(u), str(v)))

    edge_traces = []
    for mode in ("bus", "tram", "metro", "rail", "other", "multi", "transfer"):
        edge_pairs = grouped_edges.get(mode, [])
        if not edge_pairs:
            continue
        is_emphasized = highlight_mode is not None and mode == highlight_mode
        trace = _build_edge_trace(
            H,
            local_pos,
            edge_pairs,
            color=MODE_COLORS[mode],
            width=3.2 if is_emphasized else 1.6,
            opacity=0.9 if is_emphasized or highlight_mode is None else 0.12,
            name=f"{mode.title()} edges",
        )
        if trace is not None:
            edge_traces.append(trace)

    path_trace = _build_edge_trace(
        H,
        local_pos,
        highlighted_edges,
        color=MODE_COLORS["path"],
        width=6.0,
        opacity=1.0,
        name="Selected path",
    )
    if path_trace is not None:
        edge_traces.append(path_trace)

    node_x: list[float] = []
    node_y: list[float] = []
    node_z: list[float] = []
    node_size: list[float] = []
    node_color: list[str] = []
    hover_text: list[str] = []

    path_x: list[float] = []
    path_y: list[float] = []
    path_z: list[float] = []
    path_hover: list[str] = []

    focus_x: list[float] = []
    focus_y: list[float] = []
    focus_z: list[float] = []
    focus_hover: list[str] = []

    for node, attrs in H.nodes(data=True):
        sid = str(node)
        if sid not in local_pos:
            continue

        x, y = local_pos[sid]
        lon, lat = pos[sid]
        stop_name = str(attrs.get("stop_name", sid))
        degree = int(H.degree[sid])
        visible_mode = _visible_node_mode(H, sid)
        z_value = _node_z(H, sid)
        summary = _line_summary(attrs)
        hover = (
            f"{stop_name}<br>"
            f"id: {sid}<br>"
            f"layer: {visible_mode}<br>"
            f"connections: {degree}"
            + (f"<br>{summary}" if summary else "")
        )

        if sid in path_nodes:
            path_x.append(x)
            path_y.append(y)
            path_z.append(z_value)
            path_hover.append(hover)

        if sid in focus_node_set:
            focus_x.append(x)
            focus_y.append(y)
            focus_z.append(z_value)
            focus_hover.append(hover)

        node_x.append(x)
        node_y.append(y)
        node_z.append(z_value)
        node_size.append(_node_size(H, sid, emphasize=sid in path_nodes))
        node_color.append(_node_color(H, sid))
        hover_text.append(hover)

    node_opacity = 0.9 if highlight_mode is None else 0.4
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
            "opacity": node_opacity,
            "line": {"width": 0.0},
        },
    )

    traces = edge_traces + [node_trace]

    if path_x:
        traces.append(
            go.Scatter3d(
                x=path_x,
                y=path_y,
                z=path_z,
                mode="markers",
                name="Path stops",
                hovertext=path_hover,
                hovertemplate="%{hovertext}<extra></extra>",
                marker={"size": 8, "color": MODE_COLORS["path"], "opacity": 1.0},
            )
        )

    if focus_x:
        traces.append(
            go.Scatter3d(
                x=focus_x,
                y=focus_y,
                z=focus_z,
                mode="markers+text",
                name="Focus stops",
                text=["Focus"] * len(focus_x),
                textposition="top center",
                hovertext=focus_hover,
                hovertemplate="%{hovertext}<extra></extra>",
                marker={"size": 10, "color": MODE_COLORS["focus"], "opacity": 1.0},
            )
        )

    fig = go.Figure(data=traces)
    fig.update_layout(
        margin={"l": 0, "r": 0, "t": 40, "b": 0},
        scene={
            "xaxis_title": "Local X (km)",
            "yaxis_title": "Local Y (km)",
            "zaxis_title": "Transport layer",
            "aspectmode": "data",
            "camera": {"eye": {"x": 1.55, "y": 1.45, "z": 0.55}},
        },
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02, "xanchor": "left", "x": 0.0},
    )
    return fig
