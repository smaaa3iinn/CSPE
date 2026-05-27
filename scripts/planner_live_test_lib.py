"""Shared live Atlas planner test harness (POST /text → activity.log metrics)."""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPO = Path(__file__).resolve().parents[1]
DEFAULT_ACTIVITY_LOG = REPO / "logs" / "activity.log"
DEFAULT_ATLAS_URL = "http://127.0.0.1:5055"

Score = Literal["PASS", "PARTIAL", "FAIL"]

_CORRELATION_SUFFIX = re.compile(r"\s+\[[0-9a-f]{8}\]\s*$", re.I)
_TURN_TYPED = re.compile(
    r"\[Turn (\d+)\] You typed: (.+?) \[[0-9a-f]{8}\]",
)
_PLANNER_LIVE_STEP = re.compile(
    r"\[PlannerLive\] step=(\d+) user='(?P<user>[^']*)' "
    r"path=(?P<path>\S+) plan_source=(?P<plan_source>\S+)(?: correlation_id=(?P<cid>[0-9a-f]{8}))?"
    r" model=(?P<model>\S*) latency_ms=(?P<latency>\d+) "
    r"status='(?P<status>[^']*)' tool=(?P<tool>'[^']*'|None) "
    r"args='(?P<args>.*?)'\s+validation_ok=(?P<val_ok>\w+) "
    r"openai_planner_used=(?P<oai>\w+) "
    r"openai_planner_fallback=(?P<fallback>\w+) fallback_reason='(?P<fb_reason>[^']*)' "
    r"final_openai_response=\w+"
)


_PLANNER_LIVE_STEP_LEGACY = re.compile(
    r"\[PlannerLive\] step=(\d+) user='(?P<user>[^']*)' "
    r"path=(?P<path>\S+) model=(?P<model>\S*) latency_ms=(?P<latency>\d+) "
    r"status='(?P<status>[^']*)' tool=(?P<tool>'[^']*'|None) "
    r"args='(?P<args>.*?)'\s*(?:validation_ok=(?P<val_ok>\w+)\s+)?"
    r"openai_planner_used=(?P<oai>\w+) "
    r"openai_planner_fallback=(?P<fallback>\w+) fallback_reason='(?P<fb_reason>[^']*)' "
    r"final_openai_response=\w+"
)


def _parse_planner_live_step(line: str) -> re.Match | None:
    m = _PLANNER_LIVE_STEP.search(line)
    if m:
        return m
    return _PLANNER_LIVE_STEP_LEGACY.search(line)


_TURN_COMPLETE = re.compile(
    r"\[Turn (\d+)\] \[Planner\] Turn complete: status=(\w+) steps=(\d+)"
)
_FINAL_DONE = re.compile(
    r"\[Turn (\d+)\] \[PlannerLive\] final_openai_response=done"
    r"(?: correlation_id=([0-9a-f]{8}))?"
    r" text_only=true output_audio_tokens=(\d+)"
)
_FINAL_QUEUED = re.compile(
    r"\[Turn (\d+)\] \[PlannerLive\] final_openai_response=queued"
    r"(?: correlation_id=([0-9a-f]{8}))?"
)
_RT_QUEUE = re.compile(r"\[RT\] Response already in flight, queuing")
_REPEATED_GUARD = re.compile(r"\[PlannerLive\] repeated_tool_guard=true")
_RAW_TEXT = re.compile(r"\[Turn (\d+)\] \[Atlas Response\] Raw text: '(.*)'$")
_CRASH_MARKERS = (
    "Traceback (most recent call last)",
    "Unhandled exception",
    "Planner turn failed",
)


@dataclass
class PlannerStepMetrics:
    step_index: int
    path: str
    plan_source: str
    latency_ms: int
    status: str
    tool: str | None
    args_raw: str
    args: dict[str, Any]
    openai_planner_used: bool
    openai_planner_fallback: bool
    fallback_reason: str
    validation_ok: bool = True


