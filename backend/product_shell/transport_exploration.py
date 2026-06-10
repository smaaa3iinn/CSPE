"""Deterministic nearby stops / POI / area exploration around a resolved transit center."""

from __future__ import annotations

import re
from typing import Any, Literal

from src.core.graph_loader import _haversine_m
from src.core.queries import _merge_mode_lines_union
from src.core.poi_index import LocalPOILookup
from src.viz.plot_mapbox import FOOD_POI_TYPES, TRANSPORT_POI_TYPES

from backend.product_shell import transport_engine as te
from backend.product_shell.services import agent_store
from backend.product_shell.services.agent_tools import resolve_stop_query

GraphMode = Literal["all", "metro", "rail", "tram", "bus", "other"]

DEFAULT_POI_RADIUS_M = 500
DEFAULT_STOP_RADIUS_M = 1000
DEFAULT_RADIUS_M = DEFAULT_POI_RADIUS_M
MIN_RADIUS_M = 50
MAX_RADIUS_M = 3000
DEFAULT_STOP_LIMIT = 20
MAX_STOP_LIMIT = 50
DEFAULT_POI_LIMIT = 30
MAX_POI_LIMIT = 60

VALID_MODES = frozenset({"all", "metro", "rail", "tram", "bus", "other"})
VALID_POI_CATEGORIES = frozenset(
    {
        "restaurant",
        "cafe",
        "school",
        "hospital",
        "museum",
        "park",
        "shop",
        "tourism",
        "transport",
        "all",
    }
)

_DEICTIC_QUERY = re.compile(
    r"^\s*(this station|this stop|near here|around here|around this station|"
    r"around this stop|near this station|near this stop|here|this)\s*$",
    re.I,
)

_POI_CATEGORY_SPECS: dict[str, list[tuple[str | None, str | None]]] = {
    "restaurant": [("amenity", "restaurant")],
    "cafe": [("amenity", "cafe")],
    "school": [("amenity", "school"), ("amenity", "university"), ("amenity", "college")],
    "hospital": [("amenity", "hospital"), ("amenity", "clinic")],
    "museum": [("tourism", "museum"), ("tourism", "gallery")],
    "park": [("leisure", "park"), ("leisure", "garden"), ("leisure", "playground")],
    "shop": [("shop", None)],
    "tourism": [("tourism", None)],
    "transport": [(None, None)],  # filtered by type/family below
}


def clamp_radius(radius_m: int | float | None, *, default: int | None = None) -> int:
    fallback = default if default is not None else DEFAULT_POI_RADIUS_M
    try:
        value = int(radius_m if radius_m is not None else fallback)
    except (TypeError, ValueError):
        value = fallback
    return max(MIN_RADIUS_M, min(MAX_RADIUS_M, value))


def default_exploration_radius_m(*, include_stops: bool, include_pois: bool) -> int:
    """Default search radius: 1000 m when stops are included, else 500 m for POI-only."""
    if include_stops:
        return DEFAULT_STOP_RADIUS_M
    return DEFAULT_POI_RADIUS_M


def clamp_limit(value: int | None, *, default: int, maximum: int) -> int:
    try:
        n = int(value if value is not None else default)
    except (TypeError, ValueError):
        n = default
    return max(1, min(maximum, n))


def normalize_mode(mode: str | None, *, default: GraphMode = "all") -> GraphMode:
    m = str(mode or default).strip().lower()
    return m if m in VALID_MODES else default  # type: ignore[return-value]


def normalize_poi_categories(categories: list[str] | None) -> list[str]:
    if not categories:
        return ["all"]
    out: list[str] = []
    for raw in categories:
        c = str(raw or "").strip().lower()
        if not c:
            continue
        if c not in VALID_POI_CATEGORIES:
            continue
        if c not in out:
            out.append(c)
    return out or ["all"]


def normalize_transport_modes(modes: list[str] | None) -> list[str]:
    if not modes:
        return ["all"]
    out: list[str] = []
    for raw in modes:
        m = str(raw or "").strip().lower()
        if m == "all":
            return ["all"]
        if m in VALID_MODES and m != "all" and m not in out:
            out.append(m)
    return out or ["all"]


def is_deictic_query(query: str) -> bool:
    return bool(_DEICTIC_QUERY.match((query or "").strip()))


