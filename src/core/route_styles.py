"""Shared route/line colors and edge styling for maps and route summaries."""

from __future__ import annotations

from typing import Any

MODE_COLORS = {
    "bus": "#2563eb",
    "tram": "#db2777",
    "metro": "#7c3aed",
    "rail": "#059669",
    "other": "#64748b",
    "multi": "#94a3b8",
    "transfer": "#f59e0b",
    "path": "#ef4444",
    "selected": "#f97316",
}

# Bright neon green for 3D/VR route paths (distinct from 2D map orange highlight).
GRAPH3D_ROUTE_COLOR = "#39ff14"

METRO_LINE_COLORS = {
    "1": "#FECD02",
    "2": "#0E75BC",
    "3": "#A09E44",
    "3B": "#87D2DF",
    "4": "#BA4A9C",
    "5": "#F68F4A",
    "6": "#77C696",
    "7": "#F59EB2",
    "7B": "#77C696",
    "8": "#C4A2CB",
    "9": "#CDC82A",
    "10": "#E0B03A",
    "11": "#8D6539",
    "12": "#008B59",
    "13": "#87D2DF",
    "14": "#642D91",
    "15": "#B60C4A",
    "16": "#F59EB2",
    "17": "#CDC82A",
    "18": "#00B297",
}

RAIL_LINE_COLORS = {
    "A": "#F75C4C",
    "B": "#B2D6F2",
    "C": "#986E05",
    "D": "#77AF98",
    "E": "#D582BC",
    "H": "#A38869",
    "J": "#B8B705",
    "K": "#A6A560",
    "L": "#87627F",
    "N": "#9EDCD8",
    "P": "#D77D4F",
    "R": "#D66D98",
    "U": "#BB446B",
    "V": "#6D6F03",
}

TRAM_LINE_COLORS = {
    "T1": "#709FDD",
    "T2": "#C76FAB",
    "T3A": "#FCA371",
    "T3B": "#70A790",
    "T4": "#E9C373",
    "T5": "#A470B4",
    "T6": "#F8706F",
    "T7": "#AB9880",
    "T8": "#ACAC71",
    "T9": "#92C0E8",
    "T10": "#B3B27A",
    "T11": "#FCB081",
    "T12": "#CF899F",
    "T13": "#BEB29E",
    "T14": "#88D2CA",
}


def _metro_line_key(value: Any) -> str | None:
    text = str(value or "").strip().upper().replace(" ", "")
    if not text:
        return None
    if text in {"3B", "3BIS"}:
        return "3B"
    if text in {"7B", "7BIS"}:
        return "7B"
    return text


def _rail_line_key(short_name: Any, long_name: Any) -> str | None:
    for value in (short_name, long_name):
        text = str(value or "").strip().upper().replace(" ", "")
        if not text:
            continue
        if text in RAIL_LINE_COLORS:
            return text
        if text.startswith("RER") and len(text) > 3:
            candidate = text[3:]
            if candidate in RAIL_LINE_COLORS:
                return candidate
    return None


def _tram_line_key(short_name: Any, long_name: Any) -> str | None:
    for value in (short_name, long_name):
        text = str(value or "").strip().upper().replace(" ", "")
        if not text:
            continue
        if text in TRAM_LINE_COLORS:
            return text
        if text.startswith("TRAM"):
            candidate = text[4:]
            if candidate in TRAM_LINE_COLORS:
                return candidate
    return None


def _split_modes(raw: Any) -> list[str]:
    text = str(raw or "").strip()
    if not text:
        return []
    return [part for part in text.split("|") if part and part != "transfer"]


def _normalize_route_refs(data: dict[str, Any]) -> list[dict[str, str]]:
    route_refs = data.get("route_refs") or []
    normalized: list[dict[str, str]] = []
    for ref in route_refs:
        if not isinstance(ref, dict):
            continue
        normalized.append(
            {
                "mode": str(ref.get("mode", "")),
                "route_id": str(ref.get("route_id", "")),
                "route_short_name": str(ref.get("route_short_name", "")),
                "route_long_name": str(ref.get("route_long_name", "")),
                "route_label": str(ref.get("route_label", "")),
            }
        )
    return normalized


