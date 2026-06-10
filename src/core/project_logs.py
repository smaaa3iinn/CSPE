"""Central project logging: logs/health.log, logs/activity.log, logs/activity_compact.log."""

from __future__ import annotations

import logging
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LOG_DIR = Path(os.getenv("CSPE_LOG_DIR", str(_REPO_ROOT / "logs")))
_HEALTH_LOG = Path(os.getenv("CSPE_HEALTH_LOG", str(_LOG_DIR / "health.log")))
_ACTIVITY_LOG = Path(os.getenv("CSPE_ACTIVITY_LOG", str(_LOG_DIR / "activity.log")))
_COMPACT_LOG = Path(os.getenv("CSPE_COMPACT_LOG", str(_LOG_DIR / "activity_compact.log")))

_ROOTS_CONFIGURED = False
_RESET_DONE = False
_LOCK = threading.Lock()

CAT_STARTUP = "Startup"
CAT_PLANNER = "Planner"
CAT_TOOL = "Tool"
CAT_TRANSPORT = "transport"
CAT_UI = "ui_action"
CAT_MAP = "MapRender"
CAT_HTTP = "http_access"
CAT_ERRORS = "Slow"

_HEALTH_PATHS = frozenset({"/health", "/api/health"})

_HTTP_SUPPRESS_PATHS = frozenset(
    {
        "/api/shell/poll",
        "/ui",
        "/api/atlas/ui",
        "/api/transport/stats",
        "/api/shell/client-log",
        "/api/agent/events",
        "/api/shell/enqueue",
        "/api/atlas/input-mode",
        "/api/chat",
    }
)
_HTTP_SUPPRESS_PREFIXES = (
    "/api/agent/context",
    "/api/transport/stops/search",
    "/api/transport/graph3d/session",
)

_SLOW_MS = {
    "planner": 3000,
    "tool_execution": 2000,
    "map_render": 3000,
    "backend_request": 1000,
}

_COMPACT_DEMOTE_PATTERNS = re.compile(
    r"(\[RT\]|\[VAD\]|Response started|Response done|Response created|"
    r"Response already in flight|Flushing queued|Tool calls detected|"
    r"Tool-First Policy|Acknowledgment:|Event: response\.(created|output_item|content_part)|"
    r"You typed:|You said:|Atlas said:|\[TTS\]|Raw text:|Final text:|"
    r"Starting Atlas session|\[Planner\] backend=|\[Planner\] command=|"
    r"\[Planner\] path=|\[Planner\] execution|\[Planner\] Turn complete|"
    r"\[Planner\] correlation_id=|\[PlannerMetrics\]|Realtime session|Connected\.|"
    r"\[InputMode\])",
    re.I,
)

_TRACE_RT_EVENT_TYPES = frozenset(
    {
        "response.output_text.delta",
        "response.created",
        "response.output_item.added",
        "response.content_part.added",
        "response.content_part.done",
        "response.output_item.done",
    }
)

_dedupe_cache: dict[str, float] = {}
_dedupe_ttl_s = 2.0
_turn_ctx: dict[str, Any] = {}


def repo_root() -> Path:
    return _REPO_ROOT


def log_dir() -> Path:
    return _LOG_DIR


def health_log_path() -> Path:
    return _HEALTH_LOG


def activity_log_path() -> Path:
    return _ACTIVITY_LOG


def compact_log_path() -> Path:
    return _COMPACT_LOG


def get_log_mode() -> str:
    return (os.getenv("CSPE_LOG_MODE") or "compact").strip().lower()


def is_compact_mode() -> bool:
    return get_log_mode() == "compact"


def is_debug_mode() -> bool:
    return get_log_mode() == "debug"


def is_trace_mode() -> bool:
    return get_log_mode() == "trace"


def _mode_activity_level() -> int:
    mode = get_log_mode()
    if mode in ("trace", "debug"):
        return logging.DEBUG
    return logging.INFO


def _should_write_compact_file() -> bool:
    return os.getenv("CSPE_COMPACT_LOG", "1").strip().lower() not in ("0", "false", "no", "off")


def generate_correlation_id() -> str:
    return uuid.uuid4().hex[:8]


def ensure_correlation_id(value: str | None) -> str:
    cid = (value or "").strip()
    return cid if cid else generate_correlation_id()


def reset_project_logs() -> None:
    global _RESET_DONE
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    paths = [_HEALTH_LOG, _ACTIVITY_LOG]
    if _should_write_compact_file():
        paths.append(_COMPACT_LOG)
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    _RESET_DONE = True
    _dedupe_cache.clear()
    _turn_ctx.clear()


