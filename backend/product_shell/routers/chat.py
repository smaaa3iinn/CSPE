from __future__ import annotations

from fastapi import APIRouter

from backend.product_shell.schemas import ChatRequest, ChatResponse
from backend.product_shell.services.atlas_http import send_text_and_wait
from backend.product_shell.services.normalize import normalize_atlas_ui

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def post_chat(body: ChatRequest) -> ChatResponse:
    ui, err = send_text_and_wait(body.message)
    structured = normalize_atlas_ui(ui)
    if err:
        structured = [
            *structured,
            {"type": "system_status", "level": "error", "message": err},
        ]
    return ChatResponse(structured_outputs=structured, raw_ui=ui if ui else None, error=err)
