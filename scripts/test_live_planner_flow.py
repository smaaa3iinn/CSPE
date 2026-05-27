#!/usr/bin/env python3
"""
Quick live planner smoke test (subset of stress suite).

Same path as React UI: POST /text on Atlas :5055.
For full limits testing, run scripts/test_live_planner_stress.py
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from planner_live_test_lib import (  # noqa: E402
    DEFAULT_ACTIVITY_LOG,
    DEFAULT_ATLAS_URL,
    format_summary_row,
    print_summary_table,
    run_live_command,
    score_forced_fallback,
    score_route_shortcut,
    score_shortcut_fast,
    wait_atlas,
)

QUICK_COMMANDS: list[tuple[str, object]] = [
    ("Route me from Chatelet to Republique and open the map", score_route_shortcut),
    ("Add a todo to leave in 15 minutes", lambda m: score_shortcut_fast(m, expected_tools={"memory_add"})),
    ("Search stops near Republique", lambda m: score_shortcut_fast(m, expected_tools={"cspe_search_stops"})),
    ("Show the 3D graph", lambda m: score_shortcut_fast(m, expected_tools={"cspe_open_graph3d"})),
    ("What can you do?", lambda m: score_shortcut_fast(m)),
]


def main() -> int:
    include_fallback = "--include-fallback-test" in sys.argv
    atlas_url = DEFAULT_ATLAS_URL
    log_path = DEFAULT_ACTIVITY_LOG

    wait_atlas(atlas_url)
    print(f"Activity log: {log_path}")
    print("Quick live planner smoke (POST /text)\n")

    rows = []
    fail = 0
    for cmd, scorer in QUICK_COMMANDS:
        print(f"Sending: {cmd}")
        metrics = run_live_command(cmd, log_path=log_path, atlas_url=atlas_url)
        score, note = scorer(metrics)
        if score == "FAIL":
            fail += 1
        rows.append(format_summary_row("quick", cmd, score, metrics, note))

    if include_fallback:
        cmd = "__test_force_local_fail__"
        print(f"Sending: {cmd}")
        metrics = run_live_command(cmd, log_path=log_path, atlas_url=atlas_url)
        score, note = score_forced_fallback(metrics, marker=cmd)
        if score == "FAIL":
            fail += 1
        rows.append(format_summary_row("8.fallback", cmd, score, metrics, note))

    print_summary_table(rows)
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
