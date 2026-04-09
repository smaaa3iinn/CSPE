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
            show_transfers=body.show_transfers,
            poi_radius_m=body.poi_radius_m,
            poi_limit=body.poi_limit,
            poi_category_key=body.poi_category_key,
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
) -> dict:
    try:
        if mode not in ("all", "metro", "rail", "tram", "bus", "other"):
            raise HTTPException(status_code=400, detail="invalid mode")
        return {"matches": te.search_stops(q, limit=limit, mode=mode, use_lcc=use_lcc)}
    except FileNotFoundError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.post("/transport/route", response_model=TransportRouteResponse)
def post_transport_route(body: TransportRouteRequest) -> TransportRouteResponse:
    try:
        r = te.compute_route(body.from_stop_id, body.to_stop_id, mode=body.mode, use_lcc=body.use_lcc)
        return TransportRouteResponse(
            ok=r["ok"],
            path=r.get("path"),
            result=r.get("result"),
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
