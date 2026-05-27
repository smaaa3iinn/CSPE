"""
Structured activity log lines for transport, Atlas shell bridge, and agent events.

Compact mode: summaries go to logs/activity_compact.log only.
Debug/trace: full JSON payloads in logs/activity.log.
"""

from __future__ import annotations

import json
from typing import Any

from src.core.project_logs import (
    get_activity_logger,
    is_compact_mode,
    log_compact_line,
    log_deduped_compact,
    log_event,
)


def _logger():
    return get_activity_logger("ui.transport")


def _dumps(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=True, default=str)
    except Exception:
        return repr(obj)


def _action_label(payload: dict[str, Any]) -> str:
    spec = payload.get("spec") if isinstance(payload.get("spec"), dict) else {}
    run = spec.get("run") or payload.get("action") or payload.get("kind") or "unknown"
    if run == "route" or spec.get("from_query") or spec.get("to_query"):
        fr = spec.get("from_query") or spec.get("from") or "?"
        to = spec.get("to_query") or spec.get("to") or "?"
        return f"route {fr}->{to}"
    if spec.get("graph_mode"):
        return f"graph_mode={spec['graph_mode']}"
    if spec.get("mode"):
        return f"mode={spec['mode']}"
    return str(run)


def log_ui_search_stops(
    *,
    q: str,
    limit: int,
    mode: str,
    use_lcc: bool,
    station_first: bool,
    matches: list[dict[str, Any]],
) -> None:
    count = len(matches or [])
    if is_compact_mode():
        log_deduped_compact(
            f"[Transport] search_stops q={q!r} mode={mode} count={count}",
            key=f"search:{q}:{mode}",
            ttl_s=15.0,
        )
        return
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
    log_event(
        _logger(),
        "ui_search_stops",
        query=q,
        limit=limit,
        mode=mode,
        use_lcc=use_lcc,
        station_first=station_first,
        count=count,
        matches_preview=sample,
    )


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
    ok = bool(response.get("ok"))
    path = response.get("path")
    st_path = response.get("station_path")
    path_len = len(path) if isinstance(path, list) else 0
    st_len = len(st_path) if isinstance(st_path, list) else 0
    names = response.get("station_names") or []
    from_name = names[0] if isinstance(names, list) and names else from_station_id or from_stop_id or "?"
    to_name = names[-1] if isinstance(names, list) and len(names) > 1 else to_station_id or to_stop_id or "?"
    transfers = max(0, (st_len or path_len) - 1) if (st_len or path_len) else 0
    if is_compact_mode():
        log_deduped_compact(
            f"[Transport] route ok={str(ok).lower()} mode={mode} from={from_name} to={to_name} transfers={transfers}",
            key=f"route:{from_name}:{to_name}:{mode}",
            ttl_s=30.0,
        )
        if not ok:
            err = response.get("error")
            msg = (err or {}).get("message") if isinstance(err, dict) else err
            log_compact_line(f"[Transport] route failed: {msg}")
        return
    args: dict[str, Any] = {"mode": mode, "use_lcc": use_lcc, "routing": routing}
    if routing == "stop":
        args["from_stop_id"] = from_stop_id
        args["to_stop_id"] = to_stop_id
    else:
        args["from_station_id"] = from_station_id
        args["to_station_id"] = to_station_id
    log_event(
        _logger(),
        "ui_route",
        args=args,
        ok=ok,
        path_len=path_len,
        station_path_len=st_len,
        station_names=names,
        result=response.get("result") or response.get("detail"),
        error=response.get("error"),
    )


_NOISY_CLIENT_EVENTS = frozenset(
    {
        "atlas_transport_trigger",
        "ui_route_payload",
        "from_resolved",
        "to_resolved",
        "map_request",
        "context_sync",
        "agent.shell.commands_applied",
        "atlas_transport_action",
    }
)

_EXPLORATION_CLIENT_EVENTS = frozenset(
    {
        "exploration_view_applied",
        "exploration_map_refresh",
        "exploration_map_trigger",
    }
)


def _exploration_center_label(payload: dict[str, Any]) -> str:
    center = payload.get("center") if isinstance(payload.get("center"), dict) else {}
    return str(
        center.get("label")
        or center.get("station_name")
        or center.get("stop_name")
        or payload.get("query")
        or "?"
    ).strip()


def log_exploration_api_result(result: dict[str, Any], *, sync_ui: bool, cmds: int = 0) -> None:
    ok = bool(result.get("ok"))
    center = _exploration_center_label(result)
    counts = result.get("counts") if isinstance(result.get("counts"), dict) else {}
    stops = int(counts.get("stops", len(result.get("nearby_stops") or [])))
    pois = int(counts.get("pois", len(result.get("nearby_pois") or result.get("pois") or [])))
    radius = int(result.get("radius_m") or 0)
    err = result.get("error") or result.get("message")
    if ok:
        log_compact_line(
            f"[Exploration] api ok center={center!r} stops={stops} pois={pois} "
            f"radius={radius}m sync_ui={str(sync_ui).lower()} shell_cmds={cmds}"
        )
    else:
        log_compact_line(
            f"[Exploration] api failed center={center!r} err={err!r} sync_ui={str(sync_ui).lower()}"
        )
    if is_compact_mode():
        return
    log_event(
        _logger(),
        "exploration_api_result",
        ok=ok,
        center=center,
        stops=stops,
        pois=pois,
        radius_m=radius,
        sync_ui=sync_ui,
        shell_cmds=cmds,
        summary=result.get("summary"),
        error=err,
    )


