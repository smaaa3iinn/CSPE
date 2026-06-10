"""IDFM Navitia service hours / departures for station topic=hours (no SerpAPI)."""

from __future__ import annotations

import re
from typing import Any

from backend.product_shell.services.idfm_client import IdfmApiFailure, IdfmNavitiaClient

_NAVITIA_DT = re.compile(r"^(\d{8})T(\d{2})(\d{2})")


def format_navitia_time(raw: str | None) -> str:
    if not raw:
        return ""
    text = str(raw).strip()
    match = _NAVITIA_DT.match(text)
    if match:
        return f"{match.group(2)}:{match.group(3)}"
    return text


def _dt_value(raw: str | None) -> str | None:
    if not raw:
        return None
    text = str(raw).strip()
    return text if _NAVITIA_DT.match(text) else None


def _extract_datetime(cell: Any) -> str | None:
    if isinstance(cell, dict):
        return _dt_value(cell.get("date_time") or cell.get("base_date_time"))
    if isinstance(cell, str):
        return _dt_value(cell)
    return None


def _line_mode_name(line: dict[str, Any]) -> str:
    commercial = line.get("commercial_mode")
    if isinstance(commercial, dict):
        return str(commercial.get("name") or "").strip()
    return ""


def official_timetable_link(*, line_code: str, commercial_mode: str) -> str | None:
    code = (line_code or "").strip()
    mode = (commercial_mode or "").strip().lower()
    if mode == "metro" and code.isdigit():
        return f"https://www.ratp.fr/en/horaires?line=metro-{code}"
    if mode in ("rer", "transilien"):
        return "https://www.transilien.com/en/page-globals/Horaires"
    if mode == "bus" and code:
        slug = re.sub(r"\s+", "", code)
        return f"https://www.ratp.fr/en/horaires?line=bus-{slug}"
    if mode == "tram" and code:
        slug = re.sub(r"\s+", "", code)
        return f"https://www.ratp.fr/en/horaires?line=tram-{slug}"
    return "https://www.iledefrance-mobilites.fr/en/deplacer/temps-reel"


def _parse_departure(dep: dict[str, Any]) -> dict[str, Any] | None:
    display = dep.get("display_informations") if isinstance(dep.get("display_informations"), dict) else {}
    stop_dt = dep.get("stop_date_time") if isinstance(dep.get("stop_date_time"), dict) else {}
    when = _extract_datetime(stop_dt.get("departure_date_time") or stop_dt.get("base_departure_date_time"))
    if not when:
        return None
    code = str(display.get("code") or display.get("label") or "").strip()
    direction = str(display.get("direction") or display.get("headsign") or "").strip()
    mode = str(display.get("commercial_mode") or display.get("network") or "").strip()
    return {
        "line": code,
        "direction": direction,
        "mode": mode,
        "departure_time": format_navitia_time(when),
        "raw_departure": when,
    }


def _parse_stop_schedule(row: dict[str, Any]) -> dict[str, Any] | None:
    display = row.get("display_informations") if isinstance(row.get("display_informations"), dict) else {}
    first = _extract_datetime(row.get("first_datetime"))
    last = _extract_datetime(row.get("last_datetime"))
    if not first and not last:
        return None
    code = str(display.get("code") or display.get("label") or "").strip()
    direction = str(display.get("direction") or "").strip()
    mode = str(display.get("commercial_mode") or "").strip()
    return {
        "line": code,
        "direction": direction,
        "mode": mode,
        "first_service": format_navitia_time(first) if first else None,
        "last_service": format_navitia_time(last) if last else None,
        "raw_first": first,
        "raw_last": last,
    }