def _ensure_roots() -> None:
    global _ROOTS_CONFIGURED
    if _ROOTS_CONFIGURED:
        return
    _LOG_DIR.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    level = _mode_activity_level()

    health_root = logging.getLogger("cspe.health")
    health_root.setLevel(logging.INFO)
    health_root.propagate = False
    if not health_root.handlers:
        h = logging.FileHandler(_HEALTH_LOG, mode="a", encoding="utf-8")
        h.setFormatter(fmt)
        health_root.addHandler(h)

    activity_root = logging.getLogger("cspe.activity")
    activity_root.setLevel(level)
    activity_root.propagate = False
    if not activity_root.handlers:
        h = logging.FileHandler(_ACTIVITY_LOG, mode="a", encoding="utf-8")
        h.setFormatter(fmt)
        activity_root.addHandler(h)

    compact_root = logging.getLogger("cspe.compact")
    compact_root.setLevel(logging.INFO)
    compact_root.propagate = False
    if _should_write_compact_file() and not compact_root.handlers:
        ch = logging.FileHandler(_COMPACT_LOG, mode="a", encoding="utf-8")
        ch.setFormatter(logging.Formatter("%(message)s"))
        compact_root.addHandler(ch)

    _ROOTS_CONFIGURED = True


def apply_log_mode() -> None:
    _ensure_roots()
    level = _mode_activity_level()
    logging.getLogger("cspe.activity").setLevel(level)
    compact_level = logging.WARNING if is_compact_mode() else level
    for name in ("wake", "atlas", "atlas.api"):
        logging.getLogger(name).setLevel(compact_level)
    for suffix in ("wake", "startup", "compact", "dedupe", "turn", "planner", "tool_execution", "map_render", "errors"):
        logging.getLogger(f"cspe.activity.{suffix}").setLevel(compact_level)


def get_health_logger(component: str) -> logging.Logger:
    _ensure_roots()
    logger = logging.getLogger(f"cspe.health.{component.strip() or 'app'}")
    logger.setLevel(logging.INFO)
    logger.propagate = True
    return logger


def get_activity_logger(component: str) -> logging.Logger:
    _ensure_roots()
    logger = logging.getLogger(f"cspe.activity.{component.strip() or 'app'}")
    logger.setLevel(_mode_activity_level())
    logger.propagate = True
    return logger


def get_compact_logger() -> logging.Logger:
    _ensure_roots()
    return logging.getLogger("cspe.compact")


def is_health_path(path: str) -> bool:
    p = (path or "").split("?", 1)[0].rstrip("/") or "/"
    if p in _HEALTH_PATHS:
        return True
    return p.endswith("/health")


def _http_path_suppressed(method: str, path: str) -> bool:
    p = (path or "").split("?", 1)[0].rstrip("/") or "/"
    if p in _HTTP_SUPPRESS_PATHS:
        return True
    for prefix in _HTTP_SUPPRESS_PREFIXES:
        if p == prefix or p.startswith(prefix + "/"):
            if method.upper() in ("GET", "PATCH", "HEAD", "OPTIONS", "POST"):
                return True
    return False


def should_log_http(
    method: str,
    path: str,
    status: int,
    *,
    duration_ms: float | None = None,
) -> bool:
    if status >= 400:
        return True
    if is_compact_mode():
        return False
    if duration_ms is not None and duration_ms >= _SLOW_MS["backend_request"]:
        return True
    if is_trace_mode():
        return True
    if _http_path_suppressed(method, path):
        return False
    return True


def log_compact_line(line: str) -> None:
    """Write one readable line to activity_compact.log only (never activity.log)."""
    if _should_write_compact_file() and line.strip():
        get_compact_logger().info(line.strip())


def log_compact(category: str, message: str) -> None:
    if category:
        log_compact_line(f"[{category}] {message}")
    else:
        log_compact_line(message)


def _dedupe_key(key: str, ttl_s: float) -> bool:
    """Return True if this key was seen recently (should skip)."""
    now = time.monotonic()
    with _LOCK:
        prev = _dedupe_cache.get(key)
        if prev is not None and (now - prev) < ttl_s:
            return True
        _dedupe_cache[key] = now
    return False


def log_deduped_compact(line: str, *, key: str, ttl_s: float | None = None) -> bool:
    """Log one compact line if not a duplicate. Returns True if logged."""
    ttl = ttl_s if ttl_s is not None else _dedupe_ttl_s
    if _dedupe_key(key, ttl):
        return False
    log_compact_line(line)
    return True