def log_exploration_shell_enqueue(cmd: dict[str, Any]) -> None:
    if cmd.get("kind") != "transport_exploration_view":
        return
    stops = len(cmd.get("nearby_stops") or [])
    pois = len(cmd.get("nearby_pois") or [])
    radius = cmd.get("radius_m")
    center = _exploration_center_label(cmd)
    log_compact_line(
        f"[Exploration] shell enqueue view center={center!r} stops={stops} pois={pois} radius={radius}m"
    )
    if is_compact_mode():
        return
    log_event(
        _logger(),
        "exploration_shell_enqueue",
        kind=cmd.get("kind"),
        center=center,
        stops=stops,
        pois=pois,
        radius_m=radius,
        summary=cmd.get("summary"),
    )


def log_exploration_map_render(
    *,
    stop_count: int,
    poi_count: int,
    radius_m: int | float | None,
    html_bytes: int,
    selected_station_id: str | None = None,
    selected_stop_id: str | None = None,
    mode: str | None = None,
    stop_geo_count: int | None = None,
    poi_geo_count: int | None = None,
    center_ok: bool | None = None,
    overlay_only: bool = False,
) -> None:
    geo_bits: list[str] = []
    if stop_geo_count is not None:
        geo_bits.append(f"stop_geo={stop_geo_count}")
    if poi_geo_count is not None:
        geo_bits.append(f"poi_geo={poi_geo_count}")
    if center_ok is not None:
        geo_bits.append(f"center_ok={str(center_ok).lower()}")
    geo_suffix = f" {' '.join(geo_bits)}" if geo_bits else ""
    kind = "overlay_patch" if overlay_only else "map_render"
    log_compact_line(
        f"[Exploration] {kind} mode={mode or '?'} stops={stop_count} pois={poi_count} "
        f"radius={radius_m}m html_bytes={html_bytes} "
        f"sel_station={selected_station_id or '-'} sel_stop={selected_stop_id or '-'}{geo_suffix}"
    )
    if is_compact_mode():
        return
    log_event(
        _logger(),
        "exploration_map_render",
        mode=mode,
        stop_count=stop_count,
        poi_count=poi_count,
        radius_m=radius_m,
        html_bytes=html_bytes,
        selected_station_id=selected_station_id,
        selected_stop_id=selected_stop_id,
    )


def _log_exploration_client_compact(event: str, payload: dict[str, Any]) -> None:
    phase = payload.get("phase")
    if event == "exploration_map_refresh":
        fetch_id = payload.get("fetch_id")
        if phase == "start":
            log_compact_line(
                f"[Exploration] ui map_refresh start id={fetch_id} "
                f"stops={payload.get('stop_count')} pois={payload.get('poi_count')} "
                f"radius={payload.get('radius_m')}m"
            )
        elif phase == "done":
            log_compact_line(
                f"[Exploration] ui map_refresh done id={fetch_id} "
                f"html_bytes={payload.get('html_bytes')} stale={payload.get('stale')}"
            )
        elif phase == "stale":
            log_compact_line(
                f"[Exploration] ui map_refresh stale id={fetch_id} current={payload.get('current_id')}"
            )
        elif phase == "error":
            log_compact_line(
                f"[Exploration] ui map_refresh error id={fetch_id} err={payload.get('error')!r}"
            )
        elif phase in ("overlay_done", "overlay_queued", "overlay_deliver", "fallback_full_reload", "full_reload_done"):
            log_compact_line(
                f"[Exploration] ui map_refresh {phase} id={fetch_id} "
                f"stops={payload.get('stop_count')} pois={payload.get('poi_count')} "
                f"bytes={payload.get('html_bytes', 0)}"
            )
    elif event == "exploration_view_applied":
        log_compact_line(
            f"[Exploration] ui view_applied stops={payload.get('stop_count')} "
            f"pois={payload.get('poi_count')} radius={payload.get('radius_m')}m "
            f"seq={payload.get('exploration_seq')}"
        )
    elif event == "exploration_map_trigger":
        log_compact_line(
            f"[Exploration] ui trigger {payload.get('trigger')} stops={payload.get('stops')} "
            f"pois={payload.get('pois')} station={payload.get('selected_station_id') or '-'}"
        )


def log_atlas_transport_intent_enqueued(payload: dict[str, Any]) -> None:
    if is_compact_mode():
        return
    log_event(_logger(), "transport_intent_enqueued", action=_action_label(payload), payload=payload)


def log_atlas_transport_action_enqueued(payload: dict[str, Any]) -> None:
    if is_compact_mode():
        return
    log_event(_logger(), "transport_action_enqueued", action=_action_label(payload), payload=payload)


def log_atlas_transport_client_event(event: str, payload: dict[str, Any]) -> None:
    if event in _EXPLORATION_CLIENT_EVENTS:
        _log_exploration_client_compact(event, payload)
        if not is_compact_mode():
            _logger().info("[Exploration] ui %s data=%s", event, _dumps(payload))
        return
    if is_compact_mode():
        if event in _NOISY_CLIENT_EVENTS:
            return
        return
    _logger().info("[Atlas] transport_ui %s data=%s", event, _dumps(payload))