def fetch_station_service_hours(
    client: IdfmNavitiaClient,
    *,
    stop_area_id: str,
    stop_point_id: str | None,
    lines: list[dict[str, Any]],
) -> dict[str, Any]:
    """Navitia departures + theoretical stop schedules for a resolved stop area."""
    next_departures: list[dict[str, Any]] = []
    line_windows: list[dict[str, Any]] = []
    errors: list[str] = []

    try:
        dep_rows = client.fetch_departures(stop_area_id, count=8)
        seen_dep: set[str] = set()
        for dep in dep_rows:
            parsed = _parse_departure(dep)
            if not parsed:
                continue
            key = f"{parsed['line']}|{parsed['direction']}|{parsed['raw_departure']}"
            if key in seen_dep:
                continue
            seen_dep.add(key)
            next_departures.append(parsed)
            if len(next_departures) >= 8:
                break
    except IdfmApiFailure as exc:
        errors.append(f"departures: {exc.detail}")

    if stop_point_id and len(next_departures) < 4:
        try:
            point_deps = client.fetch_departures(stop_point_id, count=6)
            seen_dep = {f"{d['line']}|{d['direction']}|{d['raw_departure']}" for d in next_departures}
            for dep in point_deps:
                parsed = _parse_departure(dep)
                if not parsed:
                    continue
                key = f"{parsed['line']}|{parsed['direction']}|{parsed['raw_departure']}"
                if key in seen_dep:
                    continue
                seen_dep.add(key)
                next_departures.append(parsed)
                if len(next_departures) >= 8:
                    break
        except IdfmApiFailure as exc:
            errors.append(f"stop_point_departures: {exc.detail}")

    try:
        schedule_rows = client.fetch_stop_schedules(stop_area_id, count=24)
        seen_windows: set[str] = set()
        for row in schedule_rows:
            parsed = _parse_stop_schedule(row)
            if not parsed:
                continue
            key = f"{parsed['line']}|{parsed['direction']}"
            if key in seen_windows:
                continue
            seen_windows.add(key)
            line_windows.append(parsed)
            if len(line_windows) >= 12:
                break
    except IdfmApiFailure as exc:
        errors.append(f"stop_schedules: {exc.detail}")

    timetable_links: list[dict[str, str]] = []
    seen_links: set[str] = set()
    for line in lines[:12]:
        code = str(line.get("name") or "").strip()
        mode = _line_mode_name(line)
        url = official_timetable_link(line_code=code, commercial_mode=mode)
        if not url or url in seen_links:
            continue
        seen_links.add(url)
        label = f"{code} ({mode})" if mode else code
        timetable_links.append({"line": label, "url": url})

    return {
        "station_opening_hours": {
            "available": False,
            "note": (
                "IDFM does not publish station building opening hours; "
                "below are public transport service times at this stop."
            ),
        },
        "service_operating_hours": {
            "source": "idfm_navitia",
            "next_departures": next_departures,
            "line_service_windows": line_windows,
            "timetable_links": timetable_links,
            "errors": errors,
        },
    }


def summarize_service_hours(service_hours: dict[str, Any], *, station_label: str) -> list[str]:
    """Human-readable lines for idfm_summary (LLM-facing)."""
    lines_out: list[str] = [
        "Station building opening hours: not available from IDFM (transport service times below).",
        f"Public transport service at {station_label} (IDFM schedule / next departures):",
    ]
    svc = service_hours.get("service_operating_hours")
    if not isinstance(svc, dict):
        lines_out.append("- No schedule data returned.")
        return lines_out

    for err in svc.get("errors") or []:
        if err:
            lines_out.append(f"- Schedule fetch note: {err}")

    windows = svc.get("line_service_windows") or []
    if windows:
        lines_out.append("Theoretical first/last service today (by line/direction):")
        for row in windows[:8]:
            if not isinstance(row, dict):
                continue
            label = row.get("line") or "?"
            direction = row.get("direction") or ""
            mode = row.get("mode") or ""
            first = row.get("first_service")
            last = row.get("last_service")
            bits = [str(label)]
            if mode:
                bits.append(f"({mode})")
            if direction:
                bits.append(f"→ {direction}")
            window = []
            if first:
                window.append(f"from {first}")
            if last:
                window.append(f"until {last}")
            if window:
                lines_out.append(f"- {' '.join(bits)}: {' '.join(window)}")
            else:
                lines_out.append(f"- {' '.join(bits)}")

    deps = svc.get("next_departures") or []
    if deps:
        lines_out.append("Next scheduled departures:")
        for row in deps[:6]:
            if not isinstance(row, dict):
                continue
            label = row.get("line") or "?"
            direction = row.get("direction") or ""
            when = row.get("departure_time") or "?"
            mode = row.get("mode") or ""
            tail = f"{label} to {direction} at {when}" if direction else f"{label} at {when}"
            if mode:
                tail = f"{mode} {tail}"
            lines_out.append(f"- {tail}")

    links = svc.get("timetable_links") or []
    if links:
        lines_out.append("Official line timetables:")
        for link in links[:6]:
            if not isinstance(link, dict):
                continue
            lines_out.append(f"- {link.get('line') or 'Line'}: {link.get('url')}")

    if len(lines_out) <= 2 and not windows and not deps:
        lines_out.append(
            "- No structured timetable returned; use official line timetable links if listed above."
        )
    return lines_out
