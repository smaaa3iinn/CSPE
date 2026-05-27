#!/usr/bin/env python3
"""
Live Atlas planner stress suite — real UI path:
  POST http://127.0.0.1:5055/text → run_planner_turn → tools → final OpenAI text response.

Prerequisites: run_web_app.ps1 (Atlas :5055, product :8787), Ollama if using local planner.

Usage:
  python scripts/test_live_planner_stress.py
  python scripts/test_live_planner_stress.py --category 1 --category 2
  python scripts/test_live_planner_stress.py --include-optional-fallback
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from planner_live_test_lib import (  # noqa: E402
    DEFAULT_ACTIVITY_LOG,
    DEFAULT_ATLAS_URL,
    TestCase,
    format_summary_row,
    print_grouped_findings,
    print_summary_table,
    run_live_command,
    score_follow_up,
    score_forced_fallback,
    score_fuzzy_or_clarify,
    score_invalid,
    score_multi_step,
    score_multi_step_ordered,
    score_partial_route_with_todo,
    score_route_and_todo,
    score_route_shortcut,
    score_shortcut_fast,
    wait_atlas,
)


def build_test_cases(*, include_optional_fallback: bool) -> list[TestCase]:
    cases: list[TestCase] = []

    # 1. Single known shortcuts
    cat1 = [
        ("Open the transport map", {"cspe_open_transport_map"}),
        ("Search stops near Republique", {"cspe_search_stops"}),
        ("Show the 3D graph", {"cspe_open_graph3d"}),
        ("Switch to transport mode", {"cspe_set_mode"}),
        ("Add a todo to leave in 15 minutes", {"memory_add"}),
    ]
    for cmd, tools in cat1:
        cases.append(
            TestCase(
                category="1.shortcuts",
                command=cmd,
                scorer=lambda m, t=tools: score_shortcut_fast(m, expected_tools=t),
            )
        )

    # 2. Known combined route shortcuts
    cases.append(
        TestCase(
            category="2.route_shortcut",
            command="Route me from Chatelet to Republique and open the map",
            scorer=score_route_shortcut,
        )
    )
    cases.append(
        TestCase(
            category="2.route_shortcut",
            command="Find a route from Gare de Lyon to La Defense and show it on the map",
            scorer=score_route_shortcut,
        )
    )

    # 3. Multi-step cross-domain (ordered tool execution)
    multi_ordered: list[tuple[str, list[str]]] = [
        (
            "Route me from Chatelet to Republique, open the map, and add a todo to leave in 15 minutes",
            ["cspe_compute_route", "memory_add"],
        ),
        (
            "Search stops near Republique and then show the 3D graph",
            ["cspe_search_stops", "cspe_open_graph3d"],
        ),
        (
            "Switch to transport mode, open the map, and search stops near Chatelet",
            ["cspe_set_mode", "cspe_open_transport_map", "cspe_search_stops"],
        ),
        (
            "Add a todo to call home in 30 minutes and then show me what you can do",
            ["memory_add"],
        ),
        (
            "Route me from Chatelet to Republique, then remind me to leave in 15 minutes, then show the 3D graph",
            ["cspe_compute_route", "memory_add", "cspe_open_graph3d"],
        ),
    ]
    for cmd, tools in multi_ordered:
        cases.append(
            TestCase(
                category="3.multi_step",
                command=cmd,
                scorer=lambda m, t=tools: score_multi_step_ordered(m, expected_tools=t),
            )
        )

    # 4. Ambiguous follow-up (sequential session)
    followups = [
        ("Route me from Chatelet to Republique", "route"),
        ("Now open it in 3D", "3d"),
        ("Search around there", "search"),
        ("Add a reminder to leave for there in 15 minutes", "memory"),
    ]
    for cmd, kind in followups:
        cases.append(
            TestCase(
                category="4.follow_up",
                command=cmd,
                sequence_group="follow_up_session",
                scorer=lambda m, k=kind: score_follow_up(m, kind=k),
            )
        )

    # 5. Typos / no-accent
    fuzzy = [
        ("Route me from Chatlet to Republique", {"cspe_compute_route"}),
        ("Search stops near Republic", {"cspe_search_stops"}),
        ("Find route from La Defense to Gare du Lyon", {"cspe_compute_route"}),
        ("Open transprot map", {"cspe_open_transport_map"}),
    ]
    for cmd, tools in fuzzy:
        cases.append(
            TestCase(
                category="5.typos",
                command=cmd,
                scorer=lambda m, t=tools: score_fuzzy_or_clarify(m, prefer_tools=t),
            )
        )

    # 6. French / mixed language
    fr = [
        ("Cherche les arrêts près de République", {"cspe_search_stops"}),
        ("Calcule un trajet de Châtelet à République et ouvre la carte", {"cspe_compute_route"}),
        ("Ajoute une tâche pour partir dans 15 minutes", {"memory_add"}),
        ("Route me from Chatelet à République and open la carte", {"cspe_compute_route"}),
    ]
    for cmd, tools in fr:
        cases.append(
            TestCase(
                category="6.french",
                command=cmd,
                scorer=lambda m, t=tools: score_fuzzy_or_clarify(m, prefer_tools=t),
            )
        )

    # 7. Invalid / impossible
    invalid_cmds = [
        "Route me from Atlantis to Wakanda",
        "Search stops near qwertyuiop",
        "Add a todo sometime maybe later",
        "Open the 9D hologram view",
    ]
    for cmd in invalid_cmds:
        cases.append(
            TestCase(
                category="7.invalid",
                command=cmd,
                scorer=score_invalid,
            )
        )
    cases.append(
        TestCase(
            category="7.invalid",
            command="Route me from Atlantis to Wakanda and add a todo to leave in 15 minutes",
            scorer=score_partial_route_with_todo,
        )
    )

    # 8. Forced fallback tests
    cases.append(
        TestCase(
            category="8.fallback",
            command="__test_force_local_fail__",
            scorer=lambda m: score_forced_fallback(m, marker="__test_force_local_fail__"),
        )
    )
    if include_optional_fallback:
        for marker in ("__test_force_invalid_tool__", "__test_force_bad_json__"):
            cases.append(
                TestCase(
                    category="8.fallback",
                    command=marker,
                    optional=True,
                    scorer=lambda m, mk=marker: score_forced_fallback(m, marker=mk),
                )
            )

    return cases


def main() -> int:
    parser = argparse.ArgumentParser(description="Live Atlas planner stress test")
    parser.add_argument(
        "--category",
        action="append",
        help="Run only categories whose id starts with this prefix (e.g. 1, 3, 8)",
    )
    parser.add_argument(
        "--atlas-url",
        default=DEFAULT_ATLAS_URL,
        help=f"Atlas base URL (default {DEFAULT_ATLAS_URL})",
    )
    parser.add_argument(
        "--activity-log",
        type=Path,
        default=DEFAULT_ACTIVITY_LOG,
        help="Path to logs/activity.log",
    )
    parser.add_argument(
        "--max-wait",
        type=float,
        default=45.0,
        help="Seconds to wait per command for turn completion",
    )
    parser.add_argument(
        "--include-optional-fallback",
        action="store_true",
        help="Include __test_force_invalid_tool__ / __test_force_bad_json__ (likely unimplemented)",
    )
    args = parser.parse_args()

    cases = build_test_cases(include_optional_fallback=args.include_optional_fallback)
    if args.category:
        prefixes = args.category
        cases = [c for c in cases if any(c.category.startswith(p) for p in prefixes)]

    if not cases:
        print("No test cases selected.", file=sys.stderr)
        return 1

    print(f"Atlas URL: {args.atlas_url}")
    print(f"Activity log: {args.activity_log}")
    print(f"Cases: {len(cases)}")
    wait_atlas(args.atlas_url)

    results: list[tuple[TestCase, object, str, str]] = []
    summary_rows: list[dict] = []

    pass_n = partial_n = fail_n = 0

    for i, case in enumerate(cases, start=1):
        print(f"\n[{i}/{len(cases)}] [{case.category}] {case.command}")
        try:
            metrics = run_live_command(
                case.command,
                log_path=args.activity_log,
                atlas_url=args.atlas_url,
                max_wait_s=args.max_wait,
            )
        except Exception as exc:
            print(f"  ERROR: {exc}")
            fail_n += 1
            summary_rows.append(
                {
                    "category": case.category,
                    "command": case.command[:56],
                    "score": "FAIL",
                    "steps": 0,
                    "planner_paths": "-",
                    "tools": "-",
                    "total_ms": 0,
                    "openai_planner": "?",
                    "notes": str(exc),
                }
            )
            continue

        score, note = case.scorer(metrics)
        if case.optional and score == "PARTIAL" and "not implemented" in note:
            score = "PARTIAL"
        if score == "PASS":
            pass_n += 1
        elif score == "PARTIAL":
            partial_n += 1
        else:
            fail_n += 1

        tools = " -> ".join(metrics.tools) if metrics.tools else "-"
        paths = ",".join({s.path for s in metrics.steps}) or "-"
        print(
            f"  score={score} steps={len(metrics.steps)} paths={paths} tools={tools} "
            f"wall={int(metrics.wall_ms)}ms oai_planner={metrics.openai_planner_used_any} "
            f"audio_tokens={metrics.output_audio_tokens} guard={metrics.repeated_tool_guard}"
        )
        if note:
            print(f"  note: {note}")
        if metrics.final_response_text:
            snippet = metrics.final_response_text[:120].replace("\n", " ")
            print(f"  final: {snippet}")

        results.append((case, metrics, score, note))
        summary_rows.append(format_summary_row(case.category, case.command, score, metrics, note))

    print_summary_table(summary_rows)
    print_grouped_findings(results)

    print("")
    print(f"Totals: PASS={pass_n} PARTIAL={partial_n} FAIL={fail_n} / {len(cases)}")
    return 0 if fail_n == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
