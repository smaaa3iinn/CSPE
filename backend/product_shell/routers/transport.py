from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from backend.product_shell.schemas import (
    TransportMapRequest,
    TransportMapResponse,
    TransportExplorationOverlayRequest,
    TransportExplorationOverlayResponse,
    TransportRouteOverlayRequest,
    TransportRouteOverlayResponse,
    TransportGraph3DSessionRequest,
    TransportGraph3DSessionResponse,
    TransportGraph3DSyncPeekResponse,
    TransportGraph3DSyncPushResponse,
    TransportGraph3DSyncRequest,
    TransportRouteRequest,
    TransportRouteResponse,
    TransportStatsResponse,
)
from backend.product_shell import transport_engine as te
from backend.product_shell import transport_exploration as tex
from backend.product_shell import ui_transport_logger as ui_log
from backend.product_shell.routers import shell as shell_router
from backend.product_shell.schemas import TransportExploreAreaRequest
from backend.product_shell.services import agent_store, agent_tools, warmup
from src.core.project_logs import log_compact_line

router = APIRouter(tags=["transport"])

VALID_TRANSPORT_MODES = ("all", "all_mb", "metro", "rail", "tram", "bus", "other")


def _overlay_geo_counts(overlay: dict) -> tuple[int, int, bool]:
    center = overlay.get("center") if isinstance(overlay.get("center"), dict) else {}
    center_ok = center.get("lat") is not None and center.get("lon") is not None
    stop_geo = 0
    for row in overlay.get("nearby_stops") or []:
        if not isinstance(row, dict):
            continue
        coords = row.get("coordinates") if isinstance(row.get("coordinates"), dict) else {}
        if coords.get("lat") is not None and coords.get("lon") is not None:
            stop_geo += 1
    poi_geo = 0
    for row in overlay.get("nearby_pois") or []:
        if not isinstance(row, dict):
            continue
        coords = row.get("coordinates") if isinstance(row.get("coordinates"), dict) else {}
        if coords.get("lat") is not None and coords.get("lon") is not None:
            poi_geo += 1
    return stop_geo, poi_geo, center_ok


