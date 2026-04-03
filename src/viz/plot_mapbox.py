from __future__ import annotations

import json
import math
from functools import lru_cache
from html import escape
from pathlib import Path
from typing import Any

import networkx as nx
try:
    import plotly.graph_objects as go
except ModuleNotFoundError:  # pragma: no cover - optional legacy dependency
    go = None

from src.core.debug_log import get_debug_logger, log_event
from src.core.poi_index import LocalPOILookup
from src.viz.paris_mask import build_paris_mask_payload

LOGGER = get_debug_logger("cspe.plot_mapbox")

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
POI_BADGE_STYLES = {
    "food": {"color": "#f97316", "icon_class": "fa-solid fa-utensils"},
    "shopping": {"color": "#2563eb", "icon_class": "fa-solid fa-basket-shopping"},
    "tourism": {"color": "#8b5cf6", "icon_class": "fa-solid fa-landmark"},
    "leisure": {"color": "#10b981", "icon_class": "fa-solid fa-spa"},
    "services": {"color": "#64748b", "icon_class": "fa-solid fa-building"},
    "transport": {"color": "#0ea5e9", "icon_class": "fa-solid fa-bicycle"},
}
FOOD_POI_TYPES = {
    "bar",
    "bbq",
    "biergarten",
    "cafe",
    "fast_food",
    "food_court",
    "ice_cream",
    "pub",
    "restaurant",
}
TRANSPORT_POI_TYPES = {
    "bicycle_parking",
    "bicycle_rental",
    "bicycle_repair_station",
    "boat_rental",
    "bus_station",
    "car_rental",
    "charging_station",
    "ferry_terminal",
    "fuel",
    "motorcycle_parking",
    "parking",
    "parking_entrance",
    "taxi",
}

DEFAULT_CENTER = {"lat": 48.8566, "lon": 2.3522}
DEFAULT_ZOOM = 8.3
DEFAULT_PITCH = 55
DEFAULT_BEARING = -18
GEOJSON_ROUTE_TYPE_TO_MODE = {
    "bus": "bus",
    "tram": "tram",
    "rail": "rail",
    "subway": "metro",
    "metro": "metro",
    "funicular": "other",
    "cableway": "other",
}


def _split_modes(raw_modes: str | None) -> list[str]:
    if raw_modes is None:
        return []
    return [part for part in str(raw_modes).split("|") if part]


