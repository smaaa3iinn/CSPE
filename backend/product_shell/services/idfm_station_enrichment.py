"""Enrich a locally resolved CSPE station with Île-de-France Mobilités open data."""

from __future__ import annotations

from typing import Any

from src.core.project_logs import log_compact_line

from backend.product_shell.services.idfm_client import (
    IdfmApiFailure,
    api_key,
    local_id_to_stop_point_id,
    navitia_client,
    primary_stop_point_id,
)
from backend.product_shell.services.idfm_referential import (
    describe_accessibility_level,
    referential_store,
)
from backend.product_shell.services.idfm_service_hours import (
    fetch_station_service_hours,
    summarize_service_hours,
)


def _format_line_entry(line: dict[str, Any]) -> str:
    name = str(line.get("name") or "").strip()
    mode = ""
    commercial = line.get("commercial_mode")
    if isinstance(commercial, dict):
        mode = str(commercial.get("name") or "").strip()
    if mode and name:
        return f"{name} ({mode})"
    return name or str(line.get("id") or "")


def _summarize_disruptions(disruptions: list[dict[str, Any]], *, station_label: str) -> list[str]:
    lines_out: list[str] = []
    seen: set[str] = set()
    for disruption in disruptions:
        messages = disruption.get("messages") if isinstance(disruption.get("messages"), list) else []
        text = ""
        for msg in messages:
            if isinstance(msg, dict):
                text = str(msg.get("text") or msg.get("message") or "").strip()
                if text:
                    break
        if not text:
            continue
        compact = " ".join(text.split())
        if compact in seen:
            continue
        seen.add(compact)
        if station_label.lower() in compact.lower():
            lines_out.append(compact)
        else:
            lines_out.append(compact)
        if len(lines_out) >= 4:
            break
    return lines_out


def enrich_local_station(
    local: dict[str, Any],
    *,
    topic: str = "about",
    includes_today: bool = False,
) -> dict[str, Any]:
    """
    Enrich a station already resolved in the CSPE graph with IDFM Navitia + referential data.
    Never performs open-ended place search — requires local stop/station ids.
    """
    if local.get("kind") != "station":
        return {"ok": False, "error": "not_a_station"}

    if not api_key():
        return {
            "ok": False,
            "error": "IDFM_API_KEY is not configured",
            "failure": {"reason": "missing_api_key", "detail": "IDFM_API_KEY environment variable is not set"},
        }

    stop_point_id = primary_stop_point_id(
        stop_id=str(local.get("stop_id") or "") or None,
        stop_ids=local.get("stop_ids") if isinstance(local.get("stop_ids"), list) else None,
        station_id=str(local.get("station_id") or "") or None,
    )
    if not stop_point_id:
        return {"ok": False, "error": "No IDFM stop id on the local station match"}

    client = navitia_client()
    try:
        stop_area_id = client.stop_area_id_for_stop_point(stop_point_id)
        if not stop_area_id:
            return {"ok": False, "error": f"No IDFM stop area for {stop_point_id}"}

        stop_area = client.fetch_stop_area(stop_area_id)
        lines = client.fetch_lines(stop_area_id)
        modes = client.fetch_physical_modes(stop_area_id)
        stop_points = client.fetch_stop_points(stop_area_id)
    except IdfmApiFailure as exc:
        return {
            "ok": False,
            "error": exc.detail,
            "failure": {"reason": exc.reason, "detail": exc.detail, "status_code": exc.status_code},
        }

    label = str(local.get("label") or stop_area.get("name") or "").strip()
    mode_names = [str(row.get("name") or "").strip() for row in modes if str(row.get("name") or "").strip()]
    line_labels = [_format_line_entry(row) for row in lines[:20]]
    line_ids = [str(row.get("id") or "").strip() for row in lines if str(row.get("id") or "").strip()]

    ref = referential_store()
    accessibility_rows: list[dict[str, Any]] = []
    seen_arrids: set[str] = set()
    for member in local.get("stop_ids") if isinstance(local.get("stop_ids"), list) else [stop_point_id]:
        row = ref.accessibility_for_local_stop(str(member))
        if row and row.get("arrid") not in seen_arrids:
            seen_arrids.add(str(row.get("arrid")))
            accessibility_rows.append(row)
    gare_row = ref.gare_accessibility_for_stop_point(stop_point_id)
    if gare_row:
        accessibility_rows.append(gare_row)

    disruptions: list[dict[str, Any]] = []
    if topic in ("disruptions", "accessibility") or includes_today:
        for line_id in line_ids[:8]:
            try:
                disruptions.extend(client.fetch_disruptions_for_line(line_id, count=3))
            except IdfmApiFailure:
                continue

    summary_lines = [f"Station: {label}"]
    if stop_area_id:
        summary_lines.append(f"IDFM stop area: {stop_area_id}")
    if mode_names:
        summary_lines.append(f"Modes: {', '.join(mode_names)}")
    if line_labels:
        summary_lines.append(f"Lines: {', '.join(line_labels)}")
    if accessibility_rows:
        summary_lines.append("Accessibility (IDFM referential):")
        for row in accessibility_rows[:6]:
            if row.get("source") == "accessibilite-en-gare":
                summary_lines.append(
                    f"- {row.get('stop_name') or label}: {row.get('level_name') or row.get('level_id')}"
                )
            else:
                summary_lines.append(
                    f"- {row.get('name') or label} ({row.get('type') or 'stop'}): "
                    f"{describe_accessibility_level(str(row.get('accessibility') or ''))}"
                )
    disruption_lines = _summarize_disruptions(disruptions, station_label=label)
    if disruption_lines:
        summary_lines.append("Current service alerts (IDFM):")
        summary_lines.extend(f"- {line}" for line in disruption_lines)

    service_hours: dict[str, Any] | None = None
    if topic == "hours":
        service_hours = fetch_station_service_hours(
            client,
            stop_area_id=stop_area_id,
            stop_point_id=stop_point_id,
            lines=lines,
        )
        summary_lines.extend(summarize_service_hours(service_hours, station_label=label))

    payload = {
        "stop_point_id": stop_point_id,
        "stop_area_id": stop_area_id,
        "stop_area": {
            "id": stop_area.get("id"),
            "name": stop_area.get("name"),
            "label": stop_area.get("label"),
            "coord": stop_area.get("coord"),
        },
        "physical_modes": mode_names,
        "lines": [
            {
                "id": row.get("id"),
                "name": row.get("name"),
                "commercial_mode": (row.get("commercial_mode") or {}).get("name")
                if isinstance(row.get("commercial_mode"), dict)
                else None,
            }
            for row in lines[:20]
        ],
        "stop_points_count": len(stop_points),
        "accessibility": accessibility_rows,
        "disruptions": disruption_lines,
    }
    if service_hours:
        payload["station_opening_hours"] = service_hours.get("station_opening_hours")
        payload["service_operating_hours"] = service_hours.get("service_operating_hours")

    log_compact_line(
        "[IDFM] enriched "
        f"station={label!r} stop_area={stop_area_id} lines={len(lines)} "
        f"access_rows={len(accessibility_rows)} disruptions={len(disruption_lines)} "
        f"service_hours={topic == 'hours'}"
    )

    return {
        "ok": True,
        "enrichment_source": "idfm",
        "idfm_summary": "\n".join(summary_lines),
        "idfm_data": payload,
        "web_search_query": None,
    }
