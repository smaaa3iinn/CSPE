from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from backend.product_shell.schemas import (
    TransportMapRequest,
    TransportMapResponse,
    TransportGraph3DSessionRequest,
    TransportGraph3DSessionResponse,
    TransportRouteRequest,
    TransportRouteResponse,
    TransportStatsResponse,
)
from backend.product_shell import transport_engine as te
from backend.product_shell import ui_transport_logger as ui_log

router = APIRouter(tags=["transport"])


@router.get("/transport/bundle-health")
def get_bundle_health() -> dict:
    """Graph routing bundle readiness (cache version + layer keys). Same data source as all transport routes."""
    try:
        b = te.get_bundle()
        return {
            "ok": True,
            "cache_version": b.get("cache_version"),
            "modes": list((b.get("graphs") or {}).keys()),
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
        )
        return TransportMapResponse(html=html, mapbox_token_source=src)
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


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


@router.get("/transport/stops/search")
def get_stops_search(
    q: str = Query("", min_length=0),
    limit: int = Query(40, ge=1, le=80),
    mode: str = Query("metro"),
    use_lcc: bool = Query(True),
    station_first: bool = Query(False),
) -> dict:
    try:
        if mode not in ("all", "metro", "rail", "tram", "bus", "other"):
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


@router.get("/transport/stats", response_model=TransportStatsResponse)
def get_transport_stats(
    mode: str = Query("metro"),
    use_lcc: bool = Query(True),
) -> TransportStatsResponse:
    try:
        if mode not in ("all", "metro", "rail", "tram", "bus", "other"):
            raise HTTPException(status_code=400, detail="invalid mode")
        n, e = te.graph_stats(mode, use_lcc)
        return TransportStatsResponse(mode=mode, use_lcc=use_lcc, nodes=n, edges=e)
    except FileNotFoundError as ex:
        raise HTTPException(status_code=503, detail=str(ex)) from ex