def _normalize_label(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _normalize_route_id(value: Any) -> str:
    return str(value or "").strip().lower()


def _poi_family(category: Any, category_type: Any) -> str:
    category_text = str(category or "").strip().lower()
    type_text = str(category_type or "").strip().lower()

    if type_text in FOOD_POI_TYPES:
        return "food"
    if category_text == "shop":
        return "shopping"
    if category_text == "tourism":
        return "tourism"
    if category_text == "leisure":
        return "leisure"
    if type_text in TRANSPORT_POI_TYPES:
        return "transport"
    return "services"


def _poi_badge_style(category: Any, category_type: Any) -> dict[str, str]:
    family = _poi_family(category, category_type)
    style = POI_BADGE_STYLES[family]
    return {
        "family": family,
        "color": style["color"],
        "icon_class": style["icon_class"],
    }


def _text_color_for_background(hex_color: str) -> str:
    color = str(hex_color or "").strip().lstrip("#")
    if len(color) != 6:
        return "#ffffff"
    try:
        red = int(color[0:2], 16)
        green = int(color[2:4], 16)
        blue = int(color[4:6], 16)
    except ValueError:
        return "#ffffff"
    luminance = (0.299 * red) + (0.587 * green) + (0.114 * blue)
    return "#111827" if luminance >= 160 else "#ffffff"


def _friendly_route_labels(mode: str, short_name: str, long_name: str) -> set[str]:
    labels = {
        _normalize_label(short_name),
        _normalize_label(long_name),
    }
    short = str(short_name or "").strip()

    if mode == "metro" and short:
        labels.add(_normalize_label(f"Line {short}"))
    elif mode == "rail":
        if short and len(short) == 1 and short.isalpha():
            labels.add(_normalize_label(f"RER {short.upper()}"))
        if short:
            labels.add(_normalize_label(f"Rail {short}"))
    elif mode == "tram" and short:
        labels.add(_normalize_label(f"Tram {short}"))
    elif mode == "bus" and short:
        labels.add(_normalize_label(f"Bus {short}"))

    return {label for label in labels if label}


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


def _route_type_to_mode(route_type: Any) -> str:
    text = _normalize_label(route_type)
    if text in GEOJSON_ROUTE_TYPE_TO_MODE:
        return GEOJSON_ROUTE_TYPE_TO_MODE[text]
    try:
        code = int(route_type)
    except Exception:
        return "other"
    return {0: "tram", 1: "metro", 2: "rail", 3: "bus"}.get(code, "other")


def _valid_lat_lon(lat: Any, lon: Any) -> bool:
    try:
        lat = float(lat)
        lon = float(lon)
    except Exception:
        return False
    return -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0


def _geometry_segments(geometry: dict[str, Any]) -> list[list[tuple[float, float]]]:
    geometry_type = str(geometry.get("type") or "")
    coordinates = geometry.get("coordinates") or []
    if geometry_type == "LineString":
        raw_segments = [coordinates]
    elif geometry_type == "MultiLineString":
        raw_segments = coordinates
    else:
        raw_segments = []

    segments: list[list[tuple[float, float]]] = []
    for raw_segment in raw_segments:
        segment: list[tuple[float, float]] = []
        for point in raw_segment:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                continue
            lon, lat = point[0], point[1]
            if _valid_lat_lon(lat, lon):
                segment.append((float(lon), float(lat)))
        if len(segment) >= 2:
            segments.append(segment)
    return segments


@lru_cache(maxsize=4)
def load_line_geometries(geojson_path: str) -> dict[str, Any]:
    path = Path(geojson_path)
    features: list[dict[str, Any]] = []
    if path.is_dir():
        for geojson_file in sorted(path.glob("*.network.geojson")):
            data = json.loads(geojson_file.read_text(encoding="utf-8"))
            features.extend(data.get("features", []))
    else:
        data = json.loads(path.read_text(encoding="utf-8"))
        features.extend(data.get("features", []))

    by_mode: dict[str, list[dict[str, Any]]] = {mode: [] for mode in ("all", "bus", "tram", "metro", "rail", "other")}
    by_route_id: dict[str, dict[str, list[dict[str, Any]]]] = {
        mode: {} for mode in ("all", "bus", "tram", "metro", "rail", "other")
    }
    by_label: dict[str, dict[str, list[dict[str, Any]]]] = {
        mode: {} for mode in ("all", "bus", "tram", "metro", "rail", "other")
    }

    for feature in features:
        properties = feature.get("properties") or {}
        segments = _geometry_segments(feature.get("geometry") or {})
        if not segments:
            continue

        mode = str(properties.get("mode_detected") or "").strip().lower() or _route_type_to_mode(properties.get("route_type"))
        route_id = str(properties.get("route_id") or "").strip()
        short_name = str(properties.get("route_short_name") or "").strip()
        long_name = str(properties.get("route_long_name") or "").strip()
        labels = _friendly_route_labels(mode, short_name, long_name)

        item = {
            "mode": mode,
            "route_id": route_id,
            "route_short_name": short_name,
            "route_long_name": long_name,
            "segments": segments,
            "labels": labels,
        }
        for bucket_mode in ("all", mode):
            by_mode[bucket_mode].append(item)
            normalized_route_id = _normalize_route_id(route_id)
            if normalized_route_id:
                by_route_id[bucket_mode].setdefault(normalized_route_id, []).append(item)
            for label in labels:
                by_label[bucket_mode].setdefault(label, []).append(item)

    log_event(
        LOGGER,
        "line_geometries_loaded",
        source=str(path),
        feature_count=len(features),
        by_mode_counts={mode_name: len(items) for mode_name, items in by_mode.items()},
    )
    return {"by_mode": by_mode, "by_route_id": by_route_id, "by_label": by_label}


@lru_cache(maxsize=8)
def load_render_graph(json_path: str) -> dict[str, Any]:
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    nodes_by_id: dict[str, dict[str, Any]] = {}
    links_by_key: dict[tuple[str, str], dict[str, Any]] = {}

    for raw_node in data.get("nodes", []):
        if not isinstance(raw_node, dict):
            continue
        node_id = str(raw_node.get("id") or "").strip()
        if not node_id or node_id in nodes_by_id:
            continue
        lon = raw_node.get("x", raw_node.get("lon"))
        lat = raw_node.get("y", raw_node.get("lat"))
        if not _valid_lat_lon(lat, lon):
            continue
        nodes_by_id[node_id] = {
            "id": node_id,
            "name": str(raw_node.get("name") or raw_node.get("label") or node_id),
            "label": str(raw_node.get("label") or raw_node.get("name") or node_id),
            "mode": str(raw_node.get("mode") or "other"),
            "lon": float(raw_node.get("lon", lon)),
            "lat": float(raw_node.get("lat", lat)),
            "x": float(lon),
            "y": float(lat),
            "z": float(raw_node.get("z") or 0.0),
            "render_degree": 0,
        }

    for raw_link in data.get("links", []):
        if not isinstance(raw_link, dict):
            continue
        source = str(raw_link.get("source") or "").strip()
        target = str(raw_link.get("target") or "").strip()
        if not source or not target or source == target:
            continue
        if source not in nodes_by_id or target not in nodes_by_id:
            continue
        key = (source, target)
        link = links_by_key.setdefault(
            key,
            {
                "source": source,
                "target": target,
                "mode": str(raw_link.get("mode") or "other"),
                "count": 0,
                "route_count": 0,
                "route_ids": set(),
            },
        )
        try:
            link["count"] += max(int(raw_link.get("count") or 1), 1)
        except Exception:
            link["count"] += 1
        try:
            link["route_count"] += max(int(raw_link.get("route_count") or 0), 0)
        except Exception:
            pass
        for route_id in raw_link.get("route_ids") or []:
            route_text = str(route_id or "").strip()
            if route_text:
                link["route_ids"].add(route_text)

    links: list[dict[str, Any]] = []
    for link in links_by_key.values():
        nodes_by_id[link["source"]]["render_degree"] += 1
        nodes_by_id[link["target"]]["render_degree"] += 1
        links.append(
            {
                "source": link["source"],
                "target": link["target"],
                "mode": link["mode"],
                "count": int(link["count"]),
                "route_count": int(link["route_count"]),
                "route_ids": sorted(link["route_ids"]),
            }
        )

    nodes = list(nodes_by_id.values())
    log_event(
        LOGGER,
        "render_graph_loaded",
        source=json_path,
        node_count=len(nodes),
        link_count=len(links),
        meta=data.get("meta") or {},
    )
    return {
        "meta": data.get("meta") or {},
        "nodes": nodes,
        "nodes_by_id": nodes_by_id,
        "links": links,
    }


def _merged_render_graph(render_graphs_by_mode: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    nodes_by_id: dict[str, dict[str, Any]] = {}
    links_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}

    for mode in ("bus", "tram", "metro", "rail"):
        render_graph = render_graphs_by_mode.get(mode)
        if not render_graph:
            continue
        for node in render_graph.get("nodes", []):
            node_id = str(node.get("id") or "")
            if node_id and node_id not in nodes_by_id:
                nodes_by_id[node_id] = dict(node)
        for link in render_graph.get("links", []):
            key = (
                str(link.get("source") or ""),
                str(link.get("target") or ""),
                str(link.get("mode") or mode),
            )
            if not key[0] or not key[1]:
                continue
            merged = links_by_key.setdefault(
                key,
                {
                    "source": key[0],
                    "target": key[1],
                    "mode": key[2],
                    "count": 0,
                    "route_count": 0,
                    "route_ids": set(),
                },
            )
            merged["count"] += int(link.get("count") or 1)
            merged["route_count"] += int(link.get("route_count") or 0)
            for route_id in link.get("route_ids") or []:
                route_text = str(route_id or "").strip()
                if route_text:
                    merged["route_ids"].add(route_text)

    if not nodes_by_id:
        return None

    links: list[dict[str, Any]] = []
    for link in links_by_key.values():
        links.append(
            {
                "source": link["source"],
                "target": link["target"],
                "mode": link["mode"],
                "count": int(link["count"]),
                "route_count": int(link["route_count"]),
                "route_ids": sorted(link["route_ids"]),
            }
        )

    return {
        "meta": {
            "mode": "all",
            "node_count": len(nodes_by_id),
            "link_count": len(links),
            "version": 1,
        },
        "nodes": list(nodes_by_id.values()),
        "nodes_by_id": nodes_by_id,
        "links": links,
    }


def _active_render_graph_for_mode(
    current_mode: str,
    render_graphs_by_mode: dict[str, dict[str, Any]] | None,
) -> dict[str, Any] | None:
    if not render_graphs_by_mode:
        return None

    active = render_graphs_by_mode.get(current_mode)
    if active and active.get("nodes"):
        return active
    if current_mode == "all":
        return _merged_render_graph(render_graphs_by_mode)
    return None


def _edge_mode(data: dict[str, Any]) -> str:
    if data.get("edge_kind") == "transfer":
        return "transfer"
    modes = [mode for mode in _split_modes(data.get("modes")) if mode != "transfer"]
    if len(set(modes)) == 1:
        return modes[0]
    if len(modes) > 1:
        return "multi"
    mode = str(data.get("mode") or "other")
    return mode if mode != "transfer" else "transfer"


def _visible_node_mode(G: nx.Graph, node_id: str) -> str:
    visible_modes: set[str] = set()
    for _u, _v, data in G.edges(node_id, data=True):
        mode = _edge_mode(data)
        if mode != "transfer":
            visible_modes.add(mode)
    if len(visible_modes) == 1:
        return next(iter(visible_modes))
    if len(visible_modes) > 1:
        return "multi"
    return "other"


def _line_summary(attrs: dict[str, Any], max_items: int = 4) -> str:
    lines = attrs.get("lines") or {}
    parts: list[str] = []
    for mode in ("metro", "rail", "tram", "bus"):
        values = list(lines.get(mode, []))
        if values:
            parts.append(f"{mode}: {', '.join(values[:max_items])}")
    return " | ".join(parts)


def _node_size(G: nx.Graph, node_id: str) -> float:
    return 6.0 + min(float(G.degree[node_id]) * 0.18, 8.0)


def _station_degree(G: nx.Graph, stop_id: str, attrs: dict[str, Any]) -> int:
    if stop_id in G:
        return int(G.degree[stop_id])
    return int(attrs.get("render_degree") or 0)


def _station_radius(G: nx.Graph, stop_id: str, attrs: dict[str, Any]) -> float:
    if stop_id in G:
        return _node_size(G, stop_id)
    return 6.0 + min(float(attrs.get("render_degree") or 0) * 0.18, 8.0)


def _station_visible_mode(G: nx.Graph, stop_id: str, attrs: dict[str, Any]) -> str:
    if stop_id in G:
        return _visible_node_mode(G, stop_id)
    mode = str(attrs.get("mode") or "other")
    return mode if mode else "other"


def _node_lon_lat(attrs: dict[str, Any]) -> tuple[float, float] | None:
    lat = attrs.get("lat")
    lon = attrs.get("lon")
    if not _valid_lat_lon(lat, lon):
        return None
    return float(lon), float(lat)


def _render_node_lon_lat(node: dict[str, Any]) -> tuple[float, float] | None:
    lat = node.get("lat")
    lon = node.get("lon")
    if not _valid_lat_lon(lat, lon):
        return None
    return float(lon), float(lat)


def _line_labels_for_node(attrs: dict[str, Any], mode: str) -> set[str]:
    values = (attrs.get("lines") or {}).get(mode, [])
    return {_normalize_label(value) for value in values if _normalize_label(value)}


def _edge_route_refs(data: dict[str, Any]) -> list[dict[str, str]]:
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


def _display_mode_name(mode: str) -> str:
    return {"metro": "Metro", "rail": "RER", "tram": "Tram", "bus": "Bus"}.get(mode, mode.title())


def _format_station_line(mode: str, label: str) -> str:
    text = str(label or "").strip()
    lowered = text.lower()
    if mode == "metro" and lowered.startswith("line "):
        return text[5:].strip()
    if mode == "rail":
        if lowered.startswith("rer "):
            return text[4:].strip()
        if lowered.startswith("rail "):
            return text[5:].strip()
    if mode == "tram" and lowered.startswith("tram "):
        return text[5:].strip()
    if mode == "bus" and lowered.startswith("bus "):
        return text[4:].strip()
    return text


def _station_lines_by_mode(attrs: dict[str, Any]) -> dict[str, list[str]]:
    lines = attrs.get("lines") or {}
    out: dict[str, list[str]] = {}
    for transport_mode in ("metro", "rail", "tram", "bus"):
        values: list[str] = []
        seen: set[str] = set()
        for label in list(lines.get(transport_mode, [])):
            formatted = _format_station_line(transport_mode, str(label))
            if formatted and formatted not in seen:
                seen.add(formatted)
                values.append(formatted)
        if values:
            out[transport_mode] = values
    return out


def _station_hover_html(stop_name: str, attrs: dict[str, Any]) -> str:
    grouped_lines = _station_lines_by_mode(attrs)
    parts = [f"<b>{stop_name}</b>"]
    for transport_mode in ("metro", "rail"):
        values = grouped_lines.get(transport_mode, [])
        if values:
            parts.append(f"{_display_mode_name(transport_mode)}: {', '.join(values)}")
    return "<br>".join(parts)


def _mode_pill_html(mode: str) -> str:
    color = MODE_COLORS.get(mode, MODE_COLORS["other"])
    return (
        f'<span class="station-pill station-pill--mode" style="--pill-color:{escape(color)};">'
        f"{escape(_display_mode_name(mode))}"
        "</span>"
    )


def _line_pill_html(mode: str, line: str) -> str:
    if mode == "metro":
        metro_key = _metro_line_key(line)
        if metro_key in METRO_LINE_COLORS:
            bg_color = METRO_LINE_COLORS[metro_key]
            text_color = _text_color_for_background(bg_color)
            label_html = escape(str(line).strip())
            if metro_key in {"3B", "7B"}:
                label_html = escape(metro_key[0]) + '<span class="metro-badge__bis">bis</span>'
            return (
                f'<span class="metro-badge" style="background:{escape(bg_color)};color:{text_color};">'
                f"{label_html}"
                "</span>"
            )
    color = MODE_COLORS.get(mode, MODE_COLORS["other"])
    return (
        f'<span class="station-pill station-pill--line" style="--pill-color:{escape(color)};">'
        f"{escape(line)}"
        "</span>"
    )


def _metric_card_html(label: str, value: str) -> str:
    return (
        '<div class="station-metric">'
        f'<div class="station-metric__value">{escape(value)}</div>'
        f'<div class="station-metric__label">{escape(label)}</div>'
        "</div>"
    )


def _line_groups_html(grouped_lines: dict[str, list[str]]) -> str:
    blocks: list[str] = []
    for mode in ("metro", "rail", "tram", "bus"):
        values = grouped_lines.get(mode, [])
        if not values:
            continue
        chips = "".join(_line_pill_html(mode, value) for value in values)
        blocks.append(
            '<div class="station-line-group">'
            f'<div class="station-line-group__title">{escape(_display_mode_name(mode))}</div>'
            f'<div class="station-pill-row">{chips}</div>'
            "</div>"
        )
    if not blocks:
        return '<div class="station-empty">No line data available.</div>'
    return "".join(blocks)


def _poi_card_html(row: dict[str, Any]) -> str:
    name = str(row.get("name") or "").strip() or "(unnamed)"
    category = str(row.get("category") or "")
    category_type = str(row.get("type") or "")
    distance_m = float(row.get("distance_m") or 0.0)
    badge = _poi_badge_style(category, category_type)
    family = str(badge["family"]).replace("_", " ").title()
    type_label = category_type.replace("_", " ").title() if category_type else family
    meta_parts = [family]
    if type_label and type_label != family:
        meta_parts.append(type_label)
    meta_parts.append(f"{distance_m:.0f} m")
    meta_text = " | ".join(meta_parts)
    return (
        '<div class="poi-card">'
        f'<div class="poi-card__icon" style="background:{escape(badge["color"])};">'
        f'<i class="{escape(badge["icon_class"])}" aria-hidden="true"></i>'
        "</div>"
        '<div class="poi-card__body">'
        f'<div class="poi-card__title">{escape(name)}</div>'
        f'<div class="poi-card__meta">{escape(meta_text)}</div>'
        "</div>"
        "</div>"
    )


def _station_click_html(G: nx.Graph, stop_id: str, attrs: dict[str, Any]) -> str:
    grouped_lines = _station_lines_by_mode(attrs)
    all_lines = [line for mode in ("metro", "rail", "tram", "bus") for line in grouped_lines.get(mode, [])]
    stop_name = str(attrs.get("stop_name", stop_id))
    mode_pills = "".join(_mode_pill_html(mode) for mode in grouped_lines)
    mode_section = mode_pills or '<div class="station-empty">No mode data available.</div>'
    degree = _station_degree(G, stop_id, attrs)
    metrics = "".join(
        [
            _metric_card_html("Connections", str(degree)),
            _metric_card_html("Modes", str(len(grouped_lines))),
            _metric_card_html("Lines", str(len(all_lines))),
        ]
    )
    return (
        '<div class="station-card">'
        '<div class="station-card__hero">'
        '<div class="station-card__eyebrow">Transit stop</div>'
        f'<div class="station-card__title">{escape(stop_name)}</div>'
        f'<div class="station-card__subtitle">Stop ID {escape(stop_id)}</div>'
        "</div>"
        f'<div class="station-metrics">{metrics}</div>'
        '<div class="station-section">'
        '<div class="station-section__title">Modes</div>'
        f'<div class="station-pill-row">{mode_section}</div>'
        "</div>"
        '<div class="station-section">'
        '<div class="station-section__title">Lines</div>'
        f"{_line_groups_html(grouped_lines)}"
        "</div>"
        "</div>"
    )


def _station_click_html_with_pois(
    G: nx.Graph,
    stop_id: str,
    attrs: dict[str, Any],
    *,
    poi_lookup: LocalPOILookup | None,
    poi_radius_m: float,
    poi_limit: int,
    poi_category_key: str | None = None,
    poi_category_value: str | None = None,
) -> str:
    base_html = _station_click_html(G, stop_id, attrs).removesuffix("</div>")
    poi_rows: list[dict[str, Any]] = []

    if poi_lookup is not None and (point := _node_lon_lat(attrs)) is not None:
        poi_rows = poi_lookup.query(
            point[1],
            point[0],
            radius_m=poi_radius_m,
            category_key=poi_category_key,
            category_value=poi_category_value,
            limit=poi_limit,
        )

    if poi_rows:
        poi_cards = "".join(_poi_card_html(row) for row in poi_rows)
    else:
        poi_cards = '<div class="station-empty">No nearby POIs found for this radius.</div>'

    return (
        base_html
        + '<div class="station-section">'
        + f'<div class="station-section__title">Nearby POIs <span class="station-section__hint">{int(poi_radius_m)} m</span></div>'
        + f'<div class="poi-card-list">{poi_cards}</div>'
        + "</div></div>"
    )


def _nearby_pois_for_station(
    attrs: dict[str, Any],
    *,
    poi_lookup: LocalPOILookup | None,
    poi_radius_m: float,
    poi_limit: int,
    poi_category_key: str | None = None,
    poi_category_value: str | None = None,
) -> list[dict[str, Any]]:
    if poi_lookup is None:
        return []

    point = _node_lon_lat(attrs)
    if point is None:
        return []

    rows = poi_lookup.query(
        point[1],
        point[0],
        radius_m=poi_radius_m,
        category_key=poi_category_key,
        category_value=poi_category_value,
        limit=poi_limit,
    )
    return [
        {
            "name": str(row.get("name") or "").strip() or "(unnamed)",
            "category": str(row.get("category") or ""),
            "type": str(row.get("type") or ""),
            "lat": float(row["lat"]),
            "lon": float(row["lon"]),
            "distance_m": float(row["distance_m"]),
            **_poi_badge_style(row.get("category"), row.get("type")),
        }
        for row in rows
    ]


def _distance_sq(a: tuple[float, float], b: tuple[float, float]) -> float:
    lon_scale = max(0.2, math.cos(math.radians((a[1] + b[1]) * 0.5)))
    dx = (a[0] - b[0]) * lon_scale
    dy = a[1] - b[1]
    return dx * dx + dy * dy


def _candidate_features_by_route_id(
    line_geometries: dict[str, Any],
    candidate_modes: list[str],
    route_refs: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], list[str]]:
    features: list[dict[str, Any]] = []
    seen: set[int] = set()
    requested_route_ids: list[str] = []

    for mode in candidate_modes:
        by_route_id = line_geometries["by_route_id"].get(mode, {})
        route_ids = sorted(
            {
                _normalize_route_id(ref.get("route_id", ""))
                for ref in route_refs
                if _normalize_route_id(ref.get("route_id", "")) and str(ref.get("mode", mode)) == mode
            }
        )
        for route_id in route_ids:
            requested_route_ids.append(route_id)
            for feature in by_route_id.get(route_id, []):
                feature_id = id(feature)
                if feature_id in seen:
                    continue
                seen.add(feature_id)
                features.append(feature)

    return features, requested_route_ids


