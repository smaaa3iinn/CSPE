from __future__ import annotations

from pathlib import Path
import sys

import networkx as nx

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.cache_bundle import load_or_build_graph_bundle
from src.core.queries import shortest_path

BUNDLE_PATH = ROOT / "data" / "derived" / "routing" / "graph_bundle.pkl"
STOP_POPUP_INDEX_PATH = ROOT / "data" / "derived" / "stops" / "stop_popup_index.parquet"


def _pick_pair(G: nx.Graph) -> tuple[str, str]:
    nodes = list(G.nodes())
    if len(nodes) < 2:
        raise AssertionError("Need at least two nodes to validate routing.")
    return str(nodes[0]), str(nodes[min(len(nodes) - 1, max(1, len(nodes) // 2))])


def main():
    bundle = load_or_build_graph_bundle(
        ROOT,
        cache_path=BUNDLE_PATH,
        stop_popup_index_path=STOP_POPUP_INDEX_PATH,
    )
    graphs = bundle["graphs"]
    graphs_lcc = bundle["graphs_lcc"]
    edges = bundle["edges_clean"]

    assert edges, "Derived edge bundle returned no edges."
    assert any(str(edge.get("mode")) == "metro" for edge in edges), "Metro edges are missing."
    assert any(str(edge.get("mode")) == "bus" for edge in edges), "Bus edges are missing."

    for mode, graph in graphs.items():
        assert graph.number_of_nodes() >= 0
        assert graph.number_of_edges() >= 0
        print(f"{mode}: nodes={graph.number_of_nodes()} edges={graph.number_of_edges()}")

    route_graph = graphs_lcc["all"]
    start, end = _pick_pair(route_graph)
    res = shortest_path(route_graph, start, end)
    assert res["ok"], f"Routing failed: {res}"
    assert res["path"], "Empty path returned by routing."
    print(
        f"hops: stops={len(res['path'])} "
        f"distance_m={res['distance_m']} time_s={res['time_s']} transfers={res['transfers']}"
    )

    missing_res = shortest_path(route_graph, "__missing__", end)
    assert not missing_res["ok"] and missing_res["reason"] == "start_not_found"

    disconnected = nx.Graph()
    disconnected.add_node("a")
    disconnected.add_node("b")
    disconnected_res = shortest_path(disconnected, "a", "b")
    assert not disconnected_res["ok"] and disconnected_res["reason"] == "not_connected"

    print("Validation checks passed.")


if __name__ == "__main__":
    main()
