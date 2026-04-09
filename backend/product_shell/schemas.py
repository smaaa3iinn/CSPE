"""Request/response models for the product shell API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)


class ChatResponse(BaseModel):
    structured_outputs: list[dict[str, Any]]
    raw_ui: dict[str, Any] | None = None
    error: str | None = None


class TransportMapRequest(BaseModel):
    mode: Literal["all", "metro", "rail", "tram", "bus", "other"] = "metro"
    use_lcc: bool = True
    viz_mode: Literal["geographic", "network_3d"] = "geographic"
    path_stop_ids: list[str] | None = None
    # When set (station/hybrid map), station overlay shows only these stations and path connectors
    path_station_ids: list[str] | None = None
    selected_stop_id: str | None = None
    selected_station_id: str | None = None
    show_transfers: bool = False
    poi_radius_m: int = Field(default=300, ge=100, le=1000)
    poi_limit: int = Field(default=25, ge=5, le=200)
    poi_category_key: str | None = None  # "All" or amenity/shop/tourism/leisure
    # Stop graph vs station overlay vs both (routing always uses underlying stop graph)
    graph_viz_mode: Literal["stop", "station", "hybrid"] = "stop"
    expanded_station_id: str | None = None


class TransportMapResponse(BaseModel):
    html: str
    mapbox_token_source: str | None = None


class TransportRouteRequest(BaseModel):
    """Either stop endpoints (from_stop_id + to_stop_id) or station endpoints (from_station_id + to_station_id)."""

    mode: Literal["all", "metro", "rail", "tram", "bus", "other"] = "metro"
    use_lcc: bool = True
    from_stop_id: str | None = None
    to_stop_id: str | None = None
    from_station_id: str | None = None
    to_station_id: str | None = None


class TransportRouteResponse(BaseModel):
    ok: bool
    routing_scope: Literal["stop", "station"] | None = None
    path: list[str] | None = None
    station_path: list[str] | None = None
    station_names: list[str] | None = None
    result: dict[str, Any] | None = None
    detail: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


class TransportStatsResponse(BaseModel):
    mode: str
    use_lcc: bool
    nodes: int
    edges: int


class MemoryProject(BaseModel):
    id: str
    name: str
    count: int | None = None
    done_count: int | None = None
    created_at: str | None = None
    updated_at: str | None = None


class MemoryProjectsResponse(BaseModel):
    projects: list[MemoryProject]


class MemoryProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)


class MemoryProjectPatch(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)


class MemoryTaskItem(BaseModel):
    id: str
    title: str
    status: Literal["todo", "in_progress", "done"] = "todo"
    done: bool = False
    tags: list[str] = Field(default_factory=list)
    due_at: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class MemoryTasksResponse(BaseModel):
    project_id: str
    tasks: list[MemoryTaskItem]


class MemoryTaskCreate(BaseModel):
    project_id: str
    title: str = Field(..., min_length=1, max_length=2000)
    status: Literal["todo", "in_progress", "done"] = "todo"


class MemoryTaskPatch(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=2000)
    status: Literal["todo", "in_progress", "done"] | None = None