def name_match_score(query: str, candidate: str) -> float:
    """Simple fuzzy score for matching a user place name to a local POI/stop label."""
    q = " ".join(str(query or "").lower().split())
    c = " ".join(str(candidate or "").lower().split())
    if not q or not c:
        return 0.0
    if q == c:
        return 1.0
    if q in c or c in q:
        return 0.88
    q_tokens = set(q.split())
    c_tokens = set(c.split())
    if not q_tokens:
        return 0.0
    overlap = len(q_tokens & c_tokens) / len(q_tokens)
    if overlap >= 0.66:
        return 0.72 + 0.15 * overlap
    return overlap * 0.5


NAME_LOOKUP_POI_LIMIT = 200
NAME_LOOKUP_MIN_SCORE = 0.45


def _exact_match_threshold(query: str) -> float:
    """Multi-word brand names (e.g. Hugo Boss) tolerate slightly weaker token overlap."""
    tokens = [t for t in str(query or "").split() if t]
    return 0.5 if len(tokens) >= 2 else 0.55


def _rank_pois_by_name(
    query: str,
    rows: list[dict[str, Any]],
    *,
    min_score: float = NAME_LOOKUP_MIN_SCORE,
) -> list[tuple[float, dict[str, Any]]]:
    ranked: list[tuple[float, dict[str, Any]]] = []
    for row in rows:
        score = name_match_score(query, str(row.get("name") or row.get("type") or ""))
        if score >= min_score:
            ranked.append((score, row))
    ranked.sort(key=lambda item: (-item[0], float(item[1].get("distance_m") or 0)))
    return ranked


def _radii_for_name_lookup(snap: dict[str, Any], *, default_radius_m: int) -> list[int]:
    radii: list[int] = []
    snap_radius = snap.get("radius_m")
    if snap_radius is not None:
        radii.append(clamp_radius(snap_radius))
    for radius in (default_radius_m, 1500, 2500, MAX_RADIUS_M):
        clamped = clamp_radius(radius)
        if clamped not in radii:
            radii.append(clamped)
    return radii


def _center_for_poi_lookup(
    snap_center: dict[str, Any] | None,
    near_query: str | None,
    *,
    agent_context: dict[str, Any] | None,
    mode: GraphMode,
    use_lcc: bool,
    station_first: bool,
) -> dict[str, Any]:
    """Prefer exploration snapshot coordinates; fall back to stop/station resolution."""
    if isinstance(snap_center, dict):
        try:
            lat = float(snap_center["lat"])
            lon = float(snap_center["lon"])
        except (KeyError, TypeError, ValueError):
            pass
        else:
            label = str(
                snap_center.get("label")
                or snap_center.get("station_name")
                or snap_center.get("stop_name")
                or near_query
                or ""
            ).strip()
            return {
                "status": "exact",
                "center": {
                    "lat": lat,
                    "lon": lon,
                    "label": label or "explored area",
                    "station_id": snap_center.get("station_id"),
                    "station_name": snap_center.get("station_name"),
                    "stop_id": snap_center.get("stop_id"),
                    "stop_name": snap_center.get("stop_name"),
                },
            }
    return resolve_exploration_center(
        (near_query or "").strip()
        or (str(snap_center.get("label") or "") if isinstance(snap_center, dict) else "")
        or "",
        agent_context=agent_context,
        mode=mode,
        use_lcc=use_lcc,
        station_first=station_first,
    )


