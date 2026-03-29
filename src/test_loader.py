from __future__ import annotations

from pathlib import Path
import sys

import networkx as nx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.graph_loader import (
    build_edges_enriched,
    build_graphs_by_mode_with_lines,
    build_pos_all,
    load_gtfs,
)
from src.core.queries import shortest_path

GTFS_DIR = "data/gtfs"


def _pick_pair(G: nx.Graph) -> tuple[str, str]:
    nodes = list(G.nodes())
    if len(nodes) < 2:
        raise AssertionError("Need at least two nodes to validate routing.")
    return str(nodes[0]), str(nodes[min(len(nodes) - 1, max(1, len(nodes) // 2))])


def main():
    data = load_gtfs(GTFS_DIR)
    pos_all = build_pos_all(data.stops)
    edges = build_edges_enriched(data, pos_all=pos_all)
    graphs, graphs_lcc = build_graphs_by_mode_with_lines(data, edges, pos_all=pos_all)

    assert not edges.empty, "Enriched edge build returned no edges."
    assert (edges["edge_kind"] == "ride").any(), "Ride edges are missing."
    assert (edges["edge_kind"] == "transfer").any(), "Transfer edges are missing."

    for mode, graph in graphs.items():
        assert graph.number_of_nodes() >= 0
        assert graph.number_of_edges() >= 0
        print(f"{mode}: nodes={graph.number_of_nodes()} edges={graph.number_of_edges()}")

    route_graph = graphs_lcc["all"]
    start, end = _pick_pair(route_graph)
    for strategy in ("cost", "distance", "hops"):
        res = shortest_path(route_graph, start, end, strategy=strategy)
        assert res["ok"], f"Routing failed for strategy={strategy}: {res}"
        assert res["path"], f"Empty path for strategy={strategy}"
        print(
            f"{strategy}: stops={len(res['path'])} "
            f"distance_m={res['distance_m']} time_s={res['time_s']} transfers={res['transfers']}"
        )

    cost_res = shortest_path(route_graph, start, end, strategy="cost")
    assert cost_res["distance_m"] is not None, "Cost routing should report distance."
    assert cost_res["time_s"] is not None, "Cost routing should report time."

    missing_res = shortest_path(route_graph, "__missing__", end, strategy="cost")
    assert not missing_res["ok"] and missing_res["reason"] == "start_not_found"

    disconnected = nx.Graph()
    disconnected.add_node("a")
    disconnected.add_node("b")
    disconnected_res = shortest_path(disconnected, "a", "b", strategy="cost")
    assert not disconnected_res["ok"] and disconnected_res["reason"] == "not_connected"

    print("Validation checks passed.")


if __name__ == "__main__":
    main()