@dataclass
class TurnMetrics:
    correlation_id: str
    command: str
    turn_number: int | None = None
    steps: list[PlannerStepMetrics] = field(default_factory=list)
    turn_status: str | None = None
    executed_step_count: int = 0
    tools: list[str] = field(default_factory=list)
    wall_ms: float = 0.0
    openai_planner_used_any: bool = False
    openai_planner_fallback_any: bool = False
    openai_final_response_used: bool = False
    openai_final_response_done: bool = False
    output_audio_tokens: int = 0
    repeated_tool_guard: bool = False
    ui_atlas_transport_action_count: int = 0
    ui_search_stops_count: int = 0
    final_response_text: str = ""
    turn_complete: bool = False
    crashed: bool = False
    log_lines: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class TestCase:
    category: str
    command: str
    scorer: Callable[[TurnMetrics], tuple[Score, str]]
    sequence_group: str | None = None
    optional: bool = False


def strip_correlation_id(text: str) -> str:
    return _CORRELATION_SUFFIX.sub("", (text or "").strip()).strip()


def make_correlation_id() -> str:
    return uuid.uuid4().hex[:8]


def attach_correlation(command: str, correlation_id: str | None = None) -> tuple[str, str]:
    cid = correlation_id or make_correlation_id()
    return f"{command.strip()}  [{cid}]", cid


def wait_atlas(url: str = DEFAULT_ATLAS_URL, timeout_s: float = 5.0) -> None:
    deadline = time.monotonic() + timeout_s
    last_err: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with urlopen(f"{url.rstrip('/')}/health", timeout=3) as resp:
                if resp.status < 500:
                    return
        except (HTTPError, URLError, TimeoutError) as exc:
            last_err = exc
            time.sleep(0.3)
    raise RuntimeError(f"Atlas not reachable at {url}/health: {last_err}")


def post_atlas_text(text: str, *, url: str = DEFAULT_ATLAS_URL, timeout_s: float = 30.0) -> None:
    body = json.dumps({"text": text}).encode("utf-8")
    req = Request(
        f"{url.rstrip('/')}/text",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=timeout_s) as resp:
        if resp.status >= 400:
            raise RuntimeError(f"POST /text failed: HTTP {resp.status}")


def _read_log_tail(log_path: Path, max_lines: int = 8000) -> list[str]:
    if not log_path.is_file():
        return []
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    lines = text.splitlines()
    if len(lines) > max_lines:
        lines = lines[-max_lines:]
    return lines


def _parse_bool(raw: str) -> bool:
    return raw.strip().lower() in ("true", "1", "yes")


def _parse_args(raw: str) -> dict[str, Any]:
    if not raw or raw in ("{}", "None"):
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {"_raw": raw}


def _lines_for_turn(all_lines: list[str], turn_number: int) -> list[str]:
    prefix = f"[Turn {turn_number}]"
    out: list[str] = []
    for line in all_lines:
        if prefix in line:
            out.append(line)
    return out


def _lines_for_correlated_turn(
    all_lines: list[str],
    turn_number: int,
    correlation_id: str,
) -> list[str]:
    """Turn-scoped lines anchored at the matching You typed line (avoids stale session reuse)."""
    typed_marker = f"[Turn {turn_number}] You typed:"
    anchor: int | None = None
    for i, line in enumerate(all_lines):
        if typed_marker in line and correlation_id in line:
            anchor = i
            break
    if anchor is None:
        return _lines_for_turn(all_lines, turn_number)

    prefix = f"[Turn {turn_number}]"
    other_turn = re.compile(r"\[Turn (\d+)\]")
    out: list[str] = []
    for line in all_lines[anchor:]:
        m = other_turn.search(line)
        if m and int(m.group(1)) != turn_number:
            if out:
                break
            continue
        if prefix in line:
            out.append(line)
    return out


