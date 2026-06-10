"""Server-side agent tools: resolve stops, compute routes, sync UI — no browser required."""

from __future__ import annotations

import re
from typing import Any, Literal

from src.core.queries import normalize_text, _score_name_match
from backend.product_shell import transport_engine as te
from backend.product_shell.services import agent_store

GraphMode = Literal["all", "metro", "rail", "tram", "bus", "other"]
RoutingScope = Literal["stop", "station"]


def _pick_best_match(matches: list[dict[str, Any]], query: str = "") -> dict[str, Any] | None:
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]
    q = normalize_text(query)
    if not q:
        return matches[0]

    def rank(m: dict[str, Any]) -> tuple[int, int, str]:
        label = (m.get("station_name") or m.get("stop_name") or "").strip()
        nl = normalize_text(label)
        score = _score_name_match(nl, q)
        return (-score, len(nl), nl)

    return sorted(matches, key=rank)[0]


def resolve_stop_query(
    query: str,
    *,
    mode: GraphMode = "metro",
    use_lcc: bool = True,
    station_first: bool = True,
    limit: int = 15,
) -> dict[str, Any]:
    q = (query or "").strip()
    if not q:
        return {"status": "error", "error": "empty query", "matches": []}

    modes_to_try: list[GraphMode] = [mode]
    if mode != "all":
        modes_to_try.append("all")

    matches: list[dict[str, Any]] = []
    effective_mode: GraphMode = mode
    effective_use_lcc = use_lcc

    for search_mode in modes_to_try:
        lcc_candidates = [True, False] if use_lcc else [False]
        for lcc in lcc_candidates:
            matches = te.search_stops(
                q,
                limit=limit,
                mode=search_mode,
                use_lcc=lcc,
                station_first=station_first,
                fallback_lcc=False,
                mode_fallback=False,
            )
            if matches:
                effective_mode = search_mode
                effective_use_lcc = lcc
                break
        if matches:
            break

    best = _pick_best_match(matches, q)
    if best:
        return {
            "status": "exact",
            "query": q,
            "match": best,
            "matches": matches,
            "use_lcc": effective_use_lcc,
            "mode": effective_mode,
        }
    if matches:
        return {
            "status": "ambiguous",
            "query": q,
            "matches": matches[:8],
            "use_lcc": effective_use_lcc,
            "mode": effective_mode,
        }
    return {"status": "none", "query": q, "matches": [], "use_lcc": effective_use_lcc, "mode": mode}


def _endpoint_ids(
    resolved: dict[str, Any], *, routing_scope: RoutingScope
) -> tuple[str | None, str | None, str | None]:
    """Return (stop_id, station_id, label) from a resolve result."""
    if resolved.get("status") != "exact":
        return None, None, None
    m = resolved.get("match") or {}
    if routing_scope == "station":
        sid = (m.get("station_id") or "").strip() or None
        label = (m.get("station_name") or m.get("stop_name") or "").strip()
        return None, sid, label
    stop_id = (m.get("stop_id") or "").strip() or None
    label = (m.get("stop_name") or m.get("station_name") or "").strip()
    return stop_id, None, label