def resolve_poi_by_name(
    name: str,
    *,
    near_query: str | None = None,
    agent_context: dict[str, Any] | None = None,
    radius_m: int = 900,
    mode: GraphMode = "metro",
    use_lcc: bool = False,
    station_first: bool = True,
) -> dict[str, Any]:
    """Resolve one POI by name using exploration snapshot first, then local index near a center."""
    q = (name or "").strip()
    if len(q) < 2:
        return {"status": "error", "error": "POI name too short", "query": q}

    snap = _current_exploration_snapshot()
    snap_center = snap.get("center") if isinstance(snap.get("center"), dict) else None
    best_snap: dict[str, Any] | None = None
    best_snap_score = 0.0
    for row in snap.get("nearby_pois") or []:
        if not isinstance(row, dict):
            continue
        score = name_match_score(q, str(row.get("name") or row.get("type") or ""))
        if score > best_snap_score:
            best_snap_score = score
            best_snap = row
    snap_threshold = _exact_match_threshold(q)
    if best_snap is not None and best_snap_score >= snap_threshold:
        return {
            "status": "exact",
            "query": q,
            "poi": best_snap,
            "center": snap_center,
            "match_score": best_snap_score,
            "source": "exploration_snapshot",
        }

    lookup, err = _poi_lookup_or_error()
    if lookup is None:
        out = dict(err or {})
        out["status"] = "error"
        out["query"] = q
        return out

    center_res = _center_for_poi_lookup(
        snap_center,
        near_query,
        agent_context=agent_context,
        mode=mode,
        use_lcc=use_lcc,
        station_first=station_first,
    )
    if center_res.get("status") != "exact":
        return {
            "status": center_res.get("status") or "none",
            "query": q,
            "near_query": near_query,
            "error": center_res.get("error") or "Could not resolve a nearby center for POI lookup",
            "closest_matches": center_res.get("closest_matches") or [],
        }

    center = center_res["center"]
    threshold = _exact_match_threshold(q)
    best_score = 0.0
    best_row: dict[str, Any] | None = None
    ambiguous_candidates: list[dict[str, Any]] = []
    for search_radius in _radii_for_name_lookup(snap, default_radius_m=radius_m):
        rows = _nearby_pois_at_center(
            center,
            lookup,
            radius_m=search_radius,
            limit=NAME_LOOKUP_POI_LIMIT,
            categories=["all"],
        )
        ranked = _rank_pois_by_name(q, rows)
        if ranked and ranked[0][0] > best_score:
            best_score = ranked[0][0]
            best_row = ranked[0][1]
            ambiguous_candidates = [row for _, row in ranked[:5]]
        if best_score >= threshold:
            break

    if best_row is not None and best_score >= threshold:
        return {
            "status": "exact",
            "query": q,
            "poi": best_row,
            "center": center,
            "match_score": best_score,
            "source": "poi_index",
        }
    if ambiguous_candidates:
        return {
            "status": "ambiguous",
            "query": q,
            "center": center,
            "candidates": ambiguous_candidates,
        }
    area_label = center.get("label") or near_query or "that area"
    return {
        "status": "inferred",
        "query": q,
        "center": center,
        "near_query": near_query,
        "error": f"No local POI matching {q!r} near {area_label}; web lookup will use area context.",
    }


def query_from_agent_context(context: dict[str, Any] | None) -> str | None:
    if not isinstance(context, dict):
        return None
    world = context.get("world") if "world" in context else context
    if not isinstance(world, dict):
        return None
    transport = world.get("transport")
    if not isinstance(transport, dict):
        return None

    sel = transport.get("selected_station")
    if isinstance(sel, dict):
        sid = (sel.get("station_id") or "").strip()
        label = (sel.get("station_name") or sel.get("label") or "").strip()
        if sid:
            return sid
        if label:
            return label

    last = transport.get("last_exploration")
    if isinstance(last, dict):
        center = last.get("center")
        if isinstance(center, dict):
            for key in ("query", "station_name", "stop_name", "label"):
                val = (center.get(key) or "").strip()
                if val:
                    return val
    return None


def resolve_exploration_center(
    query: str,
    *,
    agent_context: dict[str, Any] | None = None,
    mode: GraphMode = "metro",
    use_lcc: bool = False,
    station_first: bool = True,
    limit: int = 15,
) -> dict[str, Any]:
    q = (query or "").strip()
    if not q or is_deictic_query(q):
        ctx_q = query_from_agent_context(agent_context)
        if not ctx_q:
            return {
                "status": "needs_context",
                "query": q,
                "error": "No selected station in context; ask the user which stop or station to use.",
            }
        q = ctx_q

    resolved = resolve_stop_query(
        q,
        mode=mode,
        use_lcc=use_lcc,
        station_first=station_first,
        limit=limit,
    )
    if resolved.get("status") == "exact":
        coords = center_coordinates_from_match(
            resolved.get("match") or {},
            mode=normalize_mode(resolved.get("mode") or mode),
            use_lcc=bool(resolved.get("use_lcc") if resolved.get("use_lcc") is not None else use_lcc),
        )
        if coords:
            return {
                "status": "exact",
                "query": q,
                "match": resolved.get("match"),
                "center": coords,
                "resolution": resolved,
            }
    return {
        "status": resolved.get("status") or "none",
        "query": q,
        "closest_matches": (resolved.get("matches") or [])[:limit],
        "resolution": resolved,
        "error": "Could not resolve a center stop or station for this query.",
    }


