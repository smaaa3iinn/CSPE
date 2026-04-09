"""Proxy Atlas session mode + /ui for the product shell (voice vs text)."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.product_shell.services.atlas_http import ensure_atlas_session_mode, fetch_atlas_ui
from backend.product_shell.services.normalize import normalize_atlas_ui

router = APIRouter(tags=["atlas"])


class AtlasInputModeBody(BaseModel):
    mode: Literal["text", "voice"] = Field(..., description="Atlas input mode: typed /text vs microphone realtime")


@router.post("/atlas/input-mode")
def post_atlas_input_mode(body: AtlasInputModeBody) -> dict[str, Any]:
    ok, err = ensure_atlas_session_mode(body.mode)
    if not ok:
        raise HTTPException(status_code=503, detail=err)
    return {"ok": True, "mode": body.mode}


@router.get("/atlas/ui")
def get_atlas_ui() -> dict[str, Any]:
    try:
        ui = fetch_atlas_ui()
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    return {"ui": ui, "structured_outputs": normalize_atlas_ui(ui)}
