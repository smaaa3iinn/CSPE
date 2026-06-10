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
    exploration_overlay: dict[str, Any] | None = None


class TransportMapResponse(BaseModel):
    html: str
    mapbox_token_source: str | None = None


class TransportExplorationOverlayRequest(BaseModel):
    exploration_overlay: dict[str, Any] | None = None


class TransportExplorationOverlayResponse(BaseModel):
    exploration: dict[str, Any]
    view: dict[str, float] | None = None


class TransportRouteOverlayRequest(BaseModel):
    route_overlay: TransportMapRequest | None = None


class TransportRouteOverlayResponse(BaseModel):
    route: dict[str, Any]
    view: dict[str, float] | None = None


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
    path_legs: list[dict[str, Any]] | None = None
    path_summary: list[str] | None = None
    result: dict[str, Any] | None = None
    detail: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


class TransportGraph3DSessionRequest(BaseModel):
    mode: Literal["all", "metro", "rail", "tram", "bus", "other"] = "metro"
    use_lcc: bool = True
    graph_viz_mode: Literal["stop", "station", "hybrid"] = "stop"
    path_stop_ids: list[str] | None = None
    path_station_ids: list[str] | None = None
    selected_stop_id: str | None = None
    selected_station_id: str | None = None


class TransportGraph3DSessionResponse(BaseModel):
    session_id: str
    graph_url: str
    expires_in_s: int
    metadata: dict[str, Any]


class TransportGraph3DSyncRequest(TransportGraph3DSessionRequest):
    client_id: str = Field(..., min_length=8, max_length=128)
    fingerprint: str = Field(..., min_length=1, max_length=1024)


class TransportGraph3DSyncPushResponse(BaseModel):
    session_id: str
    fingerprint: str
    expires_in_s: int


class TransportGraph3DSyncPeekResponse(BaseModel):
    changed: bool
    session_id: str | None = None
    fingerprint: str | None = None


class TransportStatsResponse(BaseModel):
    mode: str
    use_lcc: bool
    nodes: int
    edges: int


class AgentContextPatch(BaseModel):
    ui_mode: Literal["transport"] | None = None
    transport: dict[str, Any] | None = None


class AgentEventBody(BaseModel):
    event: str = Field(..., min_length=1)
    data: dict[str, Any] = Field(default_factory=dict)
    source: str | None = "browser"


class AgentTransportRouteRequest(BaseModel):
    from_query: str = Field(..., min_length=1)
    to_query: str = Field(..., min_length=1)
    mode: Literal["all", "metro", "rail", "tram", "bus", "other"] = "metro"
    use_lcc: bool = True
    routing_scope: Literal["stop", "station"] = "station"
    station_first: bool = True
    sync_ui: bool = True
    open_graph3d: bool = False
    graph_viz_mode: Literal["stop", "station", "hybrid"] = "station"


class AgentTransportRouteResponse(BaseModel):
    ok: bool
    needs_user_choice: bool = False
    result: dict[str, Any]
    graph3d: dict[str, Any] | None = None
    shell_queued: int = 0


class AgentPlaceLookupRequest(BaseModel):
    query: str = Field(..., min_length=2)
    kind: Literal["auto", "station", "poi"] = "auto"
    near_query: str | None = None
    topic: Literal["about", "history", "hours", "accessibility", "disruptions", "reviews"] | None = "about"
    includes_today: bool = False
    mode: Literal["all", "metro", "rail", "tram", "bus", "other"] = "metro"
    use_lcc: bool = True
    station_first: bool = True


class AgentPlaceLookupResponse(BaseModel):
    ok: bool
    place_kind: str | None = None
    query: str | None = None
    near_query: str | None = None
    topic: str | None = None
    local: dict[str, Any] | None = None
    local_summary: str | None = None
    idfm_summary: str | None = None
    idfm_data: dict[str, Any] | None = None
    enrichment_source: str | None = None
    web_search_query: str | None = None
    needs_clarification: bool = False
    error: str | None = None
    candidates: list[dict[str, Any]] | None = None


class TransportExploreAreaRequest(BaseModel):
    query: str = Field(..., min_length=0)
    radius_m: int | None = Field(default=None, ge=50, le=3000)
    include_stops: bool = True
    include_pois: bool = True
    poi_categories: list[str] = Field(default_factory=lambda: ["all"])
    transport_modes: list[str] = Field(default_factory=lambda: ["all"])
    limit_stops: int = Field(default=15, ge=1, le=50)
    limit_pois: int = Field(default=20, ge=1, le=60)
    mode: Literal["all", "metro", "rail", "tram", "bus", "other"] = "metro"
    use_lcc: bool = False
    station_first: bool = True
    sync_ui: bool = True