def center_coordinates_from_match(
    match: dict[str, Any],
    *,
    mode: GraphMode,
    use_lcc: bool,
) -> dict[str, Any] | None:
    station_id = (match.get("station_id") or "").strip() or None
    stop_id = (match.get("stop_id") or match.get("primary_stop_id") or "").strip() or None
    station_name = (match.get("station_name") or match.get("stop_name") or "").strip()
    stop_name = (match.get("stop_name") or station_name or "").strip()

    idx = te.station_layer_for(mode, use_lcc)
    G = te.graph_for(mode, use_lcc)

    if station_id and station_id in idx.station_centroid:
        lon, lat = idx.station_centroid[station_id]
        return {
            "station_id": station_id,
            "stop_id": stop_id,
            "station_name": station_name or idx.station_label.get(station_id, station_id),
            "stop_name": stop_name,
            "lat": lat,
            "lon": lon,
            "label": station_name or stop_name or station_id,
        }

    if stop_id and stop_id in G:
        ll = te._node_lon_lat(dict(G.nodes[stop_id]))
        if ll:
            lon, lat = ll
            sid = idx.stop_to_station.get(stop_id) if hasattr(idx, "stop_to_station") else None
            return {
                "station_id": sid,
                "stop_id": stop_id,
                "station_name": station_name,
                "stop_name": stop_name or te._node_label(dict(G.nodes[stop_id]), stop_id),
                "lat": lat,
                "lon": lon,
                "label": stop_name or station_name or stop_id,
            }

    if station_id:
        for member in idx.station_to_stops.get(station_id, []):
            if member not in G:
                continue
            ll = te._node_lon_lat(dict(G.nodes[member]))
            if ll:
                lon, lat = ll
                return {
                    "station_id": station_id,
                    "stop_id": member,
                    "station_name": station_name or idx.station_label.get(station_id, station_id),
                    "stop_name": stop_name,
                    "lat": lat,
                    "lon": lon,
                    "label": station_name or stop_name or station_id,
                }
    return None


def _station_modes(G: Any, idx: Any, station_id: str) -> list[str]:
    members = idx.station_to_stops.get(station_id, [])
    lines = _merge_mode_lines_union(G, members) or {}
    return sorted(m for m, vals in lines.items() if vals)


def _station_lines(G: Any, idx: Any, station_id: str) -> dict[str, list[str]]:
    members = idx.station_to_stops.get(station_id, [])
    return _merge_mode_lines_union(G, members) or {}


def _station_matches_mode_filter(modes: list[str], station_modes: list[str]) -> bool:
    if "all" in modes:
        return True
    return any(m in station_modes for m in modes)


def _format_nearby_stop_row(
    G: Any,
    idx: Any,
    station_id: str,
    *,
    center_lat: float,
    center_lon: float,
) -> dict[str, Any]:
    lon, lat = idx.station_centroid[station_id]
    lines = _station_lines(G, idx, station_id)
    modes = _station_modes(G, idx, station_id)
    members = idx.station_to_stops.get(station_id, [])
    primary = sorted(members)[0] if members else None
    flat_lines: list[str] = []
    for mode_key, vals in lines.items():
        for ln in (vals or [])[:6]:
            flat_lines.append(f"{mode_key}:{ln}" if mode_key else str(ln))
    return {
        "station_id": station_id,
        "stop_id": primary,
        "station_name": idx.station_label.get(station_id, station_id),
        "stop_name": idx.station_label.get(station_id, station_id),
        "lines": flat_lines[:24],
        "lines_by_mode": lines,
        "modes": modes,
        "distance_m": round(_haversine_m(center_lat, center_lon, lat, lon), 1),
        "coordinates": {"lat": lat, "lon": lon},
    }


def _nearby_stops_at_center(
    center: dict[str, Any],
    *,
    radius_m: int,
    limit: int,
    mode: GraphMode,
    use_lcc: bool,
    mode_filter: list[str] | None = None,
) -> tuple[list[dict[str, Any]], GraphMode, bool]:
    center_lat = float(center["lat"])
    center_lon = float(center["lon"])
    exclude_station = (center.get("station_id") or "").strip() or None
    search_mode = normalize_mode(mode, default="all")
    search_lcc = use_lcc
    filters = normalize_transport_modes(mode_filter or [mode])

    G = te.graph_for(search_mode, search_lcc)
    idx = te.station_layer_for(search_mode, search_lcc)

    rows: list[dict[str, Any]] = []
    for sid, (lon, lat) in idx.station_centroid.items():
        if exclude_station and sid == exclude_station:
            continue
        dist = _haversine_m(center_lat, center_lon, lat, lon)
        if dist > radius_m:
            continue
        station_modes = _station_modes(G, idx, sid)
        if not _station_matches_mode_filter(filters, station_modes):
            continue
        rows.append(_format_nearby_stop_row(G, idx, sid, center_lat=center_lat, center_lon=center_lon))

    rows.sort(key=lambda r: (r["distance_m"], r.get("station_name") or ""))
    return rows[:limit], search_mode, search_lcc


