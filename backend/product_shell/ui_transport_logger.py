"""
Human-readable file log for React UI transport actions (search, route, map refresh).

Parallel to Atlas lines like [ToolCall] Executing: cspe_search_stops — but sourced from
FastAPI when the manual UI calls /api/transport/*.

Log path: <repo>/logs/product_ui_transport.log (rotating).
"""

from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

_CONFIGURED = False


def _logger() -> logging.Logger:
    global _CONFIGURED
    logger = logging.getLogger("cspe.ui.transport")
    if _CONFIGURED:
        return logger
    logger.setLevel(logging.INFO)
    logger.propagate = False
    root = Path(__file__).resolve().parents[2]
    log_dir = root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / "product_ui_transport.log"
    if not logger.handlers:
        h = RotatingFileHandler(path, maxBytes=2_000_000, backupCount=5, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
        logger.addHandler(h)
    _CONFIGURED = True
    return logger


def _dumps(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=True, default=str)
    except Exception:
        return repr(obj)


def log_ui_search_stops(
    *,
    q: str,
    limit: int,
    mode: str,
    use_lcc: bool,
    station_first: bool,
    matches: list[dict[str, Any]],
) -> None:
    """Log GET /api/transport/stops/search (UI autocomplete / search tab)."""
    sample: list[dict[str, Any]] = []
    for m in (matches or [])[:3]:
        if not isinstance(m, dict):
            continue
        sample.append(
            {
                "stop_id": m.get("stop_id"),
                "station_id": m.get("station_id"),
                "stop_name": m.get("stop_name"),
                "station_name": m.get("station_name"),
                "line": m.get("line"),
            }
        )
    msg = (
        "[UI] [ToolCall] transport.search_stops "
        f"args={_dumps({'query': q, 'limit': limit, 'mode': mode, 'use_lcc': use_lcc, 'station_first': station_first})} "
        f"result={_dumps({'ok': True, 'count': len(matches or []), 'matches_preview': sample})}"
    )
    _logger().info(msg)


def log_ui_route(
    *,
    mode: str,
    use_lcc: bool,
    routing: str,
    from_stop_id: str | None,
    to_stop_id: str | None,
    from_station_id: str | None,
    to_station_id: str | None,
    response: dict[str, Any],
) -> None:
    """Log POST /api/transport/route (Compute route in TransportMode)."""
    args: dict[str, Any] = {"mode": mode, "use_lcc": use_lcc, "routing": routing}
    if routing == "stop":
        args["from_stop_id"] = from_stop_id
        args["to_stop_id"] = to_stop_id
    else:
        args["from_station_id"] = from_station_id
        args["to_station_id"] = to_station_id

    path = response.get("path")
    st_path = response.get("station_path")
    summary = {
        "ok": response.get("ok"),
        "routing_scope": response.get("routing_scope"),
        "path_len": len(path) if isinstance(path, list) else None,
        "station_path_len": len(st_path) if isinstance(st_path, list) else None,
        "station_names": response.get("station_names"),
        "result": response.get("result"),
        "error": response.get("error"),
    }
    ok = bool(response.get("ok"))
    msg = (
        "[UI] [ToolCall] transport.route "
        f"args={_dumps(args)} "
        f"result={_dumps(summary)} "
        f"executed_ok={ok}"
    )
    log = _logger()
    log.info(msg)
    if not ok:
        log.warning(
            "[UI] [ToolCall] transport.route failed: %s",
            (response.get("error") or {}).get("message") if isinstance(response.get("error"), dict) else response.get("error"),
        )


def log_atlas_transport_intent_enqueued(payload: dict[str, Any]) -> None:
    """Log atlas_transport_intent command queued for the React shell (before UI applies it)."""
    msg = "[Atlas] transport_intent_enqueued " f"payload={_dumps(payload)}"
    _logger().info(msg)


def log_atlas_transport_action_enqueued(payload: dict[str, Any]) -> None:
    """Log atlas_transport_action (generalized transport UI control) queued for the React shell."""
    msg = "[Atlas] transport_action_enqueued " f"payload={_dumps(payload)}"
    _logger().info(msg)


def log_atlas_transport_client_event(event: str, payload: dict[str, Any]) -> None:
    """Log milestones from the browser (resolve, route payload, route result)."""
    msg = f"[Atlas] transport_ui {event} " f"data={_dumps(payload)}"
    _logger().info(msg)