def _candidate_features_by_label(
    line_geometries: dict[str, Any],
    candidate_modes: list[str],
    route_refs: list[dict[str, str]],
    attrs_u: dict[str, Any],
    attrs_v: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[str]]:
    features: list[dict[str, Any]] = []
    seen: set[int] = set()
    requested_labels: list[str] = []

    for mode in candidate_modes:
        by_label = line_geometries["by_label"].get(mode, {})
        edge_labels = {
            _normalize_label(ref.get("route_label", ""))
            for ref in route_refs
            if _normalize_label(ref.get("route_label", "")) and str(ref.get("mode", mode)) == mode
        }
        labels_u = _line_labels_for_node(attrs_u, mode)
        labels_v = _line_labels_for_node(attrs_v, mode)
        shared_node_labels = labels_u & labels_v
        ordered_labels = (
            sorted(edge_labels & shared_node_labels)
            + sorted(edge_labels - shared_node_labels)
            + sorted(shared_node_labels - edge_labels)
            + sorted((labels_u | labels_v) - edge_labels - shared_node_labels)
        )
        for label in ordered_labels:
            requested_labels.append(label)
            for feature in by_label.get(label, []):
                feature_id = id(feature)
                if feature_id in seen:
                    continue
                seen.add(feature_id)
                features.append(feature)
    return features, requested_labels


