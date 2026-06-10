from __future__ import annotations

import time

from fastapi import APIRouter

from backend.product_shell.schemas import ChatRequest, ChatResponse
from backend.product_shell.routers import shell as shell_router
from backend.product_shell.services.atlas_http import send_text_and_wait
from backend.product_shell.services.normalize import normalize_atlas_ui
from src.core.project_logs import log_compact_line

router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def post_chat(body: ChatRequest) -> ChatResponse:
    t0 = time.perf_counter()
    shell_before = shell_router.shell_stats()
    ui, err = send_text_and_wait(body.message)
    shell_after = shell_router.shell_stats()
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    enqueued_delta = int(shell_after.get("total_enqueued") or 0) - int(
        shell_before.get("total_enqueued") or 0
    )
    log_compact_line(
        "[Chat] product_chat_return "
        f"elapsed_ms={elapsed_ms:.0f} shell_enqueued_delta={enqueued_delta} "
        f"shell_pending={shell_after.get('pending')} error={bool(err)}"
    )
    structured = normalize_atlas_ui(ui)
    if err:
        structured = [
            *structured,
            {"type": "system_status", "level": "error", "message": err},
        ]
    return ChatResponse(structured_outputs=structured, raw_ui=ui if ui else None, error=err)
