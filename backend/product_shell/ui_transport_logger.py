"""
Structured activity log lines for transport, Atlas shell bridge, and agent events.

All output goes to <repo>/logs/activity.log (see src.core.project_logs).
"""

from __future__ import annotations

import json
from typing import Any

from src.core.project_logs import get_activity_logger


def _logger():
    return get_activity_logger("ui.transport")


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
    _logger().info("[Atlas] transport_intent_enqueued payload=%s", _dumps(payload))


def log_atlas_transport_action_enqueued(payload: dict[str, Any]) -> None:
    _logger().info("[Atlas] transport_action_enqueued payload=%s", _dumps(payload))


def log_atlas_transport_client_event(event: str, payload: dict[str, Any]) -> None:
    _logger().info("[Atlas] transport_ui %s data=%s", event, _dumps(payload))

