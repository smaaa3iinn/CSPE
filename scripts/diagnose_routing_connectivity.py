#!/usr/bin/env python3
"""Connectivity and route-failure diagnostics for CSPE transport routing."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import networkx as nx

from backend.product_shell import transport_engine as te
from backend.product_shell.services import agent_tools as at
from src.core.queries import component_info, shortest_path

MODES = ["all", "metro", "rail", "tram", "bus", "other"]


def comp_stats(G: nx.Graph) -> dict:
    if G.number_of_nodes() == 0:
        return {
            "nodes": 0,
            "edges": 0,
            "components": 0,
            "lcc": 0,
            "lcc_pct": 0.0,
            "outside_lcc": 0,
            "outside_lcc_pct": 0.0,
            "top5_component_sizes": [],
            "small_components_2_10": 0,
            "isolated_nodes": 0,
        }
    comps = list(nx.connected_components(G))
    sizes = sorted((len(c) for c in comps), reverse=True)
    lcc = sizes[0]
    return {
        "nodes": G.number_of_nodes(),
        "edges": G.number_of_edges(),
        "components": len(comps),
        "lcc": lcc,
        "lcc_pct": round(100 * lcc / G.number_of_nodes(), 2),
        "outside_lcc": G.number_of_nodes() - lcc,
        "outside_lcc_pct": round(100 * (G.number_of_nodes() - lcc) / G.number_of_nodes(), 2),
        "top5_component_sizes": sizes[:5],
        "small_components_2_10": sum(1 for s in sizes if 2 <= s <= 10),
        "isolated_nodes": sum(1 for s in sizes if s == 1),
    }


def edge_kind_counts(G: nx.Graph) -> dict[str, int]:
    out: dict[str, int] = {}
    for _, _, data in G.edges(data=True):
        key = str(data.get("edge_kind") or "missing")
        out[key] = out.get(key, 0) + 1
    return out


def diagnose_endpoint_pair(
    a_query: str,
    b_query: str,
    *,
    mode: str = "metro",
    use_lcc: bool = False,
    routing_scope: str = "station",
) -> dict:
    from_r = at.resolve_stop_query(a_query, mode=mode, use_lcc=use_lcc, station_first=True)
    to_r = at.resolve_stop_query(b_query, mode=mode, use_lcc=use_lcc, station_first=True)
    out = at.compute_route_from_queries(
        a_query,
        b_query,
        mode=mode,
        use_lcc=use_lcc,
        routing_scope=routing_scope,  # type: ignore[arg-type]
        station_first=True,
    )

    G_full = te.graph_for(mode, False)
    G_lcc = te.graph_for(mode, True)
    idx_full = te.station_layer_for(mode, False)

    def endpoint_diag(resolved: dict, label: str) -> dict:
        if resolved.get("status") != "exact":
            return {"label": label, "resolve_status": resolved.get("status"), "matches": len(resolved.get("matches") or [])}
        m = resolved.get("match") or {}
        station_id = (m.get("station_id") or "").strip() or None
        stop_id = (m.get("stop_id") or "").strip() or None
        diag = {
            "label": label,
            "resolve_status": "exact",
            "station_id": station_id,
            "stop_id": stop_id,
            "name": m.get("station_name") or m.get("stop_name"),
        }
        if station_id:
            stops = [s for s in idx_full.station_to_stops.get(station_id, []) if s in G_full]
            diag["stops_in_full_graph"] = len(stops)
            diag["stops_in_lcc_graph"] = sum(1 for s in stops if s in G_lcc)
            if stops:
                s0 = sorted(stops)[0]
                diag["component_full"] = component_info(G_full, s0)
                diag["component_lcc"] = component_info(G_lcc, s0)
        elif stop_id:
            diag["in_full_graph"] = stop_id in G_full
            diag["in_lcc_graph"] = stop_id in G_lcc
            diag["component_full"] = component_info(G_full, stop_id)
            diag["component_lcc"] = component_info(G_lcc, stop_id)
        return diag

    route_err = None
    if not out.get("ok"):
        route = out.get("route") or {}
        err = route.get("error") if isinstance(route, dict) else out.get("error")
        if isinstance(err, dict):
            route_err = err

    # Path exists in full graph but not selected graph?
    path_in_full = None
    path_in_lcc = None
    if from_r.get("status") == "exact" and to_r.get("status") == "exact":
        fm = from_r["match"]
        tm = to_r["match"]
        if routing_scope == "station":
            from src.core.station_layer import best_stop_path_between_stations

            fs = (fm.get("station_id") or "").strip()
            ts = (tm.get("station_id") or "").strip()
            path_in_full = best_stop_path_between_stations(G_full, idx_full, fs, ts)
            idx_lcc = te.station_layer_for(mode, True)
            path_in_lcc = best_stop_path_between_stations(G_lcc, idx_lcc, fs, ts)
        else:
            sa = (fm.get("stop_id") or "").strip()
            sb = (tm.get("stop_id") or "").strip()
            path_in_full = shortest_path(G_full, sa, sb)
            path_in_lcc = shortest_path(G_lcc, sa, sb)

    return {
        "query": f"{a_query} -> {b_query}",
        "mode": mode,
        "requested_use_lcc": use_lcc,
        "effective_mode": out.get("mode"),
        "effective_use_lcc": out.get("use_lcc"),
        "ok": out.get("ok"),
        "from": endpoint_diag(from_r, "from"),
        "to": endpoint_diag(to_r, "to"),
        "error": route_err,
        "path_in_full_graph": {"ok": path_in_full.get("ok"), "reason": path_in_full.get("reason")} if path_in_full else None,
        "path_in_lcc_graph": {"ok": path_in_lcc.get("ok"), "reason": path_in_lcc.get("reason")} if path_in_lcc else None,
    }


def main() -> int:
    print("=== GRAPH CONNECTIVITY BY MODE (full vs LCC) ===")
    for mode in MODES:
        for use_lcc in (False, True):
            try:
                G = te.graph_for(mode, use_lcc)
                s = comp_stats(G)
                print(
                    f"{mode:5} use_lcc={str(use_lcc):5} nodes={s['nodes']:6} edges={s['edges']:6} "
                    f"comps={s['components']:5} lcc={s['lcc']:6} ({s['lcc_pct']} pct) "
                    f"outside_lcc={s['outside_lcc']} ({s['outside_lcc_pct']} pct) "
                    f"top5={s['top5_component_sizes']}"
                )
            except Exception as exc:
                print(f"{mode} use_lcc={use_lcc} ERROR: {exc}")

    print("\n=== EDGE KIND COUNTS (runtime graphs) ===")
    for mode in ["all", "metro", "bus"]:
        G = te.graph_for(mode, False)
        print(f"{mode}: {edge_kind_counts(G)}")

    print("\n=== ENDPOINT DIAGNOSTICS (metro, station routing) ===")
    pairs = [
        ("Chatelet", "Republique"),
        ("Chatelet", "Gare de Lyon"),
        ("La Defense", "Chatelet"),
        ("Montparnasse", "Saint-Lazare"),
        ("Opera", "Nation"),
        ("Chatelet", "La Defense"),
    ]
    for a, b in pairs:
        for use_lcc in (False, True):
            row = diagnose_endpoint_pair(a, b, mode="metro", use_lcc=use_lcc, routing_scope="station")
            err = row.get("error") or {}
            msg = err.get("message") if isinstance(err, dict) else err
            print(f"\n{row['query']} | requested_lcc={use_lcc} effective_lcc={row['effective_use_lcc']} ok={row['ok']}")
            print(f"  error: {msg}")
            print(f"  full_graph: {row['path_in_full_graph']} | lcc_graph: {row['path_in_lcc_graph']}")
            print(f"  from: {json.dumps(row['from'], ensure_ascii=False)}")
            print(f"  to:   {json.dumps(row['to'], ensure_ascii=False)}")

    print("\n=== MODE=all vs metro (use_lcc=False) ===")
    for a, b in pairs[:3]:
        row = diagnose_endpoint_pair(a, b, mode="all", use_lcc=False, routing_scope="station")
        err = (row.get("error") or {}).get("message")
        print(f"{row['query']}: ok={row['ok']} err={err} full={row['path_in_full_graph']}")

    print("\n=== BUS mode sample ===")
    for a, b in [("Opera", "Nation"), ("Chatelet", "Republique")]:
        row = diagnose_endpoint_pair(a, b, mode="bus", use_lcc=False, routing_scope="station")
        err = (row.get("error") or {}).get("message")
        print(f"{row['query']}: ok={row['ok']} from={row['from'].get('resolve_status')} to={row['to'].get('resolve_status')} err={err}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