def _best_segment_between_points(
    features: list[dict[str, Any]],
    start_point: tuple[float, float],
    end_point: tuple[float, float],
) -> tuple[list[tuple[float, float]] | None, dict[str, Any] | None]:
    best_piece = None
    best_score = float("inf")
    best_feature = None

    for feature in features:
        for segment in feature["segments"]:
            start_idx = min(range(len(segment)), key=lambda idx: _distance_sq(segment[idx], start_point))
            end_idx = min(range(len(segment)), key=lambda idx: _distance_sq(segment[idx], end_point))
            score = _distance_sq(segment[start_idx], start_point) + _distance_sq(segment[end_idx], end_point)

            left = min(start_idx, end_idx)
            right = max(start_idx, end_idx)
            piece = segment[left : right + 1]
            if start_idx > end_idx:
                piece = list(reversed(piece))
            if len(piece) < 2:
                continue

            if score < best_score:
                best_score = score
                best_piece = list(piece)
                best_feature = feature

    if best_piece is None or best_score > 0.0012:
        return None, None

    if _distance_sq(best_piece[0], start_point) > 1e-10:
        best_piece.insert(0, start_point)
    if _distance_sq(best_piece[-1], end_point) > 1e-10:
        best_piece.append(end_point)
    return best_piece, best_feature


def _center_and_zoom(
    G: nx.Graph,
    *,
    render_nodes: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, float], float]:
    lats: list[float] = []
    lons: list[float] = []
    if render_nodes is not None:
        for node in render_nodes:
            lat = node.get("lat")
            lon = node.get("lon")
            if not _valid_lat_lon(lat, lon):
                continue
            lats.append(float(lat))
            lons.append(float(lon))
    else:
        for _node, attrs in G.nodes(data=True):
            lat = attrs.get("lat")
            lon = attrs.get("lon")
            if not _valid_lat_lon(lat, lon):
                continue
            lats.append(float(lat))
            lons.append(float(lon))
    if not lats or not lons:
        return DEFAULT_CENTER, DEFAULT_ZOOM
    lat_span = max(lats) - min(lats)
    lon_span = max(lons) - min(lons)
    max_span = max(lat_span, lon_span)
    if max_span > 6.0:
        zoom = 5.8
    elif max_span > 3.0:
        zoom = 6.6
    elif max_span > 1.5:
        zoom = 7.5
    elif max_span > 0.8:
        zoom = 8.3
    elif max_span > 0.4:
        zoom = 9.2
    elif max_span > 0.2:
        zoom = 10.1
    elif max_span > 0.1:
        zoom = 11.0
    else:
        zoom = 12.3
    center = {
        "lat": (min(lats) + max(lats)) / 2.0,
        "lon": (min(lons) + max(lons)) / 2.0,
    }
    return center, zoom


def _build_edge_trace(
    G: nx.Graph,
    edge_pairs: list[tuple[str, str]],
    *,
    color: str,
    width: float,
    opacity: float,
    name: str,
):
    segments: list[list[tuple[float, float]]] = []
    for u, v in edge_pairs:
        start_point = _node_lon_lat(G.nodes[str(u)])
        end_point = _node_lon_lat(G.nodes[str(v)])
        if start_point is None or end_point is None:
            continue
        segments.append([start_point, end_point])
    return _build_geometry_trace(segments, color=color, width=width, opacity=opacity, name=name)


def _build_geometry_trace(
    segments: list[list[tuple[float, float]]],
    *,
    color: str,
    width: float,
    opacity: float,
    name: str,
):
    lats: list[float | None] = []
    lons: list[float | None] = []
    for segment in segments:
        if len(segment) < 2:
            continue
        for lon, lat in segment:
            lons.append(lon)
            lats.append(lat)
        lons.append(None)
        lats.append(None)
    if not lats or not lons:
        return None
    return go.Scattermapbox(
        lat=lats,
        lon=lons,
        mode="lines",
        line={"color": color, "width": width},
        opacity=opacity,
        name=name,
        hoverinfo="skip",
    )


def _network_layer_groups(
    line_geometries: dict[str, Any] | None,
    current_mode: str,
) -> list[dict[str, Any]]:
    if not line_geometries:
        return []

    trace_modes = ("bus", "tram", "metro", "rail", "other") if current_mode == "all" else (current_mode,)
    groups: list[dict[str, Any]] = []

    for mode in trace_modes:
        features = line_geometries["by_mode"].get(mode, [])
        if not features:
            continue

        if mode == "metro":
            segments_by_line: dict[str, list[list[tuple[float, float]]]] = {}
            for feature in features:
                line_key = _metro_line_key(feature.get("route_short_name")) or _metro_line_key(feature.get("route_long_name"))
                if line_key is None:
                    line_key = "metro"
                segments_by_line.setdefault(line_key, []).extend(feature["segments"])

            def _metro_sort_key(item: tuple[str, list[list[tuple[float, float]]]]):
                key = item[0]
                if key.endswith("B") and key[:-1].isdigit():
                    return (int(key[:-1]), 1)
                if key.isdigit():
                    return (int(key), 0)
                return (999, 0)

            for line_key, segments in sorted(segments_by_line.items(), key=_metro_sort_key):
                groups.append(
                    {
                        "name": f"Metro Line {line_key}",
                        "color": METRO_LINE_COLORS.get(line_key, MODE_COLORS["metro"]),
                        "width": 2.3,
                        "opacity": 0.34,
                        "segments": segments,
                    }
                )
            continue

        if mode == "rail":
            segments_by_line: dict[str, list[list[tuple[float, float]]]] = {}
            for feature in features:
                line_key = _rail_line_key(feature.get("route_short_name"), feature.get("route_long_name"))
                if line_key is None:
                    line_key = "rail"
                segments_by_line.setdefault(line_key, []).extend(feature["segments"])

            def _rail_sort_key(item: tuple[str, list[list[tuple[float, float]]]]):
                key = item[0]
                return (0, key) if key in RAIL_LINE_COLORS else (1, key)

            for line_key, segments in sorted(segments_by_line.items(), key=_rail_sort_key):
                groups.append(
                    {
                        "name": f"Rail Line {line_key}" if line_key != "rail" else "Rail routes",
                        "color": RAIL_LINE_COLORS.get(line_key, MODE_COLORS["rail"]),
                        "width": 2.3,
                        "opacity": 0.34,
                        "segments": segments,
                    }
                )
            continue

        if mode == "tram":
            segments_by_line: dict[str, list[list[tuple[float, float]]]] = {}
            for feature in features:
                line_key = _tram_line_key(feature.get("route_short_name"), feature.get("route_long_name"))
                if line_key is None:
                    line_key = "tram"
                segments_by_line.setdefault(line_key, []).extend(feature["segments"])

            def _tram_sort_key(item: tuple[str, list[list[tuple[float, float]]]]):
                key = item[0]
                if key.startswith("T") and key[1:].replace("A", "").replace("B", "").isdigit():
                    numeric = "".join(ch for ch in key[1:] if ch.isdigit())
                    suffix = "".join(ch for ch in key[1:] if ch.isalpha())
                    return (0, int(numeric or "999"), suffix)
                return (1, 999, key)

            for line_key, segments in sorted(segments_by_line.items(), key=_tram_sort_key):
                groups.append(
                    {
                        "name": f"Tram Line {line_key}" if line_key != "tram" else "Tram routes",
                        "color": TRAM_LINE_COLORS.get(line_key, MODE_COLORS["tram"]),
                        "width": 2.3,
                        "opacity": 0.34,
                        "segments": segments,
                    }
                )
            continue

        segments: list[list[tuple[float, float]]] = []
        for feature in features:
            segments.extend(feature["segments"])
        groups.append(
            {
                "name": f"{mode.title()} routes",
                "color": MODE_COLORS.get(mode, MODE_COLORS["other"]),
                "width": 1.6 if mode == "bus" else 2.1,
                "opacity": 0.14 if mode == "bus" else 0.24,
                "segments": segments,
            }
        )

    return groups


def _build_network_geometry_traces(
    line_geometries: dict[str, Any] | None,
    current_mode: str,
) -> list[go.Scattermapbox]:
    traces: list[go.Scattermapbox] = []
    for group in _network_layer_groups(line_geometries, current_mode):
        trace = _build_geometry_trace(
            group["segments"],
            color=group["color"],
            width=group["width"],
            opacity=group["opacity"],
            name=group["name"],
        )
        if trace is not None:
            traces.append(trace)
    return traces