def _fill_turn_metrics(metrics: TurnMetrics, turn_lines: list[str]) -> None:
    steps: list[PlannerStepMetrics] = []
    seen_step_idx: set[int] = set()
    final_done_for_turn = False
    planner_turn_complete = False

    for line in turn_lines:
        if any(marker in line for marker in _CRASH_MARKERS):
            metrics.crashed = True

        sm = _parse_planner_live_step(line)
        if sm:
            idx = int(sm.group(1))
            if idx not in seen_step_idx:
                seen_step_idx.add(idx)
                args_raw = sm.group("args")
                tool_raw = sm.group("tool")
                tool_name = None
                if tool_raw.startswith("'"):
                    inner = tool_raw[1:-1]
                    tool_name = None if inner == "None" else inner
                plan_src = sm.groupdict().get("plan_source") or sm.group("path")
                val_ok = sm.groupdict().get("val_ok")
                steps.append(
                    PlannerStepMetrics(
                        step_index=idx,
                        path=sm.group("path"),
                        plan_source=plan_src,
                        latency_ms=int(sm.group("latency")),
                        status=sm.group("status"),
                        tool=tool_name,
                        args_raw=args_raw,
                        args=_parse_args(args_raw),
                        openai_planner_used=_parse_bool(sm.group("oai")),
                        openai_planner_fallback=_parse_bool(sm.group("fallback")),
                        fallback_reason=sm.group("fb_reason"),
                        validation_ok=_parse_bool(val_ok) if val_ok else True,
                    )
                )

        tm = _TURN_COMPLETE.search(line)
        if tm:
            metrics.turn_status = tm.group(2)
            metrics.executed_step_count = int(tm.group(3))
            planner_turn_complete = True

        if _REPEATED_GUARD.search(line):
            metrics.repeated_tool_guard = True

        if _RT_QUEUE.search(line):
            metrics.notes.append("RT response queued while previous in flight")

        if "transport_ui atlas_transport_action" in line or "transport_action_enqueued" in line:
            metrics.ui_atlas_transport_action_count += 1

        if "[UI] [ToolCall] transport.search_stops" in line:
            metrics.ui_search_stops_count += 1

        fd = _FINAL_DONE.search(line)
        if fd:
            turn_n = int(fd.group(1))
            corr = fd.group(2)
            if metrics.turn_number is None or turn_n == metrics.turn_number:
                if corr is None or corr == metrics.correlation_id:
                    final_done_for_turn = True
                    metrics.openai_final_response_used = True
                    metrics.openai_final_response_done = True
                    metrics.output_audio_tokens = int(fd.group(3))

        fq = _FINAL_QUEUED.search(line)
        if fq:
            turn_n = int(fq.group(1))
            corr = fq.group(2)
            if metrics.turn_number is None or turn_n == metrics.turn_number:
                if corr is None or corr == metrics.correlation_id:
                    metrics.openai_final_response_used = True

        rt = _RAW_TEXT.search(line)
        if rt:
            metrics.final_response_text = rt.group(2)

    steps.sort(key=lambda s: s.step_index)
    metrics.steps = steps
    metrics.tools = [s.tool for s in steps if s.tool]
    metrics.openai_planner_used_any = any(s.openai_planner_used for s in steps)
    metrics.openai_planner_fallback_any = any(s.openai_planner_fallback for s in steps)

    if metrics.turn_status == "clarify":
        metrics.turn_complete = True
    elif metrics.turn_status == "direct" and (final_done_for_turn or steps):
        metrics.turn_complete = True
    elif final_done_for_turn and (planner_turn_complete or not steps):
        metrics.turn_complete = True
    elif metrics.turn_status == "done" and metrics.executed_step_count > 0 and metrics.steps:
        metrics.turn_complete = False


def collect_turn_metrics(
    *,
    correlation_id: str,
    command: str,
    log_path: Path,
    baseline_line_count: int,
    started_monotonic: float,
    max_wait_s: float = 45.0,
) -> TurnMetrics:
    metrics = TurnMetrics(correlation_id=correlation_id, command=command)
    deadline = time.monotonic() + max_wait_s
    turn_number: int | None = None

    while time.monotonic() < deadline:
        lines = _read_log_tail(log_path)
        new_lines = lines[baseline_line_count:] if baseline_line_count < len(lines) else lines

        if turn_number is None:
            for line in reversed(new_lines):
                if correlation_id not in line:
                    continue
                m = _TURN_TYPED.search(line)
                if m and correlation_id in line:
                    turn_number = int(m.group(1))
                    metrics.turn_number = turn_number
                    break

        if turn_number is not None:
            turn_lines = _lines_for_correlated_turn(lines, turn_number, correlation_id)
            metrics.log_lines = turn_lines
            _fill_turn_metrics(metrics, turn_lines)
            if metrics.turn_complete and not metrics.crashed:
                metrics.wall_ms = (time.monotonic() - started_monotonic) * 1000
                return metrics

        for line in new_lines:
            if correlation_id in line and any(marker in line for marker in _CRASH_MARKERS):
                metrics.crashed = True
                metrics.notes.append("crash marker in log")

        time.sleep(0.4)

    metrics.wall_ms = (time.monotonic() - started_monotonic) * 1000
    if turn_number is None:
        metrics.notes.append("turn not found in activity.log")
    elif not metrics.turn_complete:
        metrics.notes.append("timed out before final_openai_response=done")
    return metrics


