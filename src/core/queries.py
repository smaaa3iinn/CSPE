from __future__ import annotations

from collections import deque
import re
from typing import Any

import networkx as nx


def normalize_text(s: str) -> str:
    s = str(s).strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def _stop_name_prefix_match(normalized_name: str, q: str) -> bool:
    """True if whole name or any whitespace-separated token starts with q."""
    if not q:
        return False
    if normalized_name.startswith(q):
        return True
    return any(part.startswith(q) for part in normalized_name.split() if part)


def _station_search_extras(r: dict) -> dict[str, Any]:
    """Preserve station-first fields through line expansion."""
    out: dict[str, Any] = {}
    for k in ("station_id", "station_name", "primary_stop_id", "stop_ids"):
        if k in r and r[k] is not None:
            out[k] = r[k]
    return out


def _merge_mode_lines_union(G: nx.Graph, members: list[str]) -> dict[str, list[str]] | None:
    """Union line labels across all child stops (platforms) for each transport mode."""
    merged: dict[str, list[str]] = {}
    for m in members:
        if m not in G:
            continue
        node_lines = G.nodes[m].get("lines")
        if not isinstance(node_lines, dict):
            continue
        for mode_key, vals in node_lines.items():
            bucket = merged.setdefault(str(mode_key), [])
            for v in vals or []:
                sv = str(v).strip()
                if sv and sv not in bucket:
                    bucket.append(sv)
    return merged or None


def _expand_and_cap_route_results(
    results: list[dict], *, mode: str | None, limit: int, station_compact: bool = False
) -> list[dict]:
    """Shared metro/rail/tram line expansion + bus compacting (matches search_stops)."""
    if mode in {"metro", "rail", "tram"}:
        if station_compact:
            compact: list[dict] = []
            for r in results:
                extra = _station_search_extras(r)
                lines_dict = r.get("_lines") or {}
                line_list = list(lines_dict.get(mode, []))[:24]
                line_str = ", ".join(line_list) if line_list else None
                compact.append({"stop_id": r["stop_id"], "stop_name": r["stop_name"], "line": line_str, **extra})
            results = compact
        else:
            expanded = []
            for r in results:
                extra = _station_search_extras(r)
                lines = (r.get("_lines") or {}).get(mode, [])
                lines = list(lines)[:8]
                if lines:
                    for ln in lines:
                        expanded.append({"stop_id": r["stop_id"], "stop_name": r["stop_name"], "line": ln, **extra})
                else:
                    expanded.append({"stop_id": r["stop_id"], "stop_name": r["stop_name"], "line": None, **extra})
            results = expanded
    else:
        compact = []
        for r in results:
            extra = _station_search_extras(r)
            lines_dict = r.get("_lines") or {}
            summary_parts = []
            for m in ("metro", "rail", "tram"):
                if m in lines_dict and lines_dict[m]:
                    summary_parts.append(",".join(lines_dict[m][:3]))
            compact.append(
                {
                    "stop_id": r["stop_id"],
                    "stop_name": r["stop_name"],
                    "line": " | ".join(summary_parts) if summary_parts else None,
                    **extra,
                }
            )
        results = compact
    for r in results:
        r.pop("_lines", None)
    return results[:limit]


def search_stops_autocomplete(
    G: nx.Graph, query: str, limit: int = 40, mode: str | None = None, *, max_raw_stops: int = 80
) -> list[dict]:
    """
    Prefix-oriented suggestions for live search (any word in the stop name can match the prefix).
    Stops scanning after max_raw_stops candidates for performance on large graphs.
    """
    q = normalize_text(query)
    if not q:
        return []

    results: list[dict] = []
    for n, attrs in G.nodes(data=True):
        name = str(attrs.get("stop_name", ""))
        if not name:
            continue
        nn = normalize_text(name)
        if _stop_name_prefix_match(nn, q):
            results.append({"stop_id": str(n), "stop_name": name, "_lines": attrs.get("lines")})
        if len(results) >= max_raw_stops:
            break

    if not results:
        for n in G.nodes():
            nid = normalize_text(str(n))
            if nid.startswith(q):
                results.append(
                    {
                        "stop_id": str(n),
                        "stop_name": str(G.nodes[n].get("stop_name", "")),
                        "_lines": G.nodes[n].get("lines"),
                    }
                )
            if len(results) >= max_raw_stops:
                break

    results.sort(key=lambda r: normalize_text(r["stop_name"]))
    return _expand_and_cap_route_results(results, mode=mode, limit=limit)


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

    return _expand_and_cap_route_results(results, mode=mode, limit=limit)


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


def shortest_path(G: nx.Graph, a: str, b: str, strategy: str = "hops", use_weights: bool | None = None):
    a = str(a)
    b = str(b)
    _ = strategy
    _ = use_weights
    strategy = "hops"

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
        path = nx.shortest_path(G, a, b)
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
        return {"ok": False, "reason": "path_error", "path": [], "distance_m": None, "time_s": None, "transfers": 0, "strategy": strategy}


def search_stations_autocomplete(
    G: nx.Graph,
    idx: Any,
    query: str,
    limit: int = 40,
    mode: str | None = None,
    *,
    station_compact: bool = False,
) -> list[dict]:
    """
    Station-first suggestions: one row per station (child platform stops grouped).
    Grouping uses GTFS parent_station when present, else transfer connectivity and
    same normalized name within geographic proximity (not name alone).
    With ``station_compact=True`` (station-first API search): lines are merged across all
    child platforms into one row per station; no per-line duplication.
    Otherwise expanded rows keep stop_id = primary_stop_id for per-line fan-out.
    """
    q = normalize_text(query)
    if not q:
        return []

    from src.core.station_layer import StationLayerIndex

    if not isinstance(idx, StationLayerIndex):
        return []

    seen_station: set[str] = set()
    raw: list[dict] = []

    for station_id, label in idx.station_label.items():
        if station_id in seen_station:
            continue
        nn = normalize_text(label)
        if _stop_name_prefix_match(nn, q):
            members = idx.station_to_stops.get(station_id, [])
            primary = sorted(members)[0] if members else ""
            line_src = (
                _merge_mode_lines_union(G, members)
                if station_compact
                else (G.nodes[primary].get("lines") if primary in G else None)
            )
            raw.append(
                {
                    "station_id": station_id,
                    "station_name": label,
                    "stop_ids": members,
                    "primary_stop_id": primary,
                    "stop_id": primary,
                    "stop_name": label,
                    "_lines": line_src,
                }
            )
            seen_station.add(station_id)
            continue
        for member in idx.station_to_stops.get(station_id, []):
            if member not in G:
                continue
            name = str(G.nodes[member].get("stop_name", ""))
            if name and _stop_name_prefix_match(normalize_text(name), q):
                members = idx.station_to_stops.get(station_id, [])
                primary = sorted(members)[0] if members else member
                line_src = (
                    _merge_mode_lines_union(G, members)
                    if station_compact
                    else G.nodes[primary].get("lines")
                )
                raw.append(
                    {
                        "station_id": station_id,
                        "station_name": label,
                        "stop_ids": members,
                        "primary_stop_id": primary,
                        "stop_id": primary,
                        "stop_name": label,
                        "_lines": line_src,
                    }
                )
                seen_station.add(station_id)
                break

    raw.sort(key=lambda r: normalize_text(r["station_name"]))
    return _expand_and_cap_route_results(
        raw, mode=mode, limit=limit, station_compact=station_compact
    )


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