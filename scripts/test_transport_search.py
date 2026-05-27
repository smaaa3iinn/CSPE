#!/usr/bin/env python3
"""Direct transport search/route tests (no Atlas planner)."""

from __future__ import annotations

import json
import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from src.core.queries import normalize_text
from backend.product_shell import transport_engine as te
from backend.product_shell.services import agent_tools as at


STATION_NEEDLES = [
    "Chatelet",
    "Châtelet",
    "Republique",
    "République",
    "Gare de Lyon",
    "La Defense",
    "La Défense",
]


def inspect_station_data() -> None:
    print("=== Station data samples (metro, use_lcc=False) ===")
    G = te.graph_for("metro", False)
    idx = te.station_layer_for("metro", False)
    print(f"stations={len(idx.station_label)} nodes={G.number_of_nodes()}")
    for needle in STATION_NEEDLES:
        nq = normalize_text(needle)
        hits = []
        for sid, label in idx.station_label.items():
            nl = normalize_text(label)
            if nq == nl or nl.startswith(nq) or nq in nl:
                members = idx.station_to_stops.get(sid, [])[:3]
                lines = None
                if members and members[0] in G:
                    lines = G.nodes[members[0]].get("lines")
                hits.append(
                    {
                        "station_id": sid,
                        "station_name": label,
                        "normalized": nl,
                        "stop_ids_sample": members,
                        "lines": lines,
                    }
                )
        print(f"\n--- {needle!r} (norm={nq!r}) matches={len(hits)} ---")
        for row in hits[:3]:
            print(json.dumps(row, ensure_ascii=False, indent=2))


def test_search(query: str, *, mode: str = "metro", use_lcc: bool = True) -> int:
    rows = te.search_stops(
        query, limit=15, mode=mode, use_lcc=use_lcc, station_first=True, fallback_lcc=True
    )
    names = [(r.get("station_name") or r.get("stop_name")) for r in rows[:5]]
    print(f"search_stops({query!r}, mode={mode}, use_lcc={use_lcc}) -> count={len(rows)} {names}")
    return len(rows)


def test_route(a: str, b: str, *, mode: str = "metro", use_lcc: bool = True) -> bool:
    out = at.compute_route_from_queries(
        a,
        b,
        mode=mode,
        use_lcc=use_lcc,
        routing_scope="station",
        station_first=True,
    )
    ok = bool(out.get("ok"))
    print(
        f"compute_route({a!r} -> {b!r}, mode={mode}, use_lcc={use_lcc}) -> ok={ok} "
        f"route_mode={out.get('mode')} route_use_lcc={out.get('use_lcc')}"
    )
    if not ok:
        print("  from:", out.get("from", {}).get("status"), "to:", out.get("to", {}).get("status"))
    return ok


def main() -> int:
    inspect_station_data()
    print("\n=== Search tests ===")
    failures = 0
    for q in ["Republique", "République", "Chatelet", "Châtelet", "La Defense", "La Défense"]:
        if test_search(q, mode="metro", use_lcc=True) < 1:
            failures += 1
    print("\n=== Route tests ===")
    for a, b in [
        ("Chatelet", "Republique"),
        ("Châtelet", "République"),
    ]:
        if not test_route(a, b, mode="metro", use_lcc=True):
            failures += 1
    print(f"\n{'FAIL' if failures else 'PASS'}: {failures} failing checks")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