def run_live_command(
    command: str,
    *,
    log_path: Path = DEFAULT_ACTIVITY_LOG,
    atlas_url: str = DEFAULT_ATLAS_URL,
    max_wait_s: float = 45.0,
    correlation_id: str | None = None,
) -> TurnMetrics:
    sent, cid = attach_correlation(command, correlation_id)
    baseline = len(_read_log_tail(log_path))
    t0 = time.monotonic()
    post_atlas_text(sent, url=atlas_url)
    return collect_turn_metrics(
        correlation_id=cid,
        command=command,
        log_path=log_path,
        baseline_line_count=baseline,
        started_monotonic=t0,
        max_wait_s=max_wait_s,
    )


# --- Scoring helpers ---


def _first_step(m: TurnMetrics) -> PlannerStepMetrics | None:
    return m.steps[0] if m.steps else None


def score_shortcut_fast(
    m: TurnMetrics,
    *,
    expected_tools: Iterable[str] | None = None,
    max_latency_ms: int = 200,
) -> tuple[Score, str]:
    if m.crashed:
        return "FAIL", "crash detected"
    if not m.turn_complete and m.turn_status != "direct":
        return "FAIL", "; ".join(m.notes) or "incomplete turn"
    step = _first_step(m)
    if not step:
        if m.turn_status == "direct":
            return "PASS", "direct response (no tool step logged)"
        return "FAIL", "missing PlannerLive step"
    if step.path not in ("shortcut", "decomposer") and step.plan_source not in ("shortcut", "decomposer"):
        return "FAIL", f"expected shortcut/decomposer path, got {step.path}/{step.plan_source}"
    if step.latency_ms > max_latency_ms:
        return "PARTIAL", f"shortcut ok but slow ({step.latency_ms} ms > {max_latency_ms})"
    if step.openai_planner_used:
        return "FAIL", "OpenAI planner used unexpectedly"
    if expected_tools:
        exp = set(expected_tools)
        if step.tool not in exp:
            return "FAIL", f"expected tool {sorted(exp)}, got {step.tool!r}"
    if m.repeated_tool_guard:
        return "FAIL", "repeated_tool_guard triggered"
    return "PASS", "shortcut fast path"


def score_route_shortcut(m: TurnMetrics) -> tuple[Score, str]:
    if m.crashed:
        return "FAIL", "crash detected"
    step = _first_step(m)
    if not step:
        return "FAIL", "missing planner step"
    if step.path not in ("shortcut", "decomposer") or step.tool != "cspe_compute_route":
        return "FAIL", f"expected shortcut/decomposer cspe_compute_route, got {step.path}/{step.tool}"
    if not step.args.get("sync_ui"):
        return "PARTIAL", "route ok but sync_ui not true in args"
    if step.openai_planner_used:
        return "FAIL", "OpenAI planner used"
    if m.repeated_tool_guard:
        return "FAIL", "repeated loop"
    if m.ui_atlas_transport_action_count > 5:
        return "PARTIAL", f"UI transport action repeated ({m.ui_atlas_transport_action_count}x)"
    return "PASS", "route shortcut with sync_ui"


def score_route_and_todo(m: TurnMetrics) -> tuple[Score, str]:
    """Route + todo composite: PASS only if both tools run with a clean destination."""
    if m.crashed:
        return "FAIL", "crash detected"
    if not m.turn_complete:
        return "FAIL", "; ".join(m.notes) or "incomplete turn (waiting for final_openai_response=done)"

    route_step = next((s for s in m.steps if s.tool == "cspe_compute_route"), None)
    if route_step:
        to_q = str(route_step.args.get("to_query") or "").lower()
        polluted_markers = ("todo", "remind", "leave in", "add a", "and open")
        if any(marker in to_q for marker in polluted_markers):
            return "FAIL", f"to_query includes todo phrase: {to_q!r}"

    tools = set(m.tools)
    if "cspe_compute_route" in tools and "memory_add" in tools:
        return "PASS", "route + memory_add executed"
    if "cspe_compute_route" in tools:
        return "PARTIAL", "route only; memory_add missing"
    return "FAIL", f"expected cspe_compute_route + memory_add, got {m.tools}"