def _path_geometry_segments(
    G: nx.Graph,
    path: list[str] | None,
    current_mode: str,
    line_geometries: dict[str, Any] | None,
) -> tuple[list[list[tuple[float, float]]], dict[str, Any]]:
    if not path or len(path) < 2:
        return [], {"summary": {"route_id": 0, "heuristic_label": 0, "straight_fallback": 0}, "segments": []}

    segments: list[list[tuple[float, float]]] = []
    debug_rows: list[dict[str, Any]] = []
    summary = {"route_id": 0, "heuristic_label": 0, "straight_fallback": 0}

    for u, v in zip(path, path[1:]):
        u = str(u)
        v = str(v)
        attrs_u = G.nodes[u]
        attrs_v = G.nodes[v]
        start_point = _node_lon_lat(attrs_u)
        end_point = _node_lon_lat(attrs_v)
        if start_point is None or end_point is None:
            continue

        data = G.get_edge_data(u, v) or {}
        route_refs = _edge_route_refs(data)
        match_type = "straight_fallback"
        candidate_route_ids: list[str] = []
        candidate_labels: list[str] = []
        matched_feature = None

        if data.get("edge_kind") == "transfer":
            segments.append([start_point, end_point])
            summary["straight_fallback"] += 1
            debug_rows.append(
                {
                    "segment_index": len(debug_rows) + 1,
                    "from_stop_id": u,
                    "to_stop_id": v,
                    "edge_kind": "transfer",
                    "edge_mode": str(data.get("mode") or "transfer"),
                    "match_type": match_type,
                    "edge_route_ids": [],
                    "edge_route_labels": [],
                    "candidate_route_ids": [],
                    "candidate_labels": [],
                    "matched_geojson_route_id": "",
                    "matched_geojson_short_name": "",
                    "matched_geojson_long_name": "",
                }
            )
            continue

        candidate_modes = [current_mode] if current_mode != "all" else [
            mode for mode in _split_modes(str(data.get("modes") or data.get("mode") or "")) if mode != "transfer"
        ]
        if not candidate_modes:
            candidate_modes = [str(data.get("mode") or "other")]

        piece = None
        if line_geometries:
            features_by_route_id, candidate_route_ids = _candidate_features_by_route_id(
                line_geometries,
                candidate_modes,
                route_refs,
            )
            piece, matched_feature = _best_segment_between_points(features_by_route_id, start_point, end_point)
            if piece is not None:
                match_type = "route_id"
            else:
                features_by_label, candidate_labels = _candidate_features_by_label(
                    line_geometries,
                    candidate_modes,
                    route_refs,
                    attrs_u,
                    attrs_v,
                )
                piece, matched_feature = _best_segment_between_points(features_by_label, start_point, end_point)
                if piece is not None:
                    match_type = "heuristic_label"

        if piece is None:
            piece = [start_point, end_point]

        summary[match_type] += 1
        segments.append(piece)
        debug_rows.append(
            {
                "segment_index": len(debug_rows) + 1,
                "from_stop_id": u,
                "to_stop_id": v,
                "edge_kind": str(data.get("edge_kind") or "ride"),
                "edge_mode": str(data.get("mode") or current_mode),
                "match_type": match_type,
                "edge_route_ids": [ref["route_id"] for ref in route_refs if ref.get("route_id")],
                "edge_route_labels": [ref["route_label"] for ref in route_refs if ref.get("route_label")],
                "candidate_route_ids": candidate_route_ids,
                "candidate_labels": candidate_labels,
                "matched_geojson_route_id": "" if matched_feature is None else str(matched_feature.get("route_id") or ""),
                "matched_geojson_short_name": ""
                if matched_feature is None
                else str(matched_feature.get("route_short_name") or ""),
                "matched_geojson_long_name": ""
                if matched_feature is None
                else str(matched_feature.get("route_long_name") or ""),
            }
        )

    return segments, {"summary": summary, "segments": debug_rows}


def plot_graph_mapbox(
    G: nx.Graph,
    *,
    mapbox_token: str,
    mode: str,
    path: list[str] | None = None,
    selected_stop_id: str | None = None,
    show_transfers: bool = False,
    title: str = "",
    line_geometries: dict[str, Any] | None = None,
):
    traces: list[go.Scattermapbox] = []
    traces.extend(_build_network_geometry_traces(line_geometries, mode))

    if show_transfers:
        transfer_edges = [
            (str(u), str(v))
            for u, v, data in G.edges(data=True)
            if _edge_mode(data) == "transfer"
        ]
        transfer_trace = _build_edge_trace(
            G,
            transfer_edges,
            color=MODE_COLORS["transfer"],
            width=1.1,
            opacity=0.18,
            name="Transfer edges",
        )
        if transfer_trace is not None:
            traces.append(transfer_trace)

    path_segments, path_debug = _path_geometry_segments(G, path, mode, line_geometries)
    path_trace = _build_geometry_trace(
        path_segments,
        color=MODE_COLORS["path"],
        width=4.8,
        opacity=1.0,
        name="Selected path",
    )
    if path_trace is not None:
        traces.append(path_trace)

    lats: list[float] = []
    lons: list[float] = []
    sizes: list[float] = []
    colors: list[str] = []
    customdata: list[list[Any]] = []
    hover_text: list[str] = []
    selected_point_index = None
    for node, attrs in G.nodes(data=True):
        sid = str(node)
        lat = attrs.get("lat")
        lon = attrs.get("lon")
        if not _valid_lat_lon(lat, lon):
            continue
        lat = float(lat)
        lon = float(lon)
        stop_name = str(attrs.get("stop_name", sid))
        visible_mode = _visible_node_mode(G, sid)
        lats.append(lat)
        lons.append(lon)
        sizes.append(_node_size(G, sid))
        colors.append(MODE_COLORS.get(visible_mode, MODE_COLORS["other"]))
        customdata.append([sid])
        hover_text.append(
            _station_click_html(G, sid, attrs) if sid == selected_stop_id else _station_hover_html(stop_name, attrs)
        )
        if sid == selected_stop_id:
            selected_point_index = len(lats) - 1

    traces.append(
        go.Scattermapbox(
            lat=lats,
            lon=lons,
            mode="markers",
            name="Stops",
            customdata=customdata,
            hovertext=hover_text,
            marker={"size": sizes, "color": colors, "opacity": 0.8},
            hovertemplate="%{hovertext}<extra></extra>",
            selectedpoints=[] if selected_point_index is None else [selected_point_index],
            selected={"marker": {"size": 14, "opacity": 1.0, "color": MODE_COLORS["selected"]}},
            unselected={"marker": {"opacity": 0.55}},
        )
    )

    center, zoom = _center_and_zoom(G)
    fig = go.Figure(data=traces)
    fig.update_layout(
        title=title,
        margin={"l": 0, "r": 0, "t": 42, "b": 0},
        clickmode="event+select",
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.01, "xanchor": "left", "x": 0.0},
        mapbox={
            "accesstoken": mapbox_token,
            "style": "mapbox://styles/mapbox/light-v11",
            "center": center,
            "zoom": zoom,
        },
        uirevision="mapbox-network",
    )
    return fig, path_debug


def _segments_to_multiline_feature(
    segments: list[list[tuple[float, float]]],
    *,
    properties: dict[str, Any],
) -> dict[str, Any] | None:
    coordinates: list[list[list[float]]] = []
    for segment in segments:
        if len(segment) < 2:
            continue
        coordinates.append([[float(lon), float(lat)] for lon, lat in segment])
    if not coordinates:
        return None
    return {
        "type": "Feature",
        "geometry": {"type": "MultiLineString", "coordinates": coordinates},
        "properties": properties,
    }


