from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from backend.product_shell.schemas import (
    TransportMapRequest,
    TransportMapResponse,
    TransportRouteRequest,
    TransportRouteResponse,
    TransportStatsResponse,
)
from backend.product_shell import transport_engine as te

router = APIRouter(tags=["transport"])


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
        return {
            "matches": te.search_stops(
                q, limit=limit, mode=mode, use_lcc=use_lcc, station_first=station_first
            )
        }
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
        else:
            r = te.compute_route(fa, tb, mode=body.mode, use_lcc=body.use_lcc)
        return TransportRouteResponse(
            ok=r["ok"],
            routing_scope=r.get("routing_scope"),
            path=r.get("path"),
            station_path=r.get("station_path"),
            station_names=r.get("station_names"),
            result=r.get("result"),
            detail=r.get("detail"),
            error=r.get("error"),
        )
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
