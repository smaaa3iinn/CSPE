from __future__ import annotations

from collections import deque
import re
import networkx as nx


def normalize_text(s: str) -> str:
    s = str(s).strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def search_stops(G: nx.Graph, query: str, limit: int = 20, mode: str | None = None):
    q = normalize_text(query)
    if not q:
        return []

    results = []

    for n, attrs in G.nodes(data=True):
        name = str(attrs.get("stop_name", ""))
        if name and q in normalize_text(name):
            results.append({"stop_id": str(n), "stop_name": name, "_lines": attrs.get("lines")})

    if not results:
        for n in G.nodes():
            if q in normalize_text(str(n)):
                results.append({"stop_id": str(n), "stop_name": str(G.nodes[n].get("stop_name", "")), "_lines": G.nodes[n].get("lines")})

    # Expand results by line for metro/rail/tram so the UI can show:
    #   Gare de Lyon – Line 1 / Line 14 / RER A ...
    # For bus/all this can explode, so we keep a single entry.
    if mode in {"metro", "rail", "tram"}:
        expanded = []
        for r in results:
            lines = (r.get("_lines") or {}).get(mode, [])
            # cap to avoid insane dropdowns
            lines = list(lines)[:8]
            if lines:
                for ln in lines:
                    expanded.append({"stop_id": r["stop_id"], "stop_name": r["stop_name"], "line": ln})
            else:
                expanded.append({"stop_id": r["stop_id"], "stop_name": r["stop_name"], "line": None})
        results = expanded
    else:
        # compact summary if we can
        compact = []
        for r in results:
            lines_dict = r.get("_lines") or {}
            summary_parts = []
            for m in ("metro", "rail", "tram"):
                if m in lines_dict and lines_dict[m]:
                    summary_parts.append(",".join(lines_dict[m][:3]))
            compact.append({"stop_id": r["stop_id"], "stop_name": r["stop_name"], "line": " | ".join(summary_parts) if summary_parts else None})
        results = compact

    # drop helper key
    for r in results:
        r.pop("_lines", None)

    return results[:limit]


def same_component(G: nx.Graph, a: str, b: str) -> bool:
    a = str(a)
    b = str(b)
    if a not in G or b not in G:
        return False
    return nx.has_path(G, a, b)


def component_info(G: nx.Graph, node_id: str):
    node_id = str(node_id)
    if node_id not in G:
        return {"exists": False, "component_size": 0}

    for comp in nx.connected_components(G):
        if node_id in comp:
            return {"exists": True, "component_size": len(comp)}
    return {"exists": True, "component_size": 1}


def _safe_number(value):
    try:
        num = float(value)
    except Exception:
        return None
    if num != num:
        return None
    return num


def summarize_path(G: nx.Graph, path: list[str]):
    distance_total = 0.0
    time_total = 0.0
    transfer_count = 0
    mode_counts: dict[str, int] = {}
    has_distance = False
    has_time = False

    if not path:
        return {"distance_m": None, "time_s": None, "transfers": 0, "mode_counts": {}}

    for u, v in zip(path, path[1:]):
        data = G.get_edge_data(u, v) or {}
        distance_m = _safe_number(data.get("distance_m"))
        if distance_m is None:
            distance_m = _safe_number(data.get("weight_m"))
        if distance_m is not None:
            distance_total += distance_m
            has_distance = True

        time_s = _safe_number(data.get("time_s"))
        if time_s is not None:
            time_total += time_s
            has_time = True

        if data.get("edge_kind") == "transfer":
            transfer_count += 1

        mode = str(data.get("mode") or data.get("modes") or "unknown")
        mode_counts[mode] = mode_counts.get(mode, 0) + 1

    return {
        "distance_m": distance_total if has_distance else None,
        "time_s": time_total if has_time else None,
        "transfers": transfer_count,
        "mode_counts": mode_counts,
    }


def _resolve_strategy(strategy: str | None, use_weights: bool | None) -> str:
    if use_weights is not None:
        return "distance" if use_weights else "hops"
    strategy = str(strategy or "cost").strip().lower()
    if strategy not in {"cost", "distance", "hops"}:
        return "cost"
    return strategy


def _weight_fn(strategy: str):
    if strategy == "distance":
        return lambda _u, _v, data: _safe_number(data.get("distance_m")) or _safe_number(data.get("weight_m")) or 1.0
    if strategy == "cost":
        return lambda _u, _v, data: (
            _safe_number(data.get("cost"))
            or _safe_number(data.get("time_s"))
            or _safe_number(data.get("distance_m"))
            or _safe_number(data.get("weight_m"))
            or 1.0
        )
    return None


def shortest_path(G: nx.Graph, a: str, b: str, strategy: str = "cost", use_weights: bool | None = None):
    a = str(a)
    b = str(b)
    strategy = _resolve_strategy(strategy, use_weights)

    if a not in G:
        return {"ok": False, "reason": "start_not_found", "path": [], "distance_m": None, "time_s": None, "transfers": 0, "strategy": strategy}
    if b not in G:
        return {"ok": False, "reason": "end_not_found", "path": [], "distance_m": None, "time_s": None, "transfers": 0, "strategy": strategy}
    if a == b:
        return {
            "ok": True,
            "reason": "same_node",
            "path": [a],
            "distance_m": 0.0,
            "time_s": 0.0,
            "transfers": 0,
            "mode_counts": {},
            "strategy": strategy,
        }

    if not nx.has_path(G, a, b):
        return {"ok": False, "reason": "not_connected", "path": [], "distance_m": None, "time_s": None, "transfers": 0, "strategy": strategy}

    try:
        if strategy == "hops":
            path = nx.shortest_path(G, a, b)
        else:
            path = nx.shortest_path(G, a, b, weight=_weight_fn(strategy))

        path = [str(x) for x in path]
        summary = summarize_path(G, path)
        return {
            "ok": True,
            "reason": "ok",
            "path": path,
            "distance_m": summary["distance_m"],
            "time_s": summary["time_s"],
            "transfers": summary["transfers"],
            "mode_counts": summary["mode_counts"],
            "strategy": strategy,
        }
    except Exception:
        if strategy == "hops":
            return {"ok": False, "reason": "path_error", "path": [], "distance_m": None, "time_s": None, "transfers": 0, "strategy": strategy}

        try:
            path = [str(x) for x in nx.shortest_path(G, a, b)]
            summary = summarize_path(G, path)
            return {
                "ok": True,
                "reason": "ok_fallback_hops",
                "path": path,
                "distance_m": summary["distance_m"],
                "time_s": summary["time_s"],
                "transfers": summary["transfers"],
                "mode_counts": summary["mode_counts"],
                "strategy": "hops",
            }
        except Exception:
            return {"ok": False, "reason": "path_error", "path": [], "distance_m": None, "time_s": None, "transfers": 0, "strategy": strategy}


def k_hop_subgraph(G: nx.Graph, center: str, k: int = 2, max_nodes: int = 3000) -> nx.Graph:
    center = str(center)
    if center not in G:
        return nx.Graph()

    visited = {center}
    q = deque([(center, 0)])

    while q and len(visited) < max_nodes:
        node, depth = q.popleft()
        if depth >= k:
            continue
        for nb in G.neighbors(node):
            nb = str(nb)
            if nb not in visited:
                visited.add(nb)
                q.append((nb, depth + 1))
            if len(visited) >= max_nodes:
                break

    return G.subgraph(visited).copy()