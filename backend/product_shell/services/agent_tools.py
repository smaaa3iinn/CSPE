"""Server-side agent tools: resolve stops, compute routes, sync UI — no browser required."""

from __future__ import annotations

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
) -> dict[str, Any]:
    route = route_payload.get("route") or route_payload
    if not route or not route.get("ok"):
        return {"ok": False, "error": "No successful route to visualize"}
    session = te.create_graph3d_session(
        mode=mode,
        use_lcc=use_lcc,
        graph_viz_mode=graph_viz_mode,
        path_stop_ids=route.get("path"),
        path_station_ids=route.get("station_path"),
    )
    agent_store.record_event(
        "transport.graph3d.session",
        {"session_id": session.get("session_id"), "metadata": session.get("metadata")},
        source="agent_tools",
    )
    return {"ok": True, **session}


def shell_commands_for_route(route_payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Build shell commands to sync Transport UI after server-side routing."""
    cmds: list[dict[str, Any]] = [{"kind": "set_mode", "mode": "transport"}]
    route = route_payload.get("route") or {}
    spec: dict[str, Any] = {
        "open_app_mode": "transport",
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
    cmds.append({"kind": "atlas_transport_action", "spec": {**spec, "run": "route"}})

    if route.get("ok"):
        rv: dict[str, Any] = {}
        if route.get("path"):
            rv["path_ids"] = route["path"]
        if route.get("station_path"):
            rv["station_path_ids"] = route["station_path"]
        res = route.get("result") or {}
        meta_bits = []
        if res.get("time_s") is not None:
            meta_bits.append(f"{int(res['time_s'] // 60)} min")
        if res.get("transfers") is not None:
            meta_bits.append(f"{res['transfers']} transfers")
        if meta_bits:
            rv["route_meta"] = ", ".join(meta_bits)
        if rv:
            cmds.append({"kind": "transport_route_view", **rv})
    return cmds