def _stations_feature_collection(
    G: nx.Graph,
    *,
    current_mode: str | None = None,
    render_graph: dict[str, Any] | None = None,
    poi_lookup: LocalPOILookup | None = None,
    poi_radius_m: float = 300.0,
    poi_limit: int = 8,
    poi_category_key: str | None = None,
    poi_category_value: str | None = None,
) -> dict[str, Any]:
    features: list[dict[str, Any]] = []
    lightweight_popups = render_graph is not None and len(render_graph.get("nodes", [])) > 5000
    if render_graph is not None:
        node_rows = []
        for render_node in render_graph.get("nodes", []):
            sid = str(render_node.get("id") or "")
            attrs = dict(render_node)
            if sid in G:
                attrs = {**dict(G.nodes[sid]), **attrs}
            attrs["stop_name"] = str(attrs.get("stop_name") or render_node.get("name") or sid)
            attrs["lat"] = float(render_node.get("lat", render_node.get("y")))
            attrs["lon"] = float(render_node.get("lon", render_node.get("x")))
            attrs["mode"] = str(render_node.get("mode") or "bus")
            attrs["render_degree"] = int(render_node.get("render_degree") or 0)
            node_rows.append((sid, attrs, render_node))
    else:
        node_rows = [(str(node), dict(attrs), None) for node, attrs in G.nodes(data=True)]

    for sid, attrs, render_node in node_rows:
        point = _node_lon_lat(attrs)
        if point is None:
            continue

        stop_name = str(attrs.get("stop_name", sid))
        visible_mode = _station_visible_mode(G, sid, attrs)
        nearby_pois: list[dict[str, Any]] = []
        hover_html = _station_hover_html(stop_name, attrs)
        click_html = _station_click_html_with_pois(
            G,
            sid,
            attrs,
            poi_lookup=poi_lookup,
            poi_radius_m=poi_radius_m,
            poi_limit=poi_limit,
            poi_category_key=poi_category_key,
            poi_category_value=poi_category_value,
        )
        nearby_pois_json = "[]"
        if lightweight_popups:
            hover_html = ""
            click_html = ""
        else:
            nearby_pois = _nearby_pois_for_station(
                attrs,
                poi_lookup=poi_lookup,
                poi_radius_m=poi_radius_m,
                poi_limit=poi_limit,
                poi_category_key=poi_category_key,
                poi_category_value=poi_category_value,
            )
            nearby_pois_json = json.dumps(nearby_pois, ensure_ascii=True, separators=(",", ":"))
        features.append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": (
                        [point[0], point[1], float(render_node.get("z") or 0.0)]
                        if render_node is not None
                        else [point[0], point[1]]
                    ),
                },
                "properties": {
                    "stop_id": sid,
                    "stop_name": stop_name,
                    "hover_html": hover_html,
                    "click_html": click_html,
                    "nearby_pois_json": nearby_pois_json,
                    "connections": _station_degree(G, sid, attrs),
                    "visible_mode": visible_mode,
                    "render_popup_mode": "light" if lightweight_popups else "full",
                    "color": MODE_COLORS.get(visible_mode, MODE_COLORS["other"]),
                    "radius": _station_radius(G, sid, attrs),
                },
            }
        )

    return {"type": "FeatureCollection", "features": features}


