#!/usr/bin/env python3
"""
Test / benchmark local Ollama planner.

Usage:
  .\\scripts\\test_local_planner.ps1
  .\\scripts\\test_local_planner.ps1 -Benchmark
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ATLAS_ROOT = REPO / "src" / "work" / "atlas"
sys.path.insert(0, str(ATLAS_ROOT))

os.environ.setdefault("ATLAS_PLANNER_BACKEND", "local")
os.environ.setdefault("ATLAS_LOCAL_PLANNER_URL", "http://127.0.0.1:11434")
os.environ.setdefault("ATLAS_LOCAL_PLANNER_MODEL", "qwen2.5:3b-instruct")
os.environ.setdefault("ATLAS_LOCAL_PLANNER_MODEL_HEAVY", "qwen2.5:7b-instruct")
os.environ.setdefault("ATLAS_LOCAL_PLANNER_FALLBACK_OPENAI", "0")
if (os.environ.get("ATLAS_LOCAL_PLANNER_TIMEOUT") or "").strip() in ("", "20"):
    os.environ["ATLAS_LOCAL_PLANNER_TIMEOUT"] = "60"

from src.atlas_client.core.agent_planner import _plan_next_step_openai  # noqa: E402
from src.atlas_client.core.planner_config import (  # noqa: E402
    local_planner_fallback_openai,
    local_planner_model,
    local_planner_model_heavy,
    local_planner_timeout,
    planner_backend,
)
from src.atlas_client.router.local_planner import (  # noqa: E402
    LocalPlannerError,
    allowed_tool_names,
    benchmark_local_planner,
    compact_tool_catalog,
    plan_next_step_with_backend,
    validate_planner_decision,
    warmup_local_planner,
)
from src.atlas_client.router.memory_arg_enricher import enrich_memory_add_args  # noqa: E402
from src.atlas_client.router.ollama_runtime import gpu_runtime_report  # noqa: E402
from src.atlas_client.router.planner_domains import (  # noqa: E402
    build_compact_catalog,
    classify_planner_domain,
    domain_tool_names,
)

TEST_UTTERANCES = [
    "Route me from Châtelet to République and open the map",
    "Search stops near République",
    "Open the transport map",
    "Add a todo to leave in 15 minutes",
    "Find the route from Gare de Lyon to La Défense",
    "Show the 3D graph",
    "Switch to transport mode",
    "What can you do?",
]


def _print_header(title: str) -> None:
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)


def print_gpu_report() -> None:
    _print_header("GPU / Ollama runtime")
    gpu = gpu_runtime_report(model=local_planner_model())
    print(f"  nvidia-smi: {gpu.get('nvidia_smi')}")
    print(f"  ollama processor ({local_planner_model()}): {gpu.get('ollama_processor')}")
    print(f"  ollama ps: {gpu.get('ollama_ps')}")
    proc = gpu.get("ollama_processor") or ""
    if "CPU/GPU" in proc or "%/" in proc:
        print(
            "\n  NOTE: partial CPU offload detected — use qwen2.5:3b-instruct "
            "to fit fully on 6GB VRAM."
        )


def test_memory_due_at() -> None:
    _print_header("Memory enricher: relative due_at + task text")
    cases = [
        ("Add a todo to leave in 15 minutes", "Leave"),
        ("Add a todo to leave for République in 15 minutes", "Leave for République"),
        ("Remind me to leave the house in half an hour", "Leave the house"),
        ("Remind me in half an hour to call home", "Call home"),
    ]
    for text, want_text in cases:
        enriched = enrich_memory_add_args(args={"text": "Leave"}, user_text=text)
        print(f"\n  USER: {text!r}")
        print(f"  text: {enriched.args.get('text')!r} (want ~{want_text!r})")
        print(f"  due_at: {enriched.args.get('due_at')!r}")
        due = enriched.args.get("due_at")
        if due:
            assert str(due)[:4].isdigit(), f"due_at not ISO: {due}"
        got = enriched.args.get("text") or ""
        if want_text.lower() not in got.lower() and got.lower() != want_text.lower():
            print(f"  NOTE: text mismatch got={got!r}")


def test_planner_utterance(utterance: str, *, allowed: set[str]) -> None:
    print(f"\n--- USER: {utterance!r}")
    domain = classify_planner_domain(utterance)
    scoped = domain_tool_names(domain) & allowed
    cat = build_compact_catalog(scoped or allowed)
    print(f"  domain: {domain} | scoped_tools: {len(scoped)} | prompt_catalog_chars: {len(cat)}")

    def openai_fn():
        return _plan_next_step_openai(
            user_text=utterance,
            tools_catalog_text=compact_tool_catalog(),
            allowed_tools=allowed,
            context_text="",
            steps=[],
            agent_context={},
        )

    try:
        decision, metrics = plan_next_step_with_backend(
            user_text=utterance,
            tools_catalog_text=compact_tool_catalog(),
            allowed_tools=allowed,
            context_text="",
            steps_text="(no steps yet)",
            agent_context={},
            openai_plan_fn=openai_fn,
        )
        ok, _, err = validate_planner_decision(decision, allowed_tools=allowed)
        print(f"  path: {metrics.planner_path or metrics.backend_used}")
        print(f"  model: {metrics.model}")
        print(f"  prompt_chars: {metrics.prompt_chars}")
        print(f"  gpu: {metrics.gpu_status}")
        print(f"  latency_ms: {metrics.latency_ms:.0f}")
        print(f"  validation_ok: {ok} ({err or 'ok'})")
        print(f"  tool: {decision.get('tool_name')} args={decision.get('args')}")
        due = (decision.get("args") or {}).get("due_at")
        if decision.get("tool_name") == "memory_add" and due:
            iso_ok = isinstance(due, str) and due[:4].isdigit() and "T" in due
            print(f"  due_at_iso: {iso_ok} ({due!r})")
        if metrics.fallback_reason:
            print(f"  fallback_reason: {metrics.fallback_reason!r}")
    except LocalPlannerError as exc:
        print(f"  LOCAL FAILED: {exc}")
        if exc.metrics:
            print(f"  latency_ms: {exc.metrics.latency_ms:.0f}")


def run_benchmark(utterances: list[str]) -> None:
    _print_header("Model benchmark")
    print_gpu_report()
    rows = benchmark_local_planner(utterances)
    print(f"\n{'model':<22} {'ms':>7} {'path':<14} {'dom':<10} {'chars':>6} {'ok':>4} tool")
    print("-" * 72)
    for row in rows:
        print(
            f"{row.get('model',''):<22} "
            f"{row.get('latency_ms',0):>7.0f} "
            f"{row.get('path',''):<14} "
            f"{row.get('domain',''):<10} "
            f"{row.get('prompt_chars',0):>6} "
            f"{str(row.get('validation_ok','')):>4} "
            f"{row.get('tool') or row.get('error','')}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", action="store_true", help="Compare multiple Ollama models")
    args = parser.parse_args()

    print(f"Repo: {REPO}")
    print(f"ATLAS_PLANNER_BACKEND={planner_backend()}")
    print(f"fast_model={local_planner_model()} heavy_model={local_planner_model_heavy()}")
    print(f"timeout={local_planner_timeout()}s fallback_openai={local_planner_fallback_openai()}")

    full = compact_tool_catalog()
    allowed = allowed_tool_names()
    print(f"Full catalog: {len(full)} chars / {len(allowed)} tools")

    test_memory_due_at()
    print_gpu_report()

    if args.benchmark:
        run_benchmark(TEST_UTTERANCES)
        return 0

    _print_header(f"Local planner tests ({len(TEST_UTTERANCES)} utterances)")
    try:
        print("\nWarming up fast model...")
        warmup_local_planner()
        print("Warmup OK.")
    except Exception as exc:
        print(f"Warmup warning: {exc}")

    for u in TEST_UTTERANCES:
        test_planner_utterance(u, allowed=allowed)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