def log_http_line(
    component: str,
    method: str,
    path: str,
    status: int,
    *,
    duration_ms: float | None = None,
    correlation_id: str | None = None,
) -> None:
    if is_health_path(path):
        get_health_logger(component).info(f"[{component}] {method} {path} {status}")
        return

    if duration_ms is not None and duration_ms >= _SLOW_MS["backend_request"]:
        log_slow("backend_request", duration_ms, detail=f"{method} {path}", correlation_id=correlation_id)

    if not should_log_http(method, path, status, duration_ms=duration_ms):
        if is_debug_mode() or is_trace_mode():
            get_activity_logger("http.trace").debug(f"[{CAT_HTTP}] {method} {path} {status}")
        return

    p = (path or "").split("?", 1)[0].rstrip("/") or "/"
    dedupe_key = f"http:{component}:{method}:{p}:{status}"
    if p in ("/api/transport/map", "/wake", "/mode") and method.upper() in ("POST", "GET"):
        if _dedupe_key(dedupe_key, 1.5):
            return

    suffix_parts: list[str] = []
    if duration_ms is not None:
        suffix_parts.append(f"duration_ms={duration_ms:.0f}")
    if correlation_id:
        suffix_parts.append(f"correlation_id={correlation_id}")
    suffix = f" | {' '.join(suffix_parts)}" if suffix_parts else ""
    get_activity_logger(component).info(f"[{CAT_HTTP}] [{component}] {method} {path} {status}{suffix}")


def log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    import json

    payload = {"event": event, **fields}
    try:
        full = json.dumps(payload, ensure_ascii=True, default=str, sort_keys=True)
    except Exception as exc:
        logger.info('{"event":"log_event_failed","error":%r,"original_event":%r}', str(exc), event)
        return
    if is_compact_mode():
        if event == "render_mapbox_payload_built":
            log_map_render_summary(
                mode=str(fields.get("mode", "")),
                graph_nodes=int(fields.get("graph_nodes") or 0),
                graph_edges=int(fields.get("graph_edges") or 0),
                path_segments=int(fields.get("path_feature_count") or 0),
                poi_loaded=bool(fields.get("poi_lookup_loaded")),
                render_ms=fields.get("render_ms"),
                correlation_id=fields.get("correlation_id"),
            )
        logger.debug(full)
        return
    logger.info(full)


def log_slow(
    operation: str,
    duration_ms: float,
    *,
    detail: str = "",
    correlation_id: str | None = None,
) -> None:
    threshold = _SLOW_MS.get(operation, _SLOW_MS["backend_request"])
    if duration_ms < threshold:
        return
    cid = f" correlation_id={correlation_id}" if correlation_id else ""
    cmd = detail or operation
    line = f"[Slow] {operation} took {duration_ms:.0f}ms for {cmd}{cid}"
    log_deduped_compact(line, key=f"slow:{operation}:{cmd}", ttl_s=5.0)
    if not is_compact_mode():
        get_activity_logger("errors").warning(line)


def log_startup(message: str) -> None:
    log_deduped_compact(f"[Startup] {message}", key=f"startup:{message}", ttl_s=60.0)
    if not is_compact_mode():
        get_activity_logger("startup").info(f"[Startup] {message}")


def get_turn_correlation_id(turn_id: int | None) -> str | None:
    if turn_id is None:
        return None
    with _LOCK:
        ctx = _turn_ctx.get(str(turn_id))
        if ctx:
            return ctx.get("correlation_id")
    return None


def begin_turn(turn_id: int, user_text: str, *, correlation_id: str | None = None) -> str:
    cid = ensure_correlation_id(correlation_id)
    preview = user_text.strip().replace("\n", " ")[:160]
    with _LOCK:
        _turn_ctx[str(turn_id)] = {
            "turn_id": turn_id,
            "user": preview,
            "correlation_id": cid,
            "planner": None,
            "tool": None,
            "map": None,
            "final": None,
            "final_source": None,
        }
    log_compact_line(f'[Turn {turn_id}] user="{preview}" correlation_id={cid}')
    return cid


def log_turn_planner(
    *,
    turn_id: int | None,
    path: str,
    tool: str | None,
    model: str,
    latency_ms: float,
    validation_ok: bool,
    args_summary: str = "",
    correlation_id: str | None = None,
) -> None:
    cid = correlation_id or get_turn_correlation_id(turn_id) or ""
    args_short = _short_args(args_summary)
    line = (
        f"[Planner] path={path} tool={tool or 'none'} model={model} "
        f"latency={latency_ms:.0f}ms validation={str(validation_ok).lower()}"
    )
    if args_short:
        line += f" args={args_short}"
    if cid:
        line += f" correlation_id={cid}"
    log_deduped_compact(line, key=f"planner:{turn_id}:{tool}:{path}", ttl_s=30.0)
    log_slow("planner", latency_ms, detail=path, correlation_id=cid or None)