@router.get("/transport/bundle-health")
def get_bundle_health() -> dict:
    """Graph routing bundle readiness (cache version + layer keys). Same data source as all transport routes."""
    try:
        b = te.get_bundle()
        return {
            "ok": True,
            "cache_version": b.get("cache_version"),
            "modes": list((b.get("graphs") or {}).keys()),
            "warmup": warmup.warmup_status(),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.post("/transport/map", response_model=TransportMapResponse)
def post_transport_map(body: TransportMapRequest) -> TransportMapResponse:
    try:
        html, src = te.render_transport_map_html(
            mode=body.mode,
            use_lcc=body.use_lcc,
            viz_mode=body.viz_mode,
            path_stop_ids=body.path_stop_ids,
            selected_stop_id=body.selected_stop_id,
            selected_station_id=body.selected_station_id,
            show_transfers=body.show_transfers,
            poi_radius_m=body.poi_radius_m,
            poi_limit=body.poi_limit,
            poi_category_key=body.poi_category_key,
            graph_viz_mode=body.graph_viz_mode,
            expanded_station_id=body.expanded_station_id,
            path_station_ids=body.path_station_ids,
            exploration_overlay=body.exploration_overlay,
        )
        if body.exploration_overlay:
            overlay = body.exploration_overlay or {}
            stop_geo, poi_geo, center_ok = _overlay_geo_counts(overlay)
            ui_log.log_exploration_map_render(
                stop_count=len(overlay.get("nearby_stops") or []),
                poi_count=len(overlay.get("nearby_pois") or []),
                radius_m=overlay.get("radius_m"),
                html_bytes=len(html or ""),
                selected_station_id=body.selected_station_id,
                selected_stop_id=body.selected_stop_id,
                mode=body.mode,
                stop_geo_count=stop_geo,
                poi_geo_count=poi_geo,
                center_ok=center_ok,
            )
        return TransportMapResponse(html=html, mapbox_token_source=src)
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except RuntimeError as e:
        log_compact_line(f"[Exploration] map_render failed err={e!r}")
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        log_compact_line(
            "[Transport] map_render failed "
            f"mode={body.mode} graph_viz={body.graph_viz_mode} "
            f"path_stop_count={len(body.path_stop_ids or [])} "
            f"path_station_count={len(body.path_station_ids or [])} err={e!r}"
        )
        raise HTTPException(
            status_code=503,
            detail=(
                "Map render failed. The current route or selection may not be valid "
                "for the selected transport mode; clear the route and try again."
            ),
        ) from e


@router.post("/transport/map/exploration-overlay", response_model=TransportExplorationOverlayResponse)
def post_transport_exploration_overlay(body: TransportExplorationOverlayRequest) -> TransportExplorationOverlayResponse:
    from src.viz.plot_mapbox import build_exploration_overlay_update

    overlay = body.exploration_overlay
    payload = build_exploration_overlay_update(overlay)
    if overlay:
        stop_geo, poi_geo, center_ok = _overlay_geo_counts(overlay)
        ui_log.log_exploration_map_render(
            stop_count=len(overlay.get("nearby_stops") or []),
            poi_count=len(overlay.get("nearby_pois") or []),
            radius_m=overlay.get("radius_m"),
            html_bytes=0,
            selected_station_id=None,
            selected_stop_id=None,
            mode=None,
            stop_geo_count=stop_geo,
            poi_geo_count=poi_geo,
            center_ok=center_ok,
            overlay_only=True,
        )
    return TransportExplorationOverlayResponse(
        exploration=payload["exploration"],
        view=payload.get("view"),
    )


@router.post("/transport/map/route-overlay", response_model=TransportRouteOverlayResponse)
def post_transport_route_overlay(body: TransportRouteOverlayRequest) -> TransportRouteOverlayResponse:
    overlay = body.route_overlay
    if overlay is None:
        return TransportRouteOverlayResponse(
            route={
                "path": {"type": "FeatureCollection", "features": []},
                "station_network_points": {"type": "FeatureCollection", "features": []},
                "station_network_lines": {"type": "FeatureCollection", "features": []},
                "selected_stop_id": None,
                "selected_station_id": None,
                "path_stop_count": 0,
                "path_station_count": 0,
            },
            view=None,
        )
    payload = te.build_transport_route_overlay(
        mode=overlay.mode,
        use_lcc=overlay.use_lcc,
        graph_viz_mode=overlay.graph_viz_mode,
        path_stop_ids=overlay.path_stop_ids,
        path_station_ids=overlay.path_station_ids,
        selected_stop_id=overlay.selected_stop_id,
        selected_station_id=overlay.selected_station_id,
    )
    return TransportRouteOverlayResponse(route=payload["route"], view=payload.get("view"))


@router.post("/transport/graph3d/session", response_model=TransportGraph3DSessionResponse)
def post_transport_graph3d_session(
    body: TransportGraph3DSessionRequest,
) -> TransportGraph3DSessionResponse:
    try:
        session = te.create_graph3d_session(
            mode=body.mode,
            use_lcc=body.use_lcc,
            graph_viz_mode=body.graph_viz_mode,
            path_stop_ids=body.path_stop_ids,
            path_station_ids=body.path_station_ids,
            selected_stop_id=body.selected_stop_id,
            selected_station_id=body.selected_station_id,
            route_legs=body.route_legs,
            route_meta=body.route_meta,
        )
        project = session["project"]
        session_id = session["session_id"]
        return TransportGraph3DSessionResponse(
            session_id=session_id,
            graph_url=f"/api/transport/graph3d/session/{session_id}",
            expires_in_s=session["expires_in_s"],
            metadata=project.get("metadata") or {},
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/transport/graph3d/session/{session_id}")
def get_transport_graph3d_session(session_id: str) -> dict:
    project = te.get_graph3d_session(session_id)
    if project is None:
        raise HTTPException(status_code=404, detail="3D graph session expired or not found.")
    return project


@router.post("/transport/graph3d/sync", response_model=TransportGraph3DSyncPushResponse)
def post_transport_graph3d_sync(body: TransportGraph3DSyncRequest) -> TransportGraph3DSyncPushResponse:
    try:
        row = te.push_graph3d_sync(
            client_id=body.client_id,
            fingerprint=body.fingerprint,
            mode=body.mode,
            use_lcc=body.use_lcc,
            graph_viz_mode=body.graph_viz_mode,
            path_stop_ids=body.path_stop_ids,
            path_station_ids=body.path_station_ids,
            selected_stop_id=body.selected_stop_id,
            selected_station_id=body.selected_station_id,
            route_legs=body.route_legs,
            route_meta=body.route_meta,
        )
        return TransportGraph3DSyncPushResponse(**row)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/transport/graph3d/sync/{client_id}", response_model=TransportGraph3DSyncPeekResponse)
def get_transport_graph3d_sync(
    client_id: str,
    fingerprint: str | None = Query(default=None),
) -> TransportGraph3DSyncPeekResponse:
    row = te.peek_graph3d_sync(client_id, fingerprint)
    return TransportGraph3DSyncPeekResponse(**row)


@router.get("/transport/stops/search")
def get_stops_search(
    q: str = Query("", min_length=0),
    limit: int = Query(40, ge=1, le=80),
    mode: str = Query("metro"),
    use_lcc: bool = Query(True),
    station_first: bool = Query(False),
) -> dict:
    try:
        if mode not in VALID_TRANSPORT_MODES:
            raise HTTPException(status_code=400, detail="invalid mode")
        matches = te.search_stops(
            q, limit=limit, mode=mode, use_lcc=use_lcc, station_first=station_first
        )
        try:
            ui_log.log_ui_search_stops(
                q=q,
                limit=limit,
                mode=mode,
                use_lcc=use_lcc,
                station_first=station_first,
                matches=matches,
            )
        except Exception:
            pass
        return {"matches": matches}
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.post("/transport/route", response_model=TransportRouteResponse)
def post_transport_route(body: TransportRouteRequest) -> TransportRouteResponse:
    try:
        fs, ts = (body.from_station_id or "").strip(), (body.to_station_id or "").strip()
        fa, tb = (body.from_stop_id or "").strip(), (body.to_stop_id or "").strip()
        has_st = bool(fs and ts)
        has_sp = bool(fa and tb)
        if has_st == has_sp:
            raise HTTPException(
                status_code=400,
                detail="Provide exactly one of: (from_stop_id, to_stop_id) or (from_station_id, to_station_id).",
            )
        if has_st:
            r = te.compute_route_stations(fs, ts, mode=body.mode, use_lcc=body.use_lcc)
            routing = "station"
        else:
            r = te.compute_route(fa, tb, mode=body.mode, use_lcc=body.use_lcc)
            routing = "stop"
        out = TransportRouteResponse(
            ok=r["ok"],
            routing_scope=r.get("routing_scope"),
            path=r.get("path"),
            station_path=r.get("station_path"),
            station_names=r.get("station_names"),
            path_legs=r.get("path_legs"),
            path_summary=r.get("path_summary"),
            result=r.get("result"),
            detail=r.get("detail"),
            error=r.get("error"),
        )
        try:
            ui_log.log_ui_route(
                mode=body.mode,
                use_lcc=body.use_lcc,
                routing=routing,
                from_stop_id=fa or None,
                to_stop_id=tb or None,
                from_station_id=fs or None,
                to_station_id=ts or None,
                response={
                    "ok": out.ok,
                    "routing_scope": out.routing_scope,
                    "path": out.path,
                    "station_path": out.station_path,
                    "station_names": out.station_names,
                    "path_legs": out.path_legs,
                    "path_summary": out.path_summary,
                    "result": out.result,
                    "detail": out.detail,
                    "error": out.error,
                },
            )
        except Exception:
            pass
        return out
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/transport/stops/nearby")
def get_stops_nearby(
    q: str = Query("", min_length=0),
    radius_m: int = Query(tex.DEFAULT_STOP_RADIUS_M, ge=50, le=3000),
    limit: int = Query(20, ge=1, le=50),
    mode: str = Query("all"),
    use_lcc: bool = Query(False),
    station_first: bool = Query(True),
    sync_ui: bool = Query(False),
) -> dict:
    try:
        if mode not in VALID_TRANSPORT_MODES:
            raise HTTPException(status_code=400, detail="invalid mode")
        ctx = agent_store.get_context()
        result = tex.nearby_stops(
            q,
            radius_m=radius_m,
            limit=limit,
            mode=mode,  # type: ignore[arg-type]
            use_lcc=use_lcc,
            station_first=station_first,
            agent_context=ctx,
        )
        if sync_ui and result.get("ok"):
            cmds = agent_tools.shell_commands_for_exploration(result)
            ui_log.log_exploration_api_result(result, sync_ui=True, cmds=len(cmds))
            shell_router.enqueue_commands(cmds)
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/transport/pois/nearby")
def get_pois_nearby(
    q: str = Query("", min_length=0),
    radius_m: int = Query(tex.DEFAULT_POI_RADIUS_M, ge=50, le=3000),
    limit: int = Query(30, ge=1, le=60),
    categories: list[str] = Query(default=["all"]),
    mode: str = Query("metro"),
    use_lcc: bool = Query(False),
    station_first: bool = Query(True),
    sync_ui: bool = Query(False),
) -> dict:
    try:
        if mode not in VALID_TRANSPORT_MODES:
            raise HTTPException(status_code=400, detail="invalid mode")
        ctx = agent_store.get_context()
        result = tex.nearby_pois(
            q,
            radius_m=radius_m,
            limit=limit,
            categories=categories,
            mode=mode,  # type: ignore[arg-type]
            use_lcc=use_lcc,
            station_first=station_first,
            agent_context=ctx,
        )
        if sync_ui and result.get("ok"):
            cmds = agent_tools.shell_commands_for_exploration(result)
            ui_log.log_exploration_api_result(result, sync_ui=True, cmds=len(cmds))
            shell_router.enqueue_commands(cmds)
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.post("/transport/area/explore")
def post_area_explore(body: TransportExploreAreaRequest) -> dict:
    try:
        ctx = agent_store.get_context()
        result = tex.explore_area(
            body.query,
            radius_m=body.radius_m,
            include_stops=body.include_stops,
            include_pois=body.include_pois,
            poi_categories=body.poi_categories,
            transport_modes=body.transport_modes,
            limit_stops=body.limit_stops,
            limit_pois=body.limit_pois,
            mode=body.mode,
            use_lcc=body.use_lcc,
            station_first=body.station_first,
            agent_context=ctx,
        )
        if body.sync_ui and result.get("ok"):
            cmds = agent_tools.shell_commands_for_exploration(result)
            ui_log.log_exploration_api_result(result, sync_ui=True, cmds=len(cmds))
            shell_router.enqueue_commands(cmds)
        elif body.sync_ui:
            ui_log.log_exploration_api_result(result, sync_ui=True, cmds=0)
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.post("/transport/area/filter")
def post_area_filter(
    radius_m: int | None = Query(None, ge=50, le=3000),
    modes: list[str] = Query(default=["all"]),
    poi_categories: list[str] = Query(default=["all"]),
    lines: list[str] = Query(default=[]),
    max_results: int = Query(50, ge=1, le=100),
    include_stops: bool | None = Query(None),
    include_pois: bool | None = Query(None),
    sync_ui: bool = Query(False),
) -> dict:
    result = tex.filter_visible_results(
        radius_m=radius_m,
        modes=modes,
        poi_categories=poi_categories,
        lines=lines,
        max_results=max_results,
        include_stops=include_stops,
        include_pois=include_pois,
    )
    if sync_ui and result.get("ok"):
        shell_router.enqueue_commands(agent_tools.shell_commands_for_exploration(result))
    return result


@router.get("/transport/stats", response_model=TransportStatsResponse)
def get_transport_stats(
    mode: str = Query("metro"),
    use_lcc: bool = Query(True),
) -> TransportStatsResponse:
    try:
        if mode not in VALID_TRANSPORT_MODES:
            raise HTTPException(status_code=400, detail="invalid mode")
        n, e = te.graph_stats(mode, use_lcc)
        return TransportStatsResponse(mode=mode, use_lcc=use_lcc, nodes=n, edges=e)
    except FileNotFoundError as ex:
        raise HTTPException(status_code=503, detail=str(ex)) from ex