def nearby_stops(
    query: str,
    *,
    radius_m: int | None = None,
    limit: int = DEFAULT_STOP_LIMIT,
    mode: GraphMode = "all",
    use_lcc: bool = False,
    station_first: bool = True,
    agent_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    radius_m = clamp_radius(radius_m, default=DEFAULT_STOP_RADIUS_M)
    limit = clamp_limit(limit, default=DEFAULT_STOP_LIMIT, maximum=MAX_STOP_LIMIT)
    mode = normalize_mode(mode, default="all")

    center_res = resolve_exploration_center(
        query,
        agent_context=agent_context,
        mode=mode if mode != "all" else "metro",
        use_lcc=use_lcc,
        station_first=station_first,
    )
    if center_res.get("status") == "needs_context":
        return {
            "ok": False,
            "center_resolved": False,
            "query": query,
            "radius_m": radius_m,
            "error": center_res.get("error"),
            "needs_clarification": True,
            "nearby_stops": [],
            "count": 0,
        }
    if center_res.get("status") != "exact":
        return {
            "ok": False,
            "center_resolved": False,
            "query": center_res.get("query") or query,
            "radius_m": radius_m,
            "closest_matches": center_res.get("closest_matches") or [],
            "resolution": center_res.get("resolution"),
            "error": center_res.get("error") or "Center not resolved",
            "nearby_stops": [],
            "count": 0,
        }

    center = center_res["center"]
    resolution = center_res.get("resolution") or {}
    search_mode = normalize_mode(resolution.get("mode") or mode, default=mode)
    search_lcc = bool(resolution.get("use_lcc") if resolution.get("use_lcc") is not None else use_lcc)
    rows, eff_mode, eff_lcc = _nearby_stops_at_center(
        center,
        radius_m=radius_m,
        limit=limit,
        mode=search_mode,
        use_lcc=search_lcc,
        mode_filter=[mode],
    )

    payload = {
        "ok": True,
        "center_resolved": True,
        "query": center_res.get("query") or query,
        "center": center,
        "radius_m": radius_m,
        "mode": eff_mode,
        "use_lcc": eff_lcc,
        "nearby_stops": rows,
        "count": len(rows),
    }
    _store_exploration_snapshot(payload, include_stops=True, include_pois=False)
    return _attach_summary(payload, kind="stops")


def _poi_lookup_or_error() -> tuple[LocalPOILookup | None, dict[str, Any] | None]:
    lookup = te._poi_lookup()
    if lookup is None:
        return None, {
            "ok": False,
            "error": "poi_index_unavailable",
            "message": (
                "POI index is not available (missing data/normalized/poi/poi.parquet). "
                "No POI data was invented."
            ),
            "pois": [],
            "count": 0,
        }
    return lookup, None


def _poi_matches_user_categories(row: dict[str, Any], categories: list[str]) -> bool:
    if "all" in categories:
        return True
    ck = str(row.get("category") or row.get("category_key") or "").strip().lower()
    cv = str(row.get("type") or row.get("category_value") or "").strip().lower()
    family = str(row.get("family") or "").strip().lower()

    for cat in categories:
        specs = _POI_CATEGORY_SPECS.get(cat, [])
        if cat == "transport":
            if family == "transport" or cv in TRANSPORT_POI_TYPES:
                return True
            continue
        for spec_key, spec_val in specs:
            if spec_key is None:
                continue
            if ck != spec_key:
                continue
            if spec_val is None or cv == spec_val:
                return True
        if cat == "restaurant" and cv in FOOD_POI_TYPES:
            return True
    return False


def _nearby_pois_at_center(
    center: dict[str, Any],
    lookup: LocalPOILookup,
    *,
    radius_m: int,
    limit: int,
    categories: list[str],
) -> list[dict[str, Any]]:
    raw = lookup.query(
        float(center["lat"]),
        float(center["lon"]),
        float(radius_m),
        limit=limit * 4 if "all" not in categories else limit,
    )
    rows: list[dict[str, Any]] = []
    for row in raw:
        if not _poi_matches_user_categories(row, categories):
            continue
        rows.append(
            {
                "name": row.get("name"),
                "category": row.get("category"),
                "type": row.get("type"),
                "family": row.get("family"),
                "distance_m": round(float(row.get("distance_m") or 0), 1),
                "coordinates": {"lat": row.get("lat"), "lon": row.get("lon")},
                "source": "poi.parquet",
            }
        )
        if len(rows) >= limit:
            break
    return rows


def nearby_pois(
    query: str,
    *,
    radius_m: int | None = None,
    limit: int = DEFAULT_POI_LIMIT,
    categories: list[str] | None = None,
    agent_context: dict[str, Any] | None = None,
    mode: GraphMode = "metro",
    use_lcc: bool = False,
    station_first: bool = True,
) -> dict[str, Any]:
    radius_m = clamp_radius(radius_m, default=DEFAULT_POI_RADIUS_M)
    limit = clamp_limit(limit, default=DEFAULT_POI_LIMIT, maximum=MAX_POI_LIMIT)
    cats = normalize_poi_categories(categories)

    lookup, err = _poi_lookup_or_error()
    if lookup is None:
        out = dict(err or {})
        out["query"] = query
        out["radius_m"] = radius_m
        out["categories"] = cats
        return out

    center_res = resolve_exploration_center(
        query,
        agent_context=agent_context,
        mode=mode,
        use_lcc=use_lcc,
        station_first=station_first,
    )
    if center_res.get("status") == "needs_context":
        return {
            "ok": False,
            "center_resolved": False,
            "query": query,
            "radius_m": radius_m,
            "error": center_res.get("error"),
            "needs_clarification": True,
            "pois": [],
            "count": 0,
        }
    if center_res.get("status") != "exact":
        return {
            "ok": False,
            "center_resolved": False,
            "query": center_res.get("query") or query,
            "radius_m": radius_m,
            "categories": cats,
            "closest_matches": center_res.get("closest_matches") or [],
            "error": center_res.get("error") or "Center not resolved",
            "pois": [],
            "count": 0,
        }

    center = center_res["center"]
    rows = _nearby_pois_at_center(center, lookup, radius_m=radius_m, limit=limit, categories=cats)

    payload = {
        "ok": True,
        "center_resolved": True,
        "query": center_res.get("query") or query,
        "center": center,
        "radius_m": radius_m,
        "categories": cats,
        "pois": rows,
        "count": len(rows),
        "poi_index": lookup.stats.data_path,
    }
    _store_exploration_snapshot(payload, include_stops=False, include_pois=True)
    return _attach_summary(payload, kind="pois")


def explore_area(
    query: str,
    *,
    radius_m: int | None = None,
    include_stops: bool = True,
    include_pois: bool = True,
    poi_categories: list[str] | None = None,
    transport_modes: list[str] | None = None,
    limit_stops: int = 15,
    limit_pois: int = 20,
    agent_context: dict[str, Any] | None = None,
    mode: GraphMode = "metro",
    use_lcc: bool = False,
    station_first: bool = True,
) -> dict[str, Any]:
    if radius_m is None:
        radius_m = default_exploration_radius_m(include_stops=include_stops, include_pois=include_pois)
    radius_m = clamp_radius(radius_m)
    limit_stops = clamp_limit(limit_stops, default=15, maximum=MAX_STOP_LIMIT)
    limit_pois = clamp_limit(limit_pois, default=20, maximum=MAX_POI_LIMIT)
    cats = normalize_poi_categories(poi_categories)
    modes = normalize_transport_modes(transport_modes)

    center_res = resolve_exploration_center(
        query,
        agent_context=agent_context,
        mode=mode,
        use_lcc=use_lcc,
        station_first=station_first,
    )
    if center_res.get("status") == "needs_context":
        return {
            "ok": False,
            "center_resolved": False,
            "query": query,
            "radius_m": radius_m,
            "error": center_res.get("error"),
            "needs_clarification": True,
            "center": None,
            "nearby_stops": [],
            "nearby_pois": [],
            "counts": {"stops": 0, "pois": 0},
        }
    if center_res.get("status") != "exact":
        return {
            "ok": False,
            "center_resolved": False,
            "query": center_res.get("query") or query,
            "radius_m": radius_m,
            "closest_matches": center_res.get("closest_matches") or [],
            "error": center_res.get("error") or "Center not resolved",
            "center": None,
            "nearby_stops": [],
            "nearby_pois": [],
            "counts": {"stops": 0, "pois": 0},
        }

    center = center_res["center"]
    resolution = center_res.get("resolution") or {}
    search_mode = normalize_mode(resolution.get("mode") or mode, default=mode)
    search_lcc = bool(resolution.get("use_lcc") if resolution.get("use_lcc") is not None else use_lcc)
    # transport_modes=["all"] must not use the combined "all" graph for proximity search:
    # its station layer omits many metro hubs (e.g. République) and returns false empty results.
    stop_graph_mode: GraphMode = search_mode if modes == ["all"] else normalize_mode(modes[0], default=search_mode)

    stop_rows: list[dict[str, Any]] = []
    poi_rows: list[dict[str, Any]] = []
    poi_index_error: str | None = None

    if include_stops:
        stop_rows, _, _ = _nearby_stops_at_center(
            center,
            radius_m=radius_m,
            limit=limit_stops,
            mode=stop_graph_mode,
            use_lcc=search_lcc,
            mode_filter=modes,
        )
    if include_pois:
        lookup, err = _poi_lookup_or_error()
        if lookup is None:
            poi_index_error = (err or {}).get("message")
        else:
            poi_rows = _nearby_pois_at_center(
                center,
                lookup,
                radius_m=radius_m,
                limit=limit_pois,
                categories=cats,
            )

    payload = {
        "ok": True,
        "center_resolved": True,
        "query": center_res.get("query") or query,
        "center": center,
        "radius_m": radius_m,
        "mode": search_mode,
        "use_lcc": search_lcc,
        "transport_modes": modes,
        "poi_categories": cats,
        "nearby_stops": stop_rows,
        "nearby_pois": poi_rows,
        "counts": {"stops": len(stop_rows), "pois": len(poi_rows)},
        "poi_index_error": poi_index_error,
    }
    _store_exploration_snapshot(payload, include_stops=include_stops, include_pois=include_pois)
    return _attach_summary(payload, kind="explore")


def filter_visible_results(
    *,
    radius_m: int | None = None,
    modes: list[str] | None = None,
    poi_categories: list[str] | None = None,
    lines: list[str] | None = None,
    max_results: int = 50,
    include_stops: bool | None = None,
    include_pois: bool | None = None,
) -> dict[str, Any]:
    ctx = agent_store.get_context()
    transport = (ctx.get("world") or {}).get("transport") or {}
    snapshot = transport.get("last_exploration")
    if not isinstance(snapshot, dict):
        return {
            "ok": False,
            "error": "nothing_to_filter",
            "message": "No active exploration or search results in context to filter.",
            "nearby_stops": [],
            "nearby_pois": [],
            "count": 0,
        }

    stops = list(snapshot.get("nearby_stops") or [])
    pois = list(snapshot.get("nearby_pois") or [])
    if include_stops is False:
        stops = []
    if include_pois is False:
        pois = []
    if include_stops is True and not stops and snapshot.get("nearby_stops"):
        stops = list(snapshot.get("nearby_stops") or [])
    if include_pois is True and not pois and snapshot.get("nearby_pois"):
        pois = list(snapshot.get("nearby_pois") or [])

    eff_radius = clamp_radius(radius_m if radius_m is not None else snapshot.get("radius_m"))
    mode_filter = normalize_transport_modes(modes)
    cat_filter = normalize_poi_categories(poi_categories)
    line_filter = [str(x).strip().lower() for x in (lines or []) if str(x).strip()]
    max_n = clamp_limit(max_results, default=50, maximum=100)

    filtered_stops: list[dict[str, Any]] = []
    for row in stops:
        if float(row.get("distance_m") or 0) > eff_radius:
            continue
        row_modes = row.get("modes") or []
        if not _station_matches_mode_filter(mode_filter, list(row_modes)):
            continue
        if line_filter:
            flat = " ".join(str(x).lower() for x in (row.get("lines") or []))
            if not any(ln in flat for ln in line_filter):
                continue
        filtered_stops.append(row)

    filtered_pois: list[dict[str, Any]] = []
    for row in pois:
        if float(row.get("distance_m") or 0) > eff_radius:
            continue
        if not _poi_matches_user_categories(row, cat_filter):
            continue
        filtered_pois.append(row)

    filtered_stops = filtered_stops[:max_n]
    filtered_pois = filtered_pois[:max_n]

    if not filtered_stops and not filtered_pois and not stops and not pois:
        return {
            "ok": False,
            "error": "nothing_to_filter",
            "message": "No active exploration or search results in context to filter.",
            "nearby_stops": [],
            "nearby_pois": [],
            "count": 0,
        }

    payload = {
        "ok": True,
        "radius_m": eff_radius,
        "modes": mode_filter,
        "poi_categories": cat_filter,
        "lines": line_filter,
        "center": snapshot.get("center"),
        "nearby_stops": filtered_stops,
        "nearby_pois": filtered_pois,
        "counts": {"stops": len(filtered_stops), "pois": len(filtered_pois)},
        "count": len(filtered_stops) + len(filtered_pois),
    }
    _store_exploration_snapshot(payload, include_stops=bool(filtered_stops), include_pois=bool(filtered_pois))
    return _attach_summary(payload, kind="filter")


def _display_name(row: dict[str, Any], *, poi: bool = False) -> str:
    if poi:
        return str(row.get("name") or row.get("type") or "POI").strip()
    return str(row.get("station_name") or row.get("stop_name") or row.get("station_id") or row.get("stop_id") or "?").strip()


def format_name_list(names: list[str], *, max_names: int = 8) -> str:
    clean = [n for n in (x.strip() for x in names if x and str(x).strip()) if n]
    if not clean:
        return "(none)"
    if len(clean) <= max_names:
        return ", ".join(clean)
    extra = len(clean) - max_names
    return ", ".join(clean[:max_names]) + f", +{extra} more"


def center_label(payload: dict[str, Any]) -> str:
    center = payload.get("center") or {}
    return str(
        center.get("label")
        or center.get("station_name")
        or center.get("stop_name")
        or payload.get("query")
        or "area"
    ).strip()


def build_exploration_summary(payload: dict[str, Any], *, kind: str = "explore") -> str:
    """Human-readable summary with named stops/POIs for planner and assistant replies."""
    if not payload.get("ok"):
        return str(payload.get("error") or payload.get("message") or "Exploration failed")

    name = center_label(payload)
    radius = int(payload.get("radius_m") or DEFAULT_RADIUS_M)
    parts: list[str] = [f"Center: {name} ({radius}m radius)"]

    stops = payload.get("nearby_stops") or []
    if kind in ("stops", "explore", "filter") and stops:
        stop_names = [_display_name(s) for s in stops]
        parts.append(f"Nearby stops ({len(stops)}): {format_name_list(stop_names)}")

    pois = payload.get("nearby_pois") or payload.get("pois") or []
    if kind in ("pois", "explore", "filter") and pois:
        poi_names = [_display_name(p, poi=True) for p in pois]
        parts.append(f"Nearby POIs ({len(pois)}): {format_name_list(poi_names)}")

    if len(parts) == 1:
        counts = payload.get("counts") or {}
        parts.append(f"Found {counts.get('stops', 0)} stops and {counts.get('pois', 0)} POIs")
    return ". ".join(parts)


def exploration_overlay_from_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    if not payload.get("ok"):
        return None
    center = payload.get("center")
    if not isinstance(center, dict):
        return None
    return {
        "center": center,
        "radius_m": payload.get("radius_m"),
        "nearby_stops": payload.get("nearby_stops") or [],
        "nearby_pois": payload.get("nearby_pois") or payload.get("pois") or [],
        "counts": payload.get("counts"),
    }


def _attach_summary(payload: dict[str, Any], *, kind: str) -> dict[str, Any]:
    payload = dict(payload)
    payload["summary"] = build_exploration_summary(payload, kind=kind)
    return payload


def _current_exploration_snapshot() -> dict[str, Any]:
    ctx = agent_store.get_context()
    transport = (ctx.get("world") or {}).get("transport") or {}
    snap = transport.get("last_exploration")
    return snap if isinstance(snap, dict) else {}


def _store_exploration_snapshot(
    payload: dict[str, Any],
    *,
    include_stops: bool,
    include_pois: bool,
) -> None:
    prev = _current_exploration_snapshot()
    if include_stops:
        stops = list(payload.get("nearby_stops") or [])
    else:
        stops = list(prev.get("nearby_stops") or [])
    if include_pois:
        pois = list(payload.get("nearby_pois") or payload.get("pois") or [])
    else:
        pois = list(prev.get("nearby_pois") or [])

    patch: dict[str, Any] = {
        "last_exploration": {
            "query": payload.get("query"),
            "center": payload.get("center"),
            "radius_m": payload.get("radius_m"),
            "nearby_stops": stops,
            "nearby_pois": pois,
            "counts": {
                "stops": len(stops),
                "pois": len(pois),
            },
            "updated_at": agent_store.utc_iso(),
        }
    }
    center = payload.get("center")
    if isinstance(center, dict) and center.get("station_id"):
        patch["selected_station"] = {
            "station_id": center.get("station_id"),
            "station_name": center.get("station_name") or center.get("label"),
            "stop_id": center.get("stop_id"),
        }
    agent_store.patch_world_state({"transport": patch})