def compute_route_from_queries(
    from_query: str,
    to_query: str,
    *,
    mode: GraphMode = "metro",
    use_lcc: bool = True,
    routing_scope: RoutingScope = "station",
    station_first: bool = True,
    auto_pick: bool = True,
) -> dict[str, Any]:
    """Search both endpoints, resolve ambiguity, compute route server-side."""
    from_r = resolve_stop_query(
        from_query, mode=mode, use_lcc=use_lcc, station_first=station_first
    )
    to_r = resolve_stop_query(to_query, mode=mode, use_lcc=use_lcc, station_first=station_first)
    route_use_lcc = use_lcc
    route_mode: GraphMode = mode
    if from_r.get("use_lcc") is False or to_r.get("use_lcc") is False:
        route_use_lcc = False
    if from_r.get("mode") and from_r.get("mode") != mode:
        route_mode = from_r["mode"]
    elif to_r.get("mode") and to_r.get("mode") != mode:
        route_mode = to_r["mode"]
    if (
        from_r.get("use_lcc") != route_use_lcc
        or to_r.get("use_lcc") != route_use_lcc
        or from_r.get("mode") != route_mode
        or to_r.get("mode") != route_mode
    ):
        from_r = resolve_stop_query(
            from_query, mode=route_mode, use_lcc=route_use_lcc, station_first=station_first
        )
        to_r = resolve_stop_query(
            to_query, mode=route_mode, use_lcc=route_use_lcc, station_first=station_first
        )

    out: dict[str, Any] = {
        "ok": False,
        "from": from_r,
        "to": to_r,
        "routing_scope": routing_scope,
        "mode": route_mode,
        "use_lcc": route_use_lcc,
    }

    if from_r["status"] == "ambiguous" or to_r["status"] == "ambiguous":
        out["needs_user_choice"] = True
        out["error"] = {"message": "Ambiguous stop or station name", "details": []}
        if from_r["status"] == "ambiguous":
            out["error"]["details"].append({"endpoint": "from", "query": from_query, "candidates": from_r.get("matches")})
        if to_r["status"] == "ambiguous":
            out["error"]["details"].append({"endpoint": "to", "query": to_query, "candidates": to_r.get("matches")})
        agent_store.record_event("transport.route.ambiguous", out, source="agent_tools")
        return out

    if from_r["status"] != "exact" or to_r["status"] != "exact":
        out["error"] = {"message": "Could not resolve one or both endpoints", "details": [from_r, to_r]}
        agent_store.record_event("transport.route.not_found", out, source="agent_tools")
        return out

    fs, fsta, _ = _endpoint_ids(from_r, routing_scope=routing_scope)
    ts, tsta, _ = _endpoint_ids(to_r, routing_scope=routing_scope)

    if routing_scope == "station":
        if not fsta or not tsta:
            out["error"] = {"message": "Missing station IDs for station routing"}
            return out
        route = te.compute_route_stations(fsta, tsta, mode=route_mode, use_lcc=route_use_lcc)
    else:
        if not fs or not ts:
            out["error"] = {"message": "Missing stop IDs for stop routing"}
            return out
        route = te.compute_route(fs, ts, mode=route_mode, use_lcc=route_use_lcc)

    out["ok"] = bool(route.get("ok"))
    out["route"] = route
    out["from_query"] = from_query
    out["to_query"] = to_query

    if out["ok"]:
        agent_store.patch_world_state(
            {
                "transport": {
                    "from_query": from_query,
                    "to_query": to_query,
                    "path": route.get("path"),
                    "station_path": route.get("station_path"),
                    "station_names": route.get("station_names"),
                    "result": route.get("result"),
                    "mode": mode,
                    "use_lcc": use_lcc,
                    "routing_scope": routing_scope,
                }
            }
        )
        agent_store.record_event("transport.route.ok", {"from": from_query, "to": to_query, "result": route.get("result")}, source="agent_tools")
    else:
        agent_store.record_event("transport.route.failed", out, source="agent_tools")

    return out


def create_graph3d_for_route(
    route_payload: dict[str, Any],
    *,
    mode: GraphMode = "metro",
    use_lcc: bool = True,
    graph_viz_mode: Literal["stop", "station", "hybrid"] = "station",
    sync_client_id: str | None = None,
) -> dict[str, Any]:
    import json
    import uuid

    route = route_payload.get("route") or route_payload
    if not route or not route.get("ok"):
        return {"ok": False, "error": "No successful route to visualize"}
    client_id = (sync_client_id or uuid.uuid4().hex).strip()
    fingerprint = json.dumps(
        {
            "mode": mode,
            "use_lcc": use_lcc,
            "graph_viz": graph_viz_mode,
            "path_stop_ids": route.get("path") or [],
            "path_station_ids": route.get("station_path") or [],
            "selected_stop_id": None,
            "selected_station_id": None,
            "exploration_seq": 0,
        },
        sort_keys=True,
    )
    row = te.push_graph3d_sync(
        client_id=client_id,
        fingerprint=fingerprint,
        mode=mode,
        use_lcc=use_lcc,
        graph_viz_mode=graph_viz_mode,
        path_stop_ids=route.get("path"),
        path_station_ids=route.get("station_path"),
    )
    agent_store.record_event(
        "transport.graph3d.session",
        {
            "session_id": row.get("session_id"),
            "sync_client_id": client_id,
            "fingerprint": fingerprint,
        },
        source="agent_tools",
    )
    return {"ok": True, "sync_client_id": client_id, "fingerprint": fingerprint, **row}