def _pick_route_ref(route_refs: list[dict[str, str]], current_mode: str) -> dict[str, str] | None:
    if not route_refs:
        return None
    if current_mode and current_mode not in ("all", "all_mb"):
        for ref in route_refs:
            if ref.get("mode") == current_mode:
                return ref
    return route_refs[0]


def color_for_mode_line(mode: str, *, short_name: str = "", long_name: str = "", route_label: str = "") -> str:
    mode = str(mode or "other")
    if mode == "metro":
        for value in (short_name, route_label, long_name):
            key = _metro_line_key(value)
            if key and key in METRO_LINE_COLORS:
                return METRO_LINE_COLORS[key]
        return MODE_COLORS["metro"]
    if mode == "rail":
        key = _rail_line_key(short_name, long_name) or _rail_line_key(route_label, route_label)
        if key:
            return RAIL_LINE_COLORS.get(key, MODE_COLORS["rail"])
        return MODE_COLORS["rail"]
    if mode == "tram":
        key = _tram_line_key(short_name, long_name) or _tram_line_key(route_label, route_label)
        if key:
            return TRAM_LINE_COLORS.get(key, MODE_COLORS["tram"])
        return MODE_COLORS["tram"]
    return MODE_COLORS.get(mode, MODE_COLORS["other"])


def path_edge_style(data: dict[str, Any], current_mode: str = "all") -> dict[str, Any]:
    if str(data.get("edge_kind") or "") == "transfer":
        return {
            "edge_kind": "transfer",
            "mode": "transfer",
            "line_label": "Walk transfer",
            "line_key": None,
            "color": MODE_COLORS["transfer"],
        }

    route_refs = _normalize_route_refs(data)
    ref = _pick_route_ref(route_refs, current_mode)
    if ref:
        mode = str(ref.get("mode") or data.get("mode") or "other")
        line_label = str(ref.get("route_label") or "").strip()
        if not line_label:
            short_name = str(ref.get("route_short_name") or "").strip()
            long_name = str(ref.get("route_long_name") or "").strip()
            if mode == "metro" and short_name:
                line_label = f"Metro Line {short_name}"
            elif mode == "rail" and short_name:
                line_label = f"RER {short_name.upper()}" if len(short_name) == 1 else f"Rail {short_name}"
            elif mode == "tram" and short_name:
                line_label = f"Tram {short_name}"
            elif mode == "bus" and short_name:
                line_label = f"Bus {short_name}"
            else:
                line_label = long_name or mode.title()
        line_key = None
        if mode == "metro":
            line_key = _metro_line_key(ref.get("route_short_name") or ref.get("route_label"))
        elif mode == "rail":
            line_key = _rail_line_key(ref.get("route_short_name"), ref.get("route_long_name"))
        elif mode == "tram":
            line_key = _tram_line_key(ref.get("route_short_name"), ref.get("route_long_name"))
        color = color_for_mode_line(
            mode,
            short_name=str(ref.get("route_short_name") or ""),
            long_name=str(ref.get("route_long_name") or ""),
            route_label=line_label,
        )
        return {
            "edge_kind": "ride",
            "mode": mode,
            "line_label": line_label,
            "line_key": line_key,
            "color": color,
        }

    modes = _split_modes(data.get("modes") or data.get("mode"))
    mode = modes[0] if len(modes) == 1 else (str(data.get("mode") or "other") if modes else "other")
    if len(modes) > 1:
        mode = "multi"
    line_label = str(data.get("mode") or mode).title()
    if mode == "multi":
        line_label = " / ".join(m.title() for m in modes) if modes else "Multi"
    return {
        "edge_kind": "ride",
        "mode": mode,
        "line_label": line_label,
        "line_key": None,
        "color": MODE_COLORS.get(mode, MODE_COLORS["other"]),
    }


def ride_leg_key(style: dict[str, Any]) -> tuple[str, str, str | None]:
    return (
        str(style.get("edge_kind") or "ride"),
        str(style.get("mode") or ""),
        str(style.get("line_key") or style.get("line_label") or ""),
    )