def _network_feature_collection(
    line_geometries: dict[str, Any] | None,
    current_mode: str,
    *,
    render_graphs_by_mode: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    del render_graphs_by_mode

    features: list[dict[str, Any]] = []
    for group in _network_layer_groups(line_geometries, current_mode):
        feature = _segments_to_multiline_feature(
            group["segments"],
            properties={
                "name": group["name"],
                "color": group["color"],
                "width": group["width"],
                "opacity": group["opacity"],
            },
        )
        if feature is not None:
            features.append(feature)
    return {"type": "FeatureCollection", "features": features}


def _path_feature_collection(
    G: nx.Graph,
    path: list[str] | None,
    current_mode: str,
    line_geometries: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    path_segments, path_debug = _path_geometry_segments(G, path, current_mode, line_geometries)
    feature = _segments_to_multiline_feature(
        path_segments,
        properties={
            "name": "Selected path",
            "color": MODE_COLORS["path"],
            "width": 4.8,
            "opacity": 1.0,
        },
    )
    features = [] if feature is None else [feature]
    return {"type": "FeatureCollection", "features": features}, path_debug


def render_mapbox_gl_html( 
    G: nx.Graph,
    *,
    mapbox_token: str,
    mode: str,
    path: list[str] | None = None,
    show_transfers: bool = False,
    title: str = "",
    basemap_style: str = "mapbox://styles/mapbox/light-v11",
    line_geometries: dict[str, Any] | None = None,
    render_graphs_by_mode: dict[str, dict[str, Any]] | None = None,
    poi_lookup: LocalPOILookup | None = None,
    poi_radius_m: float = 300.0,
    poi_limit: int = 8,
    poi_category_key: str | None = None,
    poi_category_value: str | None = None,
    pitched_view: bool = False,
    show_3d_buildings: bool = False,
    height_px: int = 700,
    overlay_controls_html: str = "",
) -> tuple[str, dict[str, Any]]:
    active_render_graph = _active_render_graph_for_mode(mode, render_graphs_by_mode)
    center, zoom = _center_and_zoom(G, render_nodes=None if active_render_graph is None else active_render_graph.get("nodes"))
    network_source = _network_feature_collection(
        line_geometries,
        mode,
        render_graphs_by_mode=render_graphs_by_mode,
    
    )
    path_source, path_debug = _path_feature_collection(G, path, mode, line_geometries)
    stations_source = _stations_feature_collection(
        G,
        current_mode=mode,
        render_graph=active_render_graph,
        poi_lookup=poi_lookup,
        poi_radius_m=poi_radius_m,
        poi_limit=poi_limit,
        poi_category_key=poi_category_key,
        poi_category_value=poi_category_value,
    )

    transfer_features: list[dict[str, Any]] = []
    if show_transfers:
        transfer_pairs = [
            (str(u), str(v))
            for u, v, data in G.edges(data=True)
            if _edge_mode(data) == "transfer"
        ]
        feature = _segments_to_multiline_feature(
            [
                [point_u, point_v]
                for u, v in transfer_pairs
                if (point_u := _node_lon_lat(G.nodes[u])) is not None and (point_v := _node_lon_lat(G.nodes[v])) is not None
            ],
            properties={"name": "Transfer edges", "color": MODE_COLORS["transfer"], "width": 1.1, "opacity": 0.18},
        )
        if feature is not None:
            transfer_features.append(feature)

    map_payload = {
        "token": mapbox_token,
        "title": title,
        "basemap_style": basemap_style,
        "center": center,
        "attributionControl": False,
        "zoom": zoom,
        "pitch": DEFAULT_PITCH if pitched_view else 0,
        "bearing": DEFAULT_BEARING if pitched_view else 0,
        "show_3d_buildings": bool(show_3d_buildings),
        "network": network_source,
        "path": path_source,
        "stations": stations_source,
        "transfers": {"type": "FeatureCollection", "features": transfer_features},
        "clicked_pois": {"type": "FeatureCollection", "features": []},
        "height_px": int(height_px),
        "paris_mask_feature": None,
        "paris_max_bounds": None,
        "paris_mask_fill_color": "#020617",
        "paris_mask_fill_opacity": 0.9,
        "render_world_copies": True,
    }
    try:
        paris_view = build_paris_mask_payload()
        map_payload["paris_mask_feature"] = paris_view["mask_feature"]
        map_payload["paris_max_bounds"] = paris_view["max_bounds"]
        map_payload["center"] = paris_view["center"]
        map_payload["zoom"] = paris_view["zoom"]
        map_payload["render_world_copies"] = False
        log_event(
            LOGGER,
            "paris_mask_loaded",
            zoom=paris_view["zoom"],
            max_bounds=paris_view["max_bounds"],
            source_file=(paris_view["mask_feature"].get("properties") or {}).get("source_file"),
        )
    except (FileNotFoundError, ValueError, OSError, json.JSONDecodeError) as exc:
        log_event(LOGGER, "paris_mask_skipped", error=str(exc))
    log_event(
        LOGGER,
        "render_mapbox_payload_built",
        mode=mode,
        title=title,
        pitched_view=pitched_view,
        show_3d_buildings=show_3d_buildings,
        graph_nodes=G.number_of_nodes(),
        graph_edges=G.number_of_edges(),
        center=center,
        zoom=zoom,
        network_feature_count=len(network_source.get("features", [])),
        path_feature_count=len(path_source.get("features", [])),
        station_feature_count=len(stations_source.get("features", [])),
        transfer_feature_count=len(transfer_features),
        has_render_graph=active_render_graph is not None,
        render_graph_node_count=len((active_render_graph or {}).get("nodes", [])),
        render_graph_link_count=len((active_render_graph or {}).get("links", [])),
        poi_lookup_loaded=poi_lookup is not None,
        poi_radius_m=poi_radius_m,
        poi_limit=poi_limit,
        poi_category_key=poi_category_key,
        path_debug=path_debug,
    )
    payload_json = json.dumps(map_payload, ensure_ascii=True, separators=(",", ":"))

    overlay_controls_block = ""
    if overlay_controls_html.strip():
        overlay_controls_block = f"""
  <div class="map-overlay-controls" id="map-overlay-controls" data-open="false">
    <button class="map-overlay-controls__toggle" id="map-overlay-controls-toggle" type="button" aria-expanded="false">
      <span class="map-overlay-controls__toggle-label">Controls</span>
      <span class="map-overlay-controls__toggle-caret">▼</span>
    </button>
    <div class="map-overlay-panel" id="map-overlay-controls-panel">
      {overlay_controls_html}
    </div>
  </div>"""

    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <link href="https://api.mapbox.com/mapbox-gl-js/v3.4.0/mapbox-gl.css" rel="stylesheet" />
  <link
    rel="stylesheet"
    href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.2/css/all.min.css"
  />
  <style>
    html, body {{
      height: 100%;
      margin: 0;
      padding: 0;
      overflow: hidden;
      background: #1f1f1f;
      font-family: Arial, sans-serif;
    }}
    #map {{
      width: 100%;
      height: 100%;
    }}
    .map-overlay-controls {{
      position: absolute;
      top: 12px;
      left: 12px;
      z-index: 30;
      display: flex;
      flex-direction: column;
      align-items: flex-start;
      gap: 10px;
      pointer-events: none;
    }}
    .map-overlay-controls > * {{
      pointer-events: auto;
    }}
    .map-overlay-controls__toggle {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      min-height: 34px;
      padding: 0 12px;
      border: 1px solid rgba(255, 255, 255, 0.12);
      border-radius: 8px;
      background: rgba(15, 23, 42, 0.72);
      color: #f8fafc;
      backdrop-filter: blur(12px);
      -webkit-backdrop-filter: blur(12px);
      cursor: pointer;
      box-shadow: 0 10px 28px rgba(2, 6, 23, 0.28);
    }}
    .map-overlay-controls__toggle-label {{
      font-size: 12px;
      font-weight: 600;
    }}
    .map-overlay-controls__toggle-caret {{
      font-size: 10px;
      opacity: 0.85;
      transition: transform 140ms ease;
    }}
    .map-overlay-controls[data-open="true"] .map-overlay-controls__toggle-caret {{
      transform: rotate(180deg);
    }}
    .map-overlay-panel {{
      display: none;
      width: min(320px, calc(100vw - 32px));
      padding: 12px;
      border: 1px solid rgba(255, 255, 255, 0.12);
      border-radius: 12px;
      background: rgba(15, 23, 42, 0.78);
      color: #e2e8f0;
      backdrop-filter: blur(16px);
      -webkit-backdrop-filter: blur(16px);
      box-shadow: 0 20px 48px rgba(2, 6, 23, 0.34);
    }}
    .map-overlay-controls[data-open="true"] .map-overlay-panel {{
      display: block;
    }}
    .map-overlay-panel__section {{
      display: grid;
      gap: 8px;
    }}
    .map-overlay-panel__row {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      font-size: 12px;
      color: #cbd5e1;
    }}
    .map-overlay-panel__row strong {{
      color: #f8fafc;
      font-weight: 600;
      text-align: right;
    }}
    .mapboxgl-popup {{
      max-width: 380px;
    }}
    .mapboxgl-ctrl-logo {{
      display: none !important;
    }}
    .mapboxgl-ctrl-attrib a {{
    display: none !important;
    }}
    .mapbox-logo {{
      display: none !important;
    }}
    .mapbox-improve-map {{
      display: none !important;
    }}
    .mapboxgl-ctrl-compass{{
      display: none !important;
    }}
    .mapboxgl-popup-content {{
      padding: 0;
      border-radius: 18px;
      overflow: hidden;
      box-shadow: 0 20px 48px rgba(2, 6, 23, 0.42);
      font-size: 12px;
      line-height: 1.45;
      attributionControl: false, 
      background: #0f172a;
      color: #e2e8f0;
    }}
    .hover-popup .mapboxgl-popup-content {{
      padding: 8px 10px;
      border-radius: 8px;
      box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12);
      background: #ffffff;
      color: #0f172a;
    }}
    .mapboxgl-popup-close-button {{
      font-size: 16px;
      padding: 8px 10px;
      color: #cbd5e1;
      z-index: 2;
    }}
    .mapboxgl-popup-close-button:hover {{
      background: transparent;
      color: #ffffff;
    }}
    .poi-marker {{
      width: 26px;
      height: 26px;
      display: flex;
      align-items: center;
      justify-content: center;
      border-radius: 8px;
      border: 2px solid rgba(255, 255, 255, 0.95);
      box-shadow: 0 10px 24px rgba(2, 6, 23, 0.35);
      color: #ffffff;
      font-size: 12px;
    }}
    .station-card {{
      background:
        radial-gradient(circle at top, rgba(59, 130, 246, 0.18), transparent 34%),
        linear-gradient(180deg, rgba(15, 23, 42, 0.98), rgba(2, 6, 23, 0.98));
      min-width: 320px;
      max-height: 440px;
      overflow-y: auto;
      overscroll-behavior: contain;
      scrollbar-width: thin;
      scrollbar-color: rgba(148, 163, 184, 0.55) transparent;
    }}
    .station-card::-webkit-scrollbar {{
      width: 8px;
    }}
    .station-card::-webkit-scrollbar-track {{
      background: transparent;
    }}
    .station-card::-webkit-scrollbar-thumb {{
      background: rgba(148, 163, 184, 0.4);
      border-radius: 999px;
    }}
    .station-card::-webkit-scrollbar-thumb:hover {{
      background: rgba(148, 163, 184, 0.6);
    }}
    .station-card__hero {{
      padding: 22px 22px 14px;
      text-align: center;
      border-bottom: 1px solid rgba(148, 163, 184, 0.14);
    }}
    .station-card__eyebrow {{
      font-size: 11px;
      letter-spacing: 0.16em;
      text-transform: uppercase;
      color: #94a3b8;
      margin-bottom: 8px;
    }}
    .station-card__title {{
      font-size: 22px;
      font-weight: 700;
      line-height: 1.15;
      color: #f8fafc;
    }}
    .station-card__subtitle {{
      margin-top: 8px;
      font-size: 12px;
      color: #94a3b8;
    }}
    .station-metrics {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
      padding: 16px 18px 6px;
    }}
    .station-metric {{
      padding: 12px 10px;
      border-radius: 14px;
      background: rgba(15, 23, 42, 0.7);
      border: 1px solid rgba(148, 163, 184, 0.12);
      text-align: center;
    }}
    .station-metric__value {{
      font-size: 18px;
      font-weight: 700;
      color: #f8fafc;
    }}
    .station-metric__label {{
      margin-top: 4px;
      font-size: 11px;
      color: #94a3b8;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}
    .station-section {{
      padding: 14px 18px 0;
    }}
    .station-section:last-child {{
      padding-bottom: 18px;
    }}
    .station-section__title {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 10px;
      font-size: 12px;
      font-weight: 700;
      color: #cbd5e1;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}
    .station-section__hint {{
      color: #60a5fa;
      font-weight: 600;
    }}
    .station-pill-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }}
    .station-pill {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 30px;
      padding: 0 12px;
      border-radius: 999px;
      border: 1px solid color-mix(in srgb, var(--pill-color) 55%, white 12%);
      background: color-mix(in srgb, var(--pill-color) 18%, transparent);
      color: #f8fafc;
      font-size: 12px;
      font-weight: 600;
    }}
    .station-pill--mode {{
      min-width: 72px;
    }}
    .metro-badge {{
      width: 38px;
      height: 38px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      flex: 0 0 38px;
      border-radius: 999px;
      box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.22);
      font-size: 13px;
      font-weight: 800;
      line-height: 1;
      letter-spacing: -0.02em;
    }}
    .metro-badge__bis {{
      font-size: 0.58em;
      margin-left: 1px;
      align-self: flex-start;
      padding-top: 9px;
      letter-spacing: 0;
    }}
    .station-line-group + .station-line-group {{
      margin-top: 10px;
    }}
    .station-line-group__title {{
      margin-bottom: 7px;
      color: #94a3b8;
      font-size: 12px;
      font-weight: 600;
    }}
    .station-empty {{
      padding: 12px 14px;
      border-radius: 12px;
      background: rgba(15, 23, 42, 0.55);
      border: 1px dashed rgba(148, 163, 184, 0.18);
      color: #94a3b8;
    }}
    .poi-card-list {{
      display: grid;
      gap: 10px;
    }}
    .poi-card {{
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 12px;
      border-radius: 14px;
      background: rgba(15, 23, 42, 0.68);
      border: 1px solid rgba(148, 163, 184, 0.12);
    }}
    .poi-card__icon {{
      width: 38px;
      height: 38px;
      flex: 0 0 38px;
      display: flex;
      align-items: center;
      justify-content: center;
      border-radius: 12px;
      color: #ffffff;
      box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.12);
    }}
    .poi-card__title {{
      font-size: 14px;
      font-weight: 700;
      color: #f8fafc;
    }}
    .poi-card__meta {{
      margin-top: 3px;
      font-size: 12px;
      color: #94a3b8;
    }}
  </style>