def score_multi_step_ordered(
    m: TurnMetrics,
    *,
    expected_tools: list[str],
    allow_openai_planner: bool = False,
) -> tuple[Score, str]:
    """PASS only if all expected tools executed in order."""
    if m.crashed:
        return "FAIL", "crash detected"
    if not m.turn_complete:
        return "FAIL", "; ".join(m.notes) or "incomplete turn"
    if m.repeated_tool_guard:
        return "FAIL", "repeated loop"
    if not allow_openai_planner and m.openai_planner_used_any:
        return "FAIL", "OpenAI planner used unexpectedly"

    route_step = next((s for s in m.steps if s.tool == "cspe_compute_route"), None)
    if route_step:
        to_q = str(route_step.args.get("to_query") or "").lower()
        if any(p in to_q for p in ("todo", "remind", "leave in", "add a")):
            return "FAIL", f"to_query polluted: {to_q!r}"

    if m.tools == expected_tools:
        src = m.steps[0].plan_source if m.steps else "?"
        return "PASS", f"ordered multi-step ({src}): {' -> '.join(m.tools)}"
    if len(m.tools) >= 1 and set(expected_tools).issubset(set(m.tools)):
        return "PARTIAL", f"got {m.tools}, expected order {expected_tools}"
    if len(m.tools) >= 1:
        return "PARTIAL", f"partial {m.tools}, expected {expected_tools}"
    return "FAIL", f"no tools executed; expected {expected_tools}"


def score_partial_route_with_todo(m: TurnMetrics) -> tuple[Score, str]:
    """Route failure + independent memory_add should be PARTIAL/PASS with honest summary."""
    if m.crashed:
        return "FAIL", "crash detected"
    if not m.turn_complete:
        return "FAIL", "; ".join(m.notes) or "incomplete turn"
    route_step = next((s for s in m.steps if s.tool == "cspe_compute_route"), None)
    mem_step = next((s for s in m.steps if s.tool == "memory_add"), None)
    if route_step and mem_step:
        if route_step.args.get("to_query") and any(
            p in str(route_step.args.get("to_query", "")).lower()
            for p in ("todo", "remind", "leave in")
        ):
            return "FAIL", "to_query polluted with todo phrase"
        text = (m.final_response_text or "").lower()
        if "memory_add" in m.tools and "cspe_compute_route" in m.tools:
            if any(w in text for w in ("partial", "unable", "could not", "issue", "fail")):
                return "PASS", "partial success: route failed, todo added"
            return "PARTIAL", "both tools ran; final may not mention route failure clearly"
        return "PARTIAL", f"tools={m.tools}"
    if mem_step and not route_step:
        return "PARTIAL", "memory only"
    if route_step and not mem_step:
        return "PARTIAL", "route only"
    return "FAIL", f"expected route+memory partial, got {m.tools}"


def score_multi_step(m: TurnMetrics, *, expected_tools: list[set[str]] | None = None) -> tuple[Score, str]:
    """Accept multi-tool execution OR honest single-tool + clarify/direct."""
    if m.crashed:
        return "FAIL", "crash detected"
    if not m.turn_complete and m.turn_status not in ("clarify", "direct"):
        return "FAIL", "; ".join(m.notes) or "incomplete turn"

    n = len(m.tools)
    if n >= 2:
        if m.repeated_tool_guard:
            return "FAIL", "repeated loop during multi-step"
        return "PASS", f"multi-step executed ({' -> '.join(m.tools)})"

    step = _first_step(m)
    if step and step.status == "clarify":
        return "PARTIAL", "clarify - multi-step decomposition not supported"

    if m.turn_status == "clarify":
        return "PARTIAL", "clarify - only first action handled"

    expected_first: set[str] = set()
    if expected_tools:
        expected_first = expected_tools[0] if expected_tools else set()

    if n == 1:
        tool = m.tools[0]
        if expected_first and tool in expected_first:
            return "PARTIAL", f"only first action ran ({tool}); later actions ignored"
        return "PARTIAL", f"single tool {tool}; multi-step not decomposed"

    if m.turn_status == "direct":
        return "PARTIAL", "direct response without tool chain"

    return "FAIL", "no tools and no clarify"