def log_turn_tool(
    *,
    turn_id: int | None,
    tool_name: str,
    ok: bool,
    summary: str = "",
    args_summary: str = "",
    latency_ms: float | None = None,
    correlation_id: str | None = None,
    sources: list[str] | None = None,
) -> None:
    cid = correlation_id or get_turn_correlation_id(turn_id) or ""
    line = f"[Tool] {tool_name} ok={str(ok).lower()}"
    if args_summary:
        line += f" {args_summary}"
    if summary:
        line += f' summary="{summary[:200]}"'
    if sources:
        links = [str(s).strip() for s in sources if str(s).strip()]
        if links:
            line += ' sources="' + " | ".join(links[:8]) + '"'
    if cid:
        line += f" correlation_id={cid}"
    log_deduped_compact(line, key=f"tool:{turn_id}:{tool_name}", ttl_s=30.0)
    if latency_ms is not None:
        log_slow("tool_execution", latency_ms, detail=tool_name, correlation_id=cid or None)


def log_turn_final(
    *,
    turn_id: int | None,
    text: str,
    correlation_id: str | None = None,
    source: str = "assistant",
) -> None:
    preview = (text or "").strip().replace("\n", " ")[:300]
    if not preview:
        return
    cid = correlation_id or get_turn_correlation_id(turn_id) or ""
    tid = str(turn_id or "")
    with _LOCK:
        ctx = _turn_ctx.get(tid)
        if ctx:
            prev = ctx.get("final")
            prev_src = ctx.get("final_source")
            if prev_src == "assistant" and source == "planner":
                return
            if prev and source == "assistant" and prev_src == "assistant":
                if preview == prev or len(preview) <= len(prev):
                    return
            ctx["final"] = preview
            ctx["final_source"] = source
    line = f"[Final] {preview}"
    if cid:
        line += f" correlation_id={cid}"
    log_deduped_compact(line, key=f"final:{turn_id}:{source}", ttl_s=30.0)


def log_map_render_summary(
    *,
    mode: str,
    graph_nodes: int,
    graph_edges: int,
    path_segments: int,
    poi_loaded: bool,
    render_ms: float | None = None,
    correlation_id: str | None = None,
) -> None:
    line = (
        f"[MapRender] mode={mode} nodes={graph_nodes} edges={graph_edges} "
        f"path_segments={path_segments} poi_loaded={str(poi_loaded).lower()}"
    )
    if render_ms is not None:
        line += f" render_ms={render_ms:.0f}"
    if correlation_id:
        line += f" correlation_id={correlation_id}"
    log_deduped_compact(line, key=f"map:{mode}:{graph_nodes}:{path_segments}", ttl_s=10.0)
    if render_ms is not None:
        log_slow("map_render", render_ms, detail=f"mode={mode}", correlation_id=correlation_id)


def _short_args(args_summary: str) -> str:
    raw = (args_summary or "").strip()
    if not raw:
        return ""
    if len(raw) <= 120:
        return raw
    return raw[:117] + "..."


def effective_turn_log_level(level: str, message: str) -> str:
    if is_trace_mode():
        return level
    if level != "info":
        return level
    if is_debug_mode():
        return level
    if "[PlannerLive]" in message:
        return "info"
    if _COMPACT_DEMOTE_PATTERNS.search(message):
        return "debug"
    if "Text delta:" in message or "Event: response." in message:
        return "debug"
    return "debug" if is_compact_mode() else level


def should_log_realtime_event(event_type: str) -> bool:
    if is_trace_mode():
        return True
    if event_type in _TRACE_RT_EVENT_TYPES:
        return is_debug_mode()
    if event_type.startswith("response.") and is_debug_mode():
        return True
    return False


def configure_product_shell_logging() -> None:
    if os.getenv("CSPE_LOG_RESET") == "1" and not _RESET_DONE:
        reset_project_logs()
    apply_log_mode()
    if not is_compact_mode():
        log_startup(f"Product shell logging mode={get_log_mode()}")


def configure_uvicorn_loggers() -> None:
    _ensure_roots()
    for name in ("uvicorn", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True
    logging.getLogger("uvicorn.access").handlers.clear()
    logging.getLogger("uvicorn.access").propagate = False