</head>
<body>
  <div id="map"></div>
  {overlay_controls_block}
  <script src="https://api.mapbox.com/mapbox-gl-js/v3.4.0/mapbox-gl.js"></script>
  <script>
    const payload = {payload_json};
    mapboxgl.accessToken = payload.token;
    const overlayRoot = document.getElementById('map-overlay-controls');
    const overlayToggle = document.getElementById('map-overlay-controls-toggle');

    if (overlayRoot && overlayToggle) {{
      function setOverlayOpen(isOpen) {{
        overlayRoot.dataset.open = isOpen ? 'true' : 'false';
        overlayToggle.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
      }}

      overlayToggle.addEventListener('click', (event) => {{
        event.stopPropagation();
        setOverlayOpen(overlayRoot.dataset.open !== 'true');
      }});

      document.addEventListener('click', (event) => {{
        if (!overlayRoot.contains(event.target)) {{
          setOverlayOpen(false);
        }}
      }});
    }}

    const map = new mapboxgl.Map({{
      container: 'map',
      style: payload.basemap_style,
      center: [payload.center.lon, payload.center.lat],
      zoom: payload.zoom,
      pitch: payload.pitch,
      bearing: payload.bearing,
      antialias: true,
      attributionControl: true,
      renderWorldCopies: Boolean(payload.render_world_copies)
    }});

    let hoverPopup = null;
    let clickPopup = null;
    let poiMarkers = [];

    function clearPoiMarkers() {{
      poiMarkers.forEach((marker) => marker.remove());
      poiMarkers = [];
    }}

    function escapeHtml(value) {{
      return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    }}

    function buildLightHoverHtml(properties) {{
      return `<b>${{escapeHtml(properties.stop_name || properties.stop_id || 'Stop')}}</b>`;
    }}

    function buildLightClickHtml(properties) {{
      const stopName = escapeHtml(properties.stop_name || properties.stop_id || 'Stop');
      const stopId = escapeHtml(properties.stop_id || '');
      const modeName = escapeHtml((properties.visible_mode || 'bus').toString().replace(/^./, (ch) => ch.toUpperCase()));
      const connections = escapeHtml(String(properties.connections ?? 0));
      return `
        <div class="station-card">
          <div class="station-card__hero">
            <div class="station-card__eyebrow">Bus render graph</div>
            <div class="station-card__title">${{stopName}}</div>
            <div class="station-card__subtitle">Stop ID ${{stopId}}</div>
          </div>
          <div class="station-metrics">
            <div class="station-metric">
              <div class="station-metric__value">${{connections}}</div>
              <div class="station-metric__label">Connections</div>
            </div>
            <div class="station-metric">
              <div class="station-metric__value">${{modeName}}</div>
              <div class="station-metric__label">Mode</div>
            </div>
            <div class="station-metric">
              <div class="station-metric__value">Render</div>
              <div class="station-metric__label">Source</div>
            </div>
          </div>
          <div class="station-section">
            <div class="station-section__title">Info</div>
            <div class="station-empty">This bus node is rendered from the compressed render graph for performance.</div>
          </div>
        </div>
      `;
    }}

    function ensurePopupRemoved(popupRef) {{
      if (popupRef) {{
        popupRef.remove();
      }}
      return null;
    }}

    function setClickedPois(pois) {{
      clearPoiMarkers();
      (pois || []).forEach((poi) => {{
        const el = document.createElement('div');
        el.className = 'poi-marker';
        el.style.background = poi.color || '#334155';
        el.title = `${{poi.name || 'POI'}} (${{Math.round(Number(poi.distance_m || 0))}} m)`;
        el.innerHTML = `<i class="${{poi.icon_class || 'fa-solid fa-location-dot'}}" aria-hidden="true"></i>`;
        poiMarkers.push(
          new mapboxgl.Marker({{ element: el, anchor: 'center' }})
            .setLngLat([poi.lon, poi.lat])
            .addTo(map)
        );
      }});
    }}

    map.on('load', () => {{
      if (payload.paris_mask_feature) {{
        map.addSource('paris-mask', {{ type: 'geojson', data: payload.paris_mask_feature }});
        map.addLayer({{
          id: 'paris-mask-fill',
          type: 'fill',
          source: 'paris-mask',
          paint: {{
            'fill-color': payload.paris_mask_fill_color || '#020617',
            'fill-opacity': Number(payload.paris_mask_fill_opacity ?? 0.9)
          }}
        }});
      }}
      if (payload.paris_max_bounds) {{
        map.setMaxBounds(payload.paris_max_bounds);
      }}

      const firstLabelLayerId = (() => {{
        const layers = map.getStyle().layers || [];
        const labelLayer = layers.find((layer) => layer.type === 'symbol' && layer.layout && layer.layout['text-field']);
        return labelLayer ? labelLayer.id : null;
      }})();

      if (payload.show_3d_buildings && map.getStyle().sources && map.getStyle().sources.composite) {{
        map.addLayer(
          {{
            id: '3d-buildings',
            source: 'composite',
            'source-layer': 'building',
            filter: ['==', ['get', 'extrude'], 'true'],
            type: 'fill-extrusion',
            minzoom: 14,
            paint: {{
              'fill-extrusion-color': [
                'interpolate',
                ['linear'],
                ['zoom'],
                14,
                '#1f2937',
                16,
                '#334155'
              ],
              'fill-extrusion-height': [
                'interpolate',
                ['linear'],
                ['zoom'],
                14,
                0,
                14.4,
                ['coalesce', ['get', 'height'], 18]
              ],
              'fill-extrusion-base': [
                'interpolate',
                ['linear'],
                ['zoom'],
                14,
                0,
                14.4,
                ['coalesce', ['get', 'min_height'], 0]
              ],
              'fill-extrusion-opacity': 0.72
            }}
          }},
          firstLabelLayerId
        );
      }}

      map.addSource('network-lines', {{ type: 'geojson', data: payload.network }});
      map.addSource('path-lines', {{ type: 'geojson', data: payload.path }});
      map.addSource('stations', {{ type: 'geojson', data: payload.stations }});
      map.addSource('transfer-lines', {{ type: 'geojson', data: payload.transfers }});

      map.addLayer({{
        id: 'network-lines',
        type: 'line',
        source: 'network-lines',
        paint: {{
          'line-color': ['get', 'color'],
          'line-width': ['get', 'width'],
          'line-opacity': ['get', 'opacity']
        }}
      }});

      map.addLayer({{
        id: 'transfer-lines',
        type: 'line',
        source: 'transfer-lines',
        paint: {{
          'line-color': ['get', 'color'],
          'line-width': ['get', 'width'],
          'line-opacity': ['get', 'opacity']
        }}
      }});

      map.addLayer({{
        id: 'path-lines',
        type: 'line',
        source: 'path-lines',
        paint: {{
          'line-color': ['get', 'color'],
          'line-width': ['get', 'width'],
          'line-opacity': ['get', 'opacity']
        }}
      }});

      map.addLayer({{
        id: 'stations',
        type: 'circle',
        source: 'stations',
        paint: {{
          'circle-color': ['get', 'color'],
          'circle-radius': ['get', 'radius'],
          'circle-opacity': 0.8,
          'circle-stroke-width': 1,
          'circle-stroke-color': '#ffffff'
        }}
      }});

      map.on('mouseenter', 'stations', () => {{
        map.getCanvas().style.cursor = 'pointer';
      }});

      map.on('mouseleave', 'stations', () => {{
        map.getCanvas().style.cursor = '';
        hoverPopup = ensurePopupRemoved(hoverPopup);
      }});

      map.on('mousemove', 'stations', (event) => {{
        const feature = event.features && event.features[0];
        if (!feature) {{
          return;
        }}
        const coordinates = [feature.geometry.coordinates[0], feature.geometry.coordinates[1]];
        const hoverHtml = feature.properties.hover_html || buildLightHoverHtml(feature.properties || {{}});
        hoverPopup = ensurePopupRemoved(hoverPopup);
        hoverPopup = new mapboxgl.Popup({{
          closeButton: false,
          closeOnClick: false,
          offset: 12,
          className: 'hover-popup'
        }})
          .setLngLat(coordinates)
          .setHTML(hoverHtml)
          .addTo(map);
      }});

      map.on('click', 'stations', (event) => {{
        const feature = event.features && event.features[0];
        if (!feature) {{
          return;
        }}
        const coordinates = [feature.geometry.coordinates[0], feature.geometry.coordinates[1]];
        const clickHtml = feature.properties.click_html || buildLightClickHtml(feature.properties || {{}});
        let nearbyPois = [];
        try {{
          nearbyPois = JSON.parse(feature.properties.nearby_pois_json || '[]');
        }} catch (error) {{
          nearbyPois = [];
        }}
        setClickedPois(nearbyPois);
        clickPopup = ensurePopupRemoved(clickPopup);
        clickPopup = new mapboxgl.Popup({{
          closeButton: true,
          closeOnClick: false,
          offset: 14,
          maxWidth: '340px'
        }})
          .setLngLat(coordinates)
          .setHTML(clickHtml)
          .addTo(map);
        clickPopup.on('close', () => {{
          setClickedPois([]);
        }});
      }});

      map.on('click', (event) => {{
        const features = map.queryRenderedFeatures(event.point, {{ layers: ['stations'] }});
        if (!features.length && clickPopup) {{
          clickPopup = ensurePopupRemoved(clickPopup);
          setClickedPois([]);
        }}
      }});
    }});
  </script>
</body>
</html>"""
    return html, path_debug