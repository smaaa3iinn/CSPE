"""Agent context, events, and server-side composite actions for Atlas planner."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from backend.product_shell import ui_transport_logger as ui_log
from backend.product_shell.routers import shell as shell_router
from backend.product_shell.schemas import (
    AgentContextPatch,
    AgentEventBody,
    AgentPlaceLookupRequest,
    AgentPlaceLookupResponse,
    AgentTransportRouteRequest,
    AgentTransportRouteResponse,
)
from backend.product_shell.services import agent_store, agent_tools
from src.core.project_logs import log_compact_line

router = APIRouter(tags=["agent"])


@router.get("/agent/context")
def get_agent_context() -> dict[str, Any]:
    return agent_store.get_context()


@router.patch("/agent/context")
def patch_agent_context(body: AgentContextPatch) -> dict[str, Any]:
    patch = body.model_dump(exclude_none=True)
    world = agent_store.patch_world_state(patch)
    return {"ok": True, "world": world}


@router.post("/agent/events")
def post_agent_event(body: AgentEventBody) -> dict[str, Any]:
    entry = agent_store.record_event(body.event, body.data, source=body.source or "browser")
    try:
        ui_log.log_atlas_transport_client_event(f"agent.{body.event}", body.data)
    except Exception:
        pass
    return {"ok": True, "event": entry}


@router.get("/agent/events")
def get_agent_events(
    since_id: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    return {"events": agent_store.recent_events(since_id=since_id, limit=limit)}


@router.post("/agent/transport/route", response_model=AgentTransportRouteResponse)
def post_agent_transport_route(body: AgentTransportRouteRequest) -> AgentTransportRouteResponse:
    """Resolve stop names, compute route server-side, optionally sync UI and create 3D session."""
    route_mode, route_use_lcc = agent_store.active_transport_prefs(
        fallback_mode=body.mode,
        fallback_lcc=body.use_lcc,
    )
    result = agent_tools.compute_route_from_queries(
        body.from_query,
        body.to_query,
        mode=route_mode,
        use_lcc=route_use_lcc,
        routing_scope=body.routing_scope,
        station_first=body.station_first,
    )

    graph3d = None
    shell_queued = 0

    if body.sync_ui:
        cmds = agent_tools.shell_commands_for_route(result)
        shell_queued = shell_router.enqueue_commands(cmds)

    if result.get("ok") and body.open_graph3d:
        graph3d = agent_tools.create_graph3d_for_route(
            result,
            mode=route_mode,
            use_lcc=route_use_lcc,
            graph_viz_mode=body.graph_viz_mode,
        )
        if graph3d.get("ok") and graph3d.get("sync_client_id"):
            shell_queued += shell_router.enqueue_commands(
                [
                    {
                        "kind": "transport_graph3d_sync",
                        "sync_client_id": graph3d["sync_client_id"],
                        "enabled": True,
                    }
                ]
            )

    return AgentTransportRouteResponse(
        ok=bool(result.get("ok")),
        needs_user_choice=bool(result.get("needs_user_choice")),
        result=result,
        graph3d=graph3d,
        shell_queued=shell_queued,
    )


@router.post("/agent/transport/place-lookup", response_model=AgentPlaceLookupResponse)
def post_agent_place_lookup(body: AgentPlaceLookupRequest) -> AgentPlaceLookupResponse:
    """Resolve a station or POI locally and build a web-search query. Chat-only; no map sync."""
    result = agent_tools.lookup_place_for_chat(
        body.query,
        kind=body.kind,
        near_query=body.near_query,
        topic=body.topic,
        includes_today=body.includes_today,
        mode=body.mode,
        use_lcc=body.use_lcc,
        station_first=body.station_first,
    )
    if result.get("ok"):
        local = result.get("local") if isinstance(result.get("local"), dict) else {}
        agent_store.patch_world_state(
            {
                "transport": {
                    "last_place_lookup": {
                        "query": result.get("query") or body.query,
                        "place_kind": result.get("place_kind"),
                        "topic": result.get("topic") or body.topic,
                        "label": local.get("label") or result.get("query") or body.query,
                    }
                }
            }
        )
        log_compact_line(
            "[PlaceLookup] "
            f"query={body.query!r} near={result.get('near_query')!r} "
            f"source={result.get('enrichment_source')!r} "
            f"web={result.get('web_search_query')!r}"
        )
        if result.get("idfm_summary"):
            log_compact_line(f"[PlaceLookup] idfm_summary_chars={len(str(result.get('idfm_summary') or ''))}")
    elif result.get("needs_clarification"):
        log_compact_line(f"[PlaceLookup] needs_context query={body.query!r} error={result.get('error')!r}")
    return AgentPlaceLookupResponse(
        ok=bool(result.get("ok")),
        place_kind=result.get("place_kind"),
        query=result.get("query"),
        near_query=result.get("near_query"),
        topic=result.get("topic"),
        local=result.get("local"),
        local_summary=result.get("local_summary"),
        idfm_summary=result.get("idfm_summary"),
        idfm_data=result.get("idfm_data"),
        enrichment_source=result.get("enrichment_source"),
        web_search_query=result.get("web_search_query"),
        needs_clarification=bool(result.get("needs_clarification")),
        error=result.get("error"),
        candidates=result.get("candidates"),
    )


class AgentTaskRegisterBody(BaseModel):
    kind: str = Field(..., min_length=1)
    payload: dict[str, Any] = Field(default_factory=dict)


@router.post("/agent/tasks")
def post_agent_task(body: AgentTaskRegisterBody) -> dict[str, Any]:
    task = agent_store.register_task(body.kind, body.payload)
    return {"ok": True, "task": task}


@router.get("/agent/tasks/{task_id}")
def get_agent_task(task_id: str) -> dict[str, Any]:
    ctx = agent_store.get_context()
    for t in ctx.get("pending_tasks") or []:
        if t.get("id") == task_id:
            return {"ok": True, "task": t}
    return {"ok": False, "error": "task not found"}