def score_follow_up(m: TurnMetrics, *, kind: str) -> tuple[Score, str]:
    if m.crashed:
        return "FAIL", "crash detected"
    step = _first_step(m)
    if m.turn_status == "clarify" or (step and step.status == "clarify"):
        return "PASS", "honest clarify for ambiguous follow-up"
    if not m.turn_complete:
        return "FAIL", "; ".join(m.notes) or "incomplete"

    if kind == "3d" and step and step.tool == "cspe_open_graph3d":
        return "PASS", "opened 3D from follow-up"
    if kind == "search" and step and step.tool == "cspe_search_stops":
        q = (step.args.get("query") or "").lower()
        if "republique" in q or "république" in q:
            return "PASS", "contextual search near République"
        return "PARTIAL", f"search ok but query={q!r} may lack context"
    if kind == "memory" and step and step.tool == "memory_add":
        return "PASS", "memory follow-up"
    if kind == "route" and step and step.tool == "cspe_compute_route":
        return "PASS", "route follow-up"

    if step and step.tool:
        return "PARTIAL", f"tool {step.tool} - context link uncertain"
    return "PARTIAL", "no clear tool; may need clarify"


def score_fuzzy_or_clarify(
    m: TurnMetrics,
    *,
    prefer_tools: Iterable[str] | None = None,
) -> tuple[Score, str]:
    if m.crashed:
        return "FAIL", "crash detected"
    if m.repeated_tool_guard:
        return "FAIL", "repeated loop"
    step = _first_step(m)
    if m.turn_status == "clarify" or (step and step.status == "clarify"):
        return "PASS", "clean clarify"
    if not step:
        return "FAIL", "no planner step"
    if step.openai_planner_used and step.path.startswith("fallback"):
        return "PARTIAL", f"OpenAI fallback used ({step.path})"
    if prefer_tools and step.tool in set(prefer_tools):
        return "PASS", f"resolved via {step.tool}"
    if step.tool:
        return "PARTIAL", f"unexpected tool {step.tool}"
    return "FAIL", "no resolution"


def score_invalid(m: TurnMetrics, *, expect_clarify: bool = True) -> tuple[Score, str]:
    if m.crashed:
        return "FAIL", "crash detected"
    if m.repeated_tool_guard:
        return "FAIL", "repeated tool loop on invalid input"
    if len(m.tools) > 3:
        return "FAIL", f"too many tool steps ({len(m.tools)})"
    step = _first_step(m)
    if m.turn_status == "clarify" or (step and step.status == "clarify"):
        return "PASS", "clarify on invalid input"
    if expect_clarify and m.turn_status == "direct":
        text = m.final_response_text.lower()
        if any(w in text for w in ("can't", "cannot", "unable", "don't", "sorry", "clarify", "invalid")):
            return "PASS", "direct failure/clarify message"
        return "PARTIAL", "direct response may not clarify failure"
    if m.turn_complete:
        return "PARTIAL", f"completed with tools={m.tools}"
    return "FAIL", "; ".join(m.notes) or "incomplete"


def score_forced_fallback(m: TurnMetrics, *, marker: str) -> tuple[Score, str]:
    if m.crashed:
        return "FAIL", "crash detected"
    step = _first_step(m)
    if marker == "__test_force_local_fail__":
        if step and (
            step.openai_planner_fallback
            or step.path in ("fallback_error", "openai", "fallback_slow", "openai_fallback")
        ):
            if m.output_audio_tokens != 0:
                return "PARTIAL", f"fallback ok but output_audio_tokens={m.output_audio_tokens}"
            if m.turn_status == "direct" and m.final_response_text:
                return "PASS", "forced fallback with direct UX message"
            if m.turn_complete:
                return "PASS", "forced fallback completed"
            return "PARTIAL", "fallback triggered but turn incomplete"
        if m.turn_status == "direct" and "Fallback test completed" in (m.final_response_text or ""):
            return "PASS", "forced fallback direct summary"
        if any("openai_fallback" in line or "fallback_error" in line for line in m.log_lines):
            if m.turn_complete and m.output_audio_tokens == 0:
                return "PASS", "forced fallback via planner pipeline log"
        if not step:
            return "FAIL", "missing planner step"
        return "FAIL", f"expected fallback, got path={step.path}"
    return "PARTIAL", f"optional marker {marker} not implemented - skipped"


