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
    AgentTransportRouteRequest,
    AgentTransportRouteResponse,
)
from backend.product_shell.services import agent_store, agent_tools

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
    result = agent_tools.compute_route_from_queries(
        body.from_query,
        body.to_query,
        mode=body.mode,
        use_lcc=body.use_lcc,
        routing_scope=body.routing_scope,
        station_first=body.station_first,
    )

    graph3d = None
    shell_queued = 0

    if result.get("ok") and body.sync_ui:
        cmds = agent_tools.shell_commands_for_route(result)
        shell_queued = shell_router.enqueue_commands(cmds)

    if result.get("ok") and body.open_graph3d:
        graph3d = agent_tools.create_graph3d_for_route(
            result,
            mode=body.mode,
            use_lcc=body.use_lcc,
            graph_viz_mode=body.graph_viz_mode,
        )

    return AgentTransportRouteResponse(
        ok=bool(result.get("ok")),
        needs_user_choice=bool(result.get("needs_user_choice")),
        result=result,
        graph3d=graph3d,
        shell_queued=shell_queued,
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