def shell_commands_for_route(route_payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Build shell commands to sync Transport UI after server-side routing."""
    cmds: list[dict[str, Any]] = [{"kind": "set_mode", "mode": "transport"}]
    route = route_payload.get("route") or {}
    spec: dict[str, Any] = {
        "open_app_mode": "transport",
        "dock_tab": "route",
        "run": "none",
    }
    if route_payload.get("from_query"):
        spec["from_query"] = route_payload["from_query"]
    if route_payload.get("to_query"):
        spec["to_query"] = route_payload["to_query"]
    if route_payload.get("mode"):
        spec["graph_mode"] = route_payload["mode"]
    if "use_lcc" in route_payload:
        spec["use_lcc"] = route_payload["use_lcc"]
    if route_payload.get("routing_scope"):
        spec["routing_scope"] = route_payload["routing_scope"]
    cmds.append({"kind": "atlas_transport_action", "spec": spec})

    if route.get("ok"):
        rv: dict[str, Any] = {}
        if route.get("path"):
            rv["path_ids"] = route["path"]
        if route.get("station_path"):
            rv["station_path_ids"] = route["station_path"]
        if route.get("path_legs"):
            rv["route_legs"] = route["path_legs"]
        res = route.get("result") or {}
        meta_bits = []
        if res.get("time_s") is not None:
            meta_bits.append(f"{int(res['time_s'] // 60)} min")
        if res.get("transfers") is not None:
            meta_bits.append(f"{res['transfers']} transfers")
        if route.get("path_summary"):
            rv["route_meta"] = " · ".join(str(line) for line in route["path_summary"] if line)
        elif meta_bits:
            rv["route_meta"] = ", ".join(meta_bits)
        if rv:
            cmds.append({"kind": "transport_route_view", **rv})
    else:
        err = route_payload.get("error") or route.get("error") or {}
        msg = (
            err.get("message")
            if isinstance(err, dict)
            else str(err) if err else "Route failed"
        )
        cmds.append(
            {
                "kind": "transport_route_view",
                "clear_paths": True,
                "route_error": msg or "Route failed",
            }
        )
    return cmds


def shell_commands_for_exploration(exploration: dict[str, Any]) -> list[dict[str, Any]]:
    """Sync Transport UI after area / nearby exploration (center + named results on map)."""
    center = exploration.get("center") or {}
    label = (
        center.get("label")
        or center.get("station_name")
        or center.get("stop_name")
        or exploration.get("query")
        or ""
    )
    cmds: list[dict[str, Any]] = [{"kind": "set_mode", "mode": "transport"}]
    spec: dict[str, Any] = {
        "open_app_mode": "transport",
        "run": "exploration_map",
        "dock_tab": "search",
        "stop_lookup_query": str(label).strip(),
    }
    if exploration.get("mode"):
        spec["graph_mode"] = exploration["mode"]
    if "use_lcc" in exploration:
        spec["use_lcc"] = exploration["use_lcc"]
    if center.get("station_id"):
        spec["selected_station_id"] = center["station_id"]
    if center.get("stop_id"):
        spec["selected_stop_id"] = center["stop_id"]

    counts = exploration.get("counts") or {}
    stop_n = len(exploration.get("nearby_stops") or [])
    poi_n = len(exploration.get("nearby_pois") or exploration.get("pois") or [])
    spec["exploration_revision"] = (
        f"{exploration.get('radius_m')}:{counts.get('stops', stop_n)}:"
        f"{counts.get('pois', poi_n)}:{stop_n}:{poi_n}"
    )

    rv: dict[str, Any] = {
        "center": center,
        "radius_m": exploration.get("radius_m"),
        "counts": counts,
        "summary": exploration.get("summary"),
        "nearby_stops": exploration.get("nearby_stops") or [],
        "nearby_pois": exploration.get("nearby_pois") or exploration.get("pois") or [],
    }
    cmds.append({"kind": "transport_exploration_view", **rv})
    cmds.append({"kind": "atlas_transport_action", "spec": spec})
    return cmds


PlaceKind = Literal["auto", "station", "poi"]
PlaceTopic = Literal["about", "history", "hours", "accessibility", "disruptions", "reviews"]


def _format_station_lines(line_map: dict[str, list[str]] | None) -> str:
    if not line_map:
        return ""
    parts: list[str] = []
    for mode, lines in sorted(line_map.items()):
        vals = [str(x).strip() for x in (lines or []) if str(x).strip()]
        if vals:
            parts.append(f"{mode}: {', '.join(vals[:8])}")
    return "; ".join(parts)


_AIRPORT_AREA = re.compile(
    r"\b(orly|cdg|roissy|a[eé]roport|airport|terminal)\b",
    re.I,
)
_SHOP_CATEGORY = frozenset({"shop", "clothes", "fashion", "boutique", "jewelry", "jewellery"})


def _is_airport_context(*labels: str | None) -> bool:
    text = " ".join(str(label or "") for label in labels).lower()
    return bool(_AIRPORT_AREA.search(text))


def _is_shop_like(category: str | None, label: str | None = None) -> bool:
    cat = str(category or "").strip().lower()
    if cat in _SHOP_CATEGORY or cat.startswith("shop"):
        return True
    label_l = str(label or "").lower()
    return any(token in label_l for token in ("shop", "boutique", "store", "magasin"))


def _build_web_search_query(
    *,
    kind: str,
    label: str,
    near_label: str | None,
    topic: PlaceTopic | None,
    includes_today: bool = False,
    category: str | None = None,
) -> str:
    area = (near_label or "Paris").strip()
    topic = (topic or "about").strip().lower()
    today = " today" if includes_today else ""
    shop_like = _is_shop_like(category, label)
    airport = _is_airport_context(area, label, near_label)

    if kind == "station":
        if topic == "history":
            return f"{label} Paris metro station history"
        if topic == "accessibility":
            return f"{label} Paris metro station accessibility wheelchair{today}"
        if topic == "disruptions":
            return f"RATP {label} Paris metro service disruption{today}"
        if topic == "hours":
            return f"{label} Paris metro station opening hours"
        if topic == "reviews":
            return f"{label} Paris metro station passenger information"
        return f"{label} station Paris Île-de-France metro RER"

    if topic == "hours":
        if airport:
            parts = [label, area, "airport", "terminal"]
            if shop_like:
                parts.extend(["shop", "boutique"])
            parts.extend(["opening hours", "horaires"])
            return " ".join(part for part in parts if part)
        if shop_like:
            return f"{label} {area} Paris boutique store opening hours horaires"
        return f"{label} {area} Paris opening hours horaires"
    if topic == "reviews":
        if airport and shop_like:
            return f"{label} {area} airport terminal shop reviews"
        return f"{label} {area} Paris reviews"
    if topic == "history":
        return f"{label} {area} Paris history"
    if airport and shop_like:
        return f"{label} {area} airport terminal shop boutique"
    return f"{label} {area} Paris"


def _near_query_from_context(ctx: dict[str, Any]) -> str | None:
    from backend.product_shell import transport_exploration as tex

    world = ctx.get("world") if isinstance(ctx.get("world"), dict) else ctx
    transport = world.get("transport") if isinstance(world, dict) else None
    if not isinstance(transport, dict):
        return tex.query_from_agent_context(ctx)

    last = transport.get("last_exploration")
    if isinstance(last, dict):
        center = last.get("center")
        if isinstance(center, dict):
            for key in ("label", "station_name", "stop_name", "query"):
                val = str(center.get(key) or "").strip()
                if val:
                    return val
        q = str(last.get("query") or "").strip()
        if q:
            return q

    sel = transport.get("selected_station")
    if isinstance(sel, dict):
        val = str(sel.get("station_name") or sel.get("label") or "").strip()
        if val:
            return val
    return tex.query_from_agent_context(ctx)


def _exploration_anchor_from_context(ctx: dict[str, Any]) -> str | None:
    """Last map exploration center (from 'show POIs around X') — required for POI info lookups."""
    world = ctx.get("world") if isinstance(ctx.get("world"), dict) else ctx
    transport = world.get("transport") if isinstance(world, dict) else None
    if not isinstance(transport, dict):
        return None
    last = transport.get("last_exploration")
    if not isinstance(last, dict):
        return None
    center = last.get("center")
    if isinstance(center, dict):
        for key in ("label", "station_name", "stop_name", "query"):
            val = str(center.get(key) or "").strip()
            if val:
                return val
    q = str(last.get("query") or "").strip()
    return q or None


def _anchor_for_place_lookup(
    ctx: dict[str, Any],
    *,
    topic: str,
    place_kind: str,
) -> str | None:
    if place_kind == "station":
        return _near_query_from_context(ctx)
    if place_kind == "poi" or topic in ("hours", "reviews"):
        return _exploration_anchor_from_context(ctx)
    explored = _exploration_anchor_from_context(ctx)
    if explored:
        return explored
    return _near_query_from_context(ctx)


def _ensure_area_anchored_web_query(
    web_query: str,
    *,
    label: str,
    near_label: str,
    topic: str = "about",
    category: str | None = None,
) -> str:
    """Ensure the web query includes the exploration area, never a bare global brand lookup."""
    area = str(near_label or "").strip()
    if not area or area.lower() == "paris":
        return web_query
    q_lower = web_query.lower()
    area_tokens = [t for t in re.split(r"\W+", area.lower()) if len(t) > 3]
    if area_tokens and any(token in q_lower for token in area_tokens):
        return web_query
    topic_value = topic if topic in ("about", "history", "hours", "accessibility", "disruptions", "reviews") else "about"
    return _build_web_search_query(
        kind="poi",
        label=label,
        near_label=area,
        topic=topic_value,  # type: ignore[arg-type]
        category=category,
    )


def _finalize_place_lookup_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Force area anchoring on outbound web queries and echo near_query on the payload."""
    if not payload.get("ok"):
        return payload
    payload = dict(payload)
    local = payload.get("local") if isinstance(payload.get("local"), dict) else {}
    label = str(local.get("label") or payload.get("query") or "").strip()
    near_label = str(local.get("near") or payload.get("near_query") or "").strip()
    if near_label:
        payload["near_query"] = near_label
    web_query = str(payload.get("web_search_query") or "").strip()
    if web_query and near_label and payload.get("place_kind") == "poi":
        category = str(local.get("category") or "").strip() or None
        payload["web_search_query"] = _ensure_area_anchored_web_query(
            web_query,
            label=label or str(payload.get("query") or ""),
            near_label=near_label,
            topic=str(payload.get("topic") or "about"),
            category=category,
        )
    return payload


def _inferred_poi_lookup_payload(
    q: str,
    *,
    center: dict[str, Any],
    near: str | None,
    near_query: str | None,
    topic: PlaceTopic | None,
    includes_today: bool,
) -> dict[str, Any]:
    near_label = str(
        center.get("label") or center.get("station_name") or near or near_query or "Paris"
    ).strip()
    local_lines = [
        f"Place requested: {q}",
        f"Search area: {near_label} (from recent map exploration)",
        "No exact match in the local POI index; online search is anchored to this area.",
    ]
    web_query = _build_web_search_query(
        kind="poi",
        label=q,
        near_label=near_label,
        topic=topic,
        includes_today=includes_today,
    )
    return {
        "ok": True,
        "place_kind": "poi",
        "query": q,
        "near_query": near_query or near_label,
        "topic": topic,
        "inferred": True,
        "local": {
            "kind": "poi",
            "label": q,
            "near": near_label,
            "source": "area_context",
        },
        "local_summary": "\n".join(local_lines),
        "web_search_query": web_query,
    }


def _station_lookup_payload(
    q: str,
    *,
    local: dict[str, Any],
    local_lines: list[str],
    near_query: str | None,
    topic: PlaceTopic | None,
    includes_today: bool,
) -> dict[str, Any]:
    from backend.product_shell.services.idfm_station_enrichment import enrich_local_station

    match = dict(local)
    if isinstance(local.get("stop_ids"), list):
        match["stop_ids"] = list(local.get("stop_ids") or [])

    idfm = enrich_local_station(
        match,
        topic=str(topic or "about"),
        includes_today=includes_today,
    )
    payload: dict[str, Any] = {
        "ok": True,
        "place_kind": "station",
        "query": q,
        "near_query": near_query,
        "topic": topic,
        "local": local,
        "local_summary": "\n".join(local_lines),
        "web_search_query": None,
        "enrichment_source": "local",
    }
    if idfm.get("ok"):
        payload["enrichment_source"] = "idfm"
        payload["idfm_summary"] = idfm.get("idfm_summary")
        payload["idfm_data"] = idfm.get("idfm_data")
    elif idfm.get("failure"):
        payload["idfm_error"] = idfm.get("error")
        payload["idfm_failure"] = idfm.get("failure")
    return payload


def _poi_lookup_result(
    q: str,
    *,
    near: str | None,
    ctx: dict[str, Any],
    mode: GraphMode,
    use_lcc: bool,
    station_first: bool,
    topic: PlaceTopic | None,
    includes_today: bool,
    near_query: str | None,
) -> dict[str, Any] | None:
    from backend.product_shell import transport_exploration as tex

    poi_res = tex.resolve_poi_by_name(
        q,
        near_query=near,
        agent_context=ctx,
        mode=mode,
        use_lcc=use_lcc,
        station_first=station_first,
    )
    if poi_res.get("status") == "inferred":
        center = poi_res.get("center") if isinstance(poi_res.get("center"), dict) else {}
        if center:
            return _inferred_poi_lookup_payload(
                q,
                center=center,
                near=near,
                near_query=near_query,
                topic=topic,
                includes_today=includes_today,
            )
        return None
    if poi_res.get("status") != "exact":
        return None
    poi = poi_res.get("poi") or {}
    center = poi_res.get("center") if isinstance(poi_res.get("center"), dict) else {}
    label = str(poi.get("name") or q).strip()
    near_label = str(
        center.get("label") or center.get("station_name") or near or near_query or "Paris"
    ).strip()
    category = str(poi.get("category") or poi.get("type") or poi.get("family") or "place").strip()
    dist = poi.get("distance_m")
    local_lines = [f"POI: {label} ({category})"]
    if dist is not None:
        local_lines.append(f"Distance from {near_label}: {int(round(float(dist)))} m")
    if poi_res.get("source") == "exploration_snapshot":
        local_lines.append("Matched from the current map exploration list.")
    web_query = _build_web_search_query(
        kind="poi",
        label=label,
        near_label=near_label,
        topic=topic,
        includes_today=includes_today,
        category=category,
    )
    return {
        "ok": True,
        "place_kind": "poi",
        "query": q,
        "near_query": near_query or near_label,
        "topic": topic,
        "local": {
            "kind": "poi",
            "label": label,
            "category": category,
            "distance_m": dist,
            "coordinates": poi.get("coordinates"),
            "near": near_label,
            "source": poi_res.get("source"),
        },
        "local_summary": "\n".join(local_lines),
        "web_search_query": web_query,
    }


def lookup_place_for_chat(
    query: str,
    *,
    kind: PlaceKind = "auto",
    near_query: str | None = None,
    topic: PlaceTopic | None = "about",
    includes_today: bool = False,
    mode: GraphMode = "metro",
    use_lcc: bool = True,
    station_first: bool = True,
    agent_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Resolve a station or POI from local CSPE data and build a web-search query.
    Chat-only: does not sync map UI.
    """
    from backend.product_shell import transport_exploration as tex
    from backend.product_shell.services import agent_store

    q = (query or "").strip()
    if len(q) < 2:
        return {"ok": False, "error": "query too short", "needs_clarification": True}

    ctx = agent_context if agent_context is not None else agent_store.get_context()
    place_kind = (kind or "auto").strip().lower()
    if place_kind not in ("auto", "station", "poi"):
        place_kind = "auto"

    topic_value = topic or "about"
    anchor = _anchor_for_place_lookup(ctx, topic=topic_value, place_kind=place_kind)
    if place_kind in ("poi", "auto") and topic_value in ("hours", "reviews"):
        if not anchor:
            return {
                "ok": False,
                "place_kind": "poi",
                "query": q,
                "needs_clarification": True,
                "error": (
                    "Explore an area first (e.g. show POIs around a station), "
                    "then ask about a specific place there."
                ),
            }
    near = (near_query or "").strip() or anchor or _near_query_from_context(ctx)
    prefer_poi = place_kind in ("poi", "auto") and topic_value in ("hours", "reviews")

    if prefer_poi:
        poi_payload = _poi_lookup_result(
            q,
            near=near,
            ctx=ctx,
            mode=mode,
            use_lcc=use_lcc,
            station_first=station_first,
            topic=topic_value,
            includes_today=includes_today,
            near_query=near_query,
        )
        if poi_payload:
            return _finalize_place_lookup_payload(poi_payload)

    local: dict[str, Any] | None = None
    local_lines: list[str] = []

    if place_kind in ("auto", "station"):
        station_res = resolve_stop_query(
            q,
            mode=mode,
            use_lcc=use_lcc,
            station_first=station_first,
        )
        if station_res.get("status") == "exact":
            match = station_res.get("match") or {}
            mode_eff = station_res.get("mode") or mode
            lcc_eff = bool(station_res.get("use_lcc") if station_res.get("use_lcc") is not None else use_lcc)
            label = (
                (match.get("station_name") or match.get("stop_name") or q).strip()
            )
            line_map: dict[str, list[str]] = {}
            modes_served: list[str] = []
            station_id = (match.get("station_id") or "").strip() or None
            if station_id:
                G = te.graph_for(mode_eff, lcc_eff)
                idx = te.station_layer_for(mode_eff, lcc_eff)
                line_map = tex._station_lines(G, idx, station_id)
                modes_served = tex._station_modes(G, idx, station_id)
            line_text = _format_station_lines(line_map)
            local = {
                "kind": "station",
                "label": label,
                "station_id": station_id,
                "stop_id": match.get("stop_id"),
                "station_name": match.get("station_name"),
                "stop_name": match.get("stop_name"),
                "stop_ids": list(match.get("stop_ids") or []),
                "modes_served": modes_served,
                "lines": line_map,
            }
            local_lines.append(f"Station: {label}")
            if modes_served:
                local_lines.append(f"Modes: {', '.join(modes_served)}")
            if line_text:
                local_lines.append(f"Lines: {line_text}")
            if place_kind == "station" or (place_kind == "auto" and station_res.get("status") == "exact"):
                return _station_lookup_payload(
                    q,
                    local=local,
                    local_lines=local_lines,
                    near_query=near_query,
                    topic=topic,
                    includes_today=includes_today,
                )
        if place_kind == "station":
            if station_res.get("status") == "ambiguous":
                return {
                    "ok": False,
                    "place_kind": "station",
                    "query": q,
                    "needs_clarification": True,
                    "error": "Multiple stations match; ask the user to be more specific.",
                    "candidates": (station_res.get("matches") or [])[:5],
                }
            return {
                "ok": False,
                "place_kind": "station",
                "query": q,
                "error": f"No station found for {q!r}",
            }

    poi_res = tex.resolve_poi_by_name(
        q,
        near_query=near,
        agent_context=ctx,
        mode=mode,
        use_lcc=use_lcc,
        station_first=station_first,
    )
    if poi_res.get("status") == "exact":
        poi = poi_res.get("poi") or {}
        center = poi_res.get("center") if isinstance(poi_res.get("center"), dict) else {}
        label = str(poi.get("name") or q).strip()
        near_label = str(
            center.get("label") or center.get("station_name") or near or near_query or "Paris"
        ).strip()
        category = str(poi.get("category") or poi.get("type") or poi.get("family") or "place").strip()
        dist = poi.get("distance_m")
        local = {
            "kind": "poi",
            "label": label,
            "category": category,
            "distance_m": dist,
            "coordinates": poi.get("coordinates"),
            "near": near_label,
            "source": poi_res.get("source"),
        }
        local_lines.append(f"POI: {label} ({category})")
        if dist is not None:
            local_lines.append(f"Distance from {near_label}: {int(round(float(dist)))} m")
        if poi_res.get("source") == "exploration_snapshot":
            local_lines.append("Matched from the current map exploration list.")
        web_query = _build_web_search_query(
            kind="poi",
            label=label,
            near_label=near_label,
            topic=topic_value,
            includes_today=includes_today,
            category=category,
        )
        return _finalize_place_lookup_payload(
            {
                "ok": True,
                "place_kind": "poi",
                "query": q,
                "near_query": near_query or near_label,
                "topic": topic,
                "local": local,
                "local_summary": "\n".join(local_lines),
                "web_search_query": web_query,
            }
        )

    if poi_res.get("status") == "inferred":
        center = poi_res.get("center") if isinstance(poi_res.get("center"), dict) else {}
        if center:
            return _finalize_place_lookup_payload(
                _inferred_poi_lookup_payload(
                    q,
                    center=center,
                    near=near,
                    near_query=near_query,
                    topic=topic,
                    includes_today=includes_today,
                )
            )

    if poi_res.get("status") == "ambiguous":
        return {
            "ok": False,
            "place_kind": "poi",
            "query": q,
            "needs_clarification": True,
            "error": "Multiple POIs match; ask the user which one they mean.",
            "candidates": poi_res.get("candidates") or [],
        }

    return {
        "ok": False,
        "place_kind": "poi",
        "query": q,
        "near_query": near_query,
        "error": poi_res.get("error") or f"Could not find {q!r}",
        "needs_clarification": bool(poi_res.get("status") == "needs_context"),
    }