def format_summary_row(
    category: str,
    command: str,
    score: Score,
    metrics: TurnMetrics,
    notes: str,
) -> dict[str, Any]:
    paths = ",".join(sorted({s.path for s in metrics.steps})) or "-"
    tools = " -> ".join(metrics.tools) if metrics.tools else "-"
    oai = "yes" if metrics.openai_planner_used_any else "no"
    return {
        "category": category,
        "command": command[:56] + ("..." if len(command) > 56 else ""),
        "score": score,
        "steps": len(metrics.steps),
        "planner_paths": paths,
        "tools": tools,
        "total_ms": int(metrics.wall_ms),
        "openai_planner": oai,
        "notes": notes,
    }


def print_summary_table(rows: list[dict[str, Any]]) -> None:
    headers = [
        "Category",
        "Command",
        "Score",
        "Steps",
        "Planner paths",
        "Tools",
        "Total ms",
        "OpenAI planner?",
        "Notes",
    ]
    print("")
    print("=== Summary ===")
    print(" | ".join(headers))
    print("-" * 140)
    for row in rows:
        print(
            f"{row['category']} | {row['command']} | {row['score']} | {row['steps']} | "
            f"{row['planner_paths']} | {row['tools']} | {row['total_ms']} | "
            f"{row['openai_planner']} | {row['notes']}"
        )


def print_grouped_findings(results: list[tuple[TestCase, TurnMetrics, Score, str]]) -> None:
    works: list[str] = []
    shortcuts_only: list[str] = []
    local_planner: list[str] = []
    openai_fallback: list[str] = []
    fails: list[str] = []
    multi: list[str] = []

    for case, metrics, score, note in results:
        label = f"[{case.category}] {case.command[:50]}"
        step = _first_step(metrics)
        path = step.path if step else metrics.turn_status or "?"

        if score == "FAIL":
            fails.append(f"{label} - {note}")
        elif score == "PASS":
            works.append(f"{label} ({path})")
        elif path == "shortcut":
            shortcuts_only.append(f"{label} - {note}")
        elif path.startswith("fallback") or metrics.openai_planner_fallback_any:
            openai_fallback.append(f"{label} - {note}")
        elif path in ("local_fast", "local_heavy", "local"):
            local_planner.append(f"{label} - {note}")
        else:
            works.append(f"{label} - {note}")

        if case.category.startswith("3.") and len(metrics.tools) < 2 and score != "PASS":
            multi.append(f"{label}: {len(metrics.tools)} tool(s) - {note}")

    print("")
    print("=== Grouped findings ===")
    sections = [
        ("Works reliably", works),
        ("Shortcut-only (partial but acceptable)", shortcuts_only),
        ("Requires local planner", local_planner),
        ("OpenAI fallback used", openai_fallback),
        ("Fails", fails),
        ("Multi-step gaps", multi),
    ]
    for title, items in sections:
        print(f"\n{title}:")
        if not items:
            print("  (none)")
        else:
            for item in items:
                print(f"  - {item}")

    print("\nMulti-step support:")
    multi_pass = sum(1 for c, m, s, _ in results if c.category.startswith("3.") and s == "PASS")
    multi_total = sum(1 for c, _, _, _ in results if c.category.startswith("3."))
    if multi_pass == 0:
        print("  No category-3 multi-step tests passed — check decomposer path and agent_planner execution.")
    elif multi_pass < multi_total:
        print(f"  Partial multi-step: {multi_pass}/{multi_total} composite commands ran all expected tools in order.")
    else:
        print(f"  Multi-step decomposer pipeline: {multi_pass}/{multi_total} tests passed.")

    print("\nSuggested follow-ups:")
    print("  1. Extend decomposer patterns for new composite voice commands.")
    print("  2. Keep OpenAI planner fallback for complex_unknown only.")
    print("  3. Log plan_source + validation_ok on every PlannerLive step (already in Option D).")
    print("  4. Keep correlation_id stripping in planner_user_text for all parsers.")
