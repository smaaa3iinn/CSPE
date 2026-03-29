from __future__ import annotations

import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
import networkx as nx


def plot_graph_2d(
    G: nx.Graph,
    pos: dict,
    title: str = "",
    max_edges: int = 60000,
    path: list[str] | None = None,
    zoom_to_path: bool = False,
):
    fig, ax = plt.subplots()

    # Background edges (lighter)
    segments = []
    count = 0
    for a, b in G.edges():
        if count >= max_edges:
            break
        if a in pos and b in pos:
            segments.append([pos[a], pos[b]])
            count += 1

    if segments:
        lc = LineCollection(segments, linewidths=0.25, alpha=0.15)  # lighter
        ax.add_collection(lc)

    # Path on top (strong)
    if path and len(path) >= 2:
        pseg = []
        xs, ys = [], []
        for i in range(len(path) - 1):
            u = path[i]
            v = path[i + 1]
            if u in pos and v in pos:
                (x1, y1), (x2, y2) = pos[u], pos[v]
                pseg.append([(x1, y1), (x2, y2)])
                xs += [x1, x2]
                ys += [y1, y2]

        if pseg:
            plc = LineCollection(pseg, linewidths=3.5, alpha=0.95, colors="red")
            ax.add_collection(plc)

            # Optional zoom
            if zoom_to_path and xs and ys:
                pad_x = (max(xs) - min(xs)) * 0.15 + 1e-6
                pad_y = (max(ys) - min(ys)) * 0.15 + 1e-6
                ax.set_xlim(min(xs) - pad_x, max(xs) + pad_x)
                ax.set_ylim(min(ys) - pad_y, max(ys) + pad_y)

    if not zoom_to_path:
        ax.autoscale()

    ax.set_aspect("equal", adjustable="datalim")
    ax.set_title(title)
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.grid(False)

    return fig