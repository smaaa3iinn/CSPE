from __future__ import annotations

import time
from typing import Any, Literal, cast

from fastapi import APIRouter

from backend.product_shell.schemas import ChatRequest, ChatResponse, UiCommandBatch
from backend.product_shell.display_session import enrich_ui_command_batch
from backend.product_shell.routers import shell as shell_router
from backend.product_shell.services.atlas_http import send_text_and_wait
from backend.product_shell.services.normalize import normalize_atlas_ui
from src.core.project_logs import generate_correlation_id, log_compact_line

router = APIRouter(tags=["chat"])


def _command_id_from_ui(ui: dict[str, Any] | None) -> str | None:
    if not isinstance(ui, dict):
        return None
    for key in ("correlation_id", "turn_correlation_id", "turn_id"):
        raw = ui.get(key)
        if raw is not None and str(raw).strip():
            return str(raw).strip()
    return None


@router.post("/chat", response_model=ChatResponse)
def post_chat(body: ChatRequest) -> ChatResponse:
    t0 = time.perf_counter()
    shell_before = shell_router.shell_stats()
    command_id = shell_router.begin_turn_capture(generate_correlation_id())
    ui: dict[str, Any] = {}
    err: str | None = None
    try:
        ui, err = send_text_and_wait(body.message)
    finally:
        turn_batch = shell_router.end_turn_capture()
        atlas_cid = _command_id_from_ui(ui)
        if turn_batch and atlas_cid:
            turn_batch["command_id"] = atlas_cid
        elif turn_batch and not turn_batch.get("command_id"):
            turn_batch["command_id"] = command_id

    shell_after = shell_router.shell_stats()
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    enqueued_delta = int(shell_after.get("total_enqueued") or 0) - int(
        shell_before.get("total_enqueued") or 0
    )
    pending = int(shell_after.get("pending") or 0)

    ui_commands: UiCommandBatch | None = None
    ui_sync: Literal["inline", "queued", "none"] = "none"
    if turn_batch and turn_batch.get("commands"):
        enriched = enrich_ui_command_batch(turn_batch, source="atlas_chat", target="active_display")
        assert enriched is not None
        ui_commands = UiCommandBatch(
            command_id=str(enriched["command_id"]),
            commands=list(enriched["commands"]),
            session_id=enriched.get("session_id"),
            target=enriched.get("target") or "active_display",
            source=enriched.get("source") or "atlas_chat",
            created_at=enriched.get("created_at"),
        )
        ui_sync = "inline"
        kinds = ",".join(
            str(c.get("kind") or "?") for c in ui_commands.commands[:8]
        )
        log_compact_line(
            f"[UICommand] phase=chat_inline cid={ui_commands.command_id} "
            f"target={ui_commands.target} count={len(ui_commands.commands)} kinds={kinds}"
        )
    elif enqueued_delta > 0:
        ui_sync = "queued"
        log_compact_line(
            f"[UICommand] phase=chat_queued_only cid={command_id} "
            f"enqueued_delta={enqueued_delta} pending={pending} "
            "detail=commands_enqueued_without_turn_capture"
        )

    log_compact_line(
        "[Chat] product_chat_return "
        f"elapsed_ms={elapsed_ms:.0f} shell_enqueued_delta={enqueued_delta} "
        f"shell_pending={pending} ui_sync={ui_sync} "
        f"inline_cmds={len(ui_commands.commands) if ui_commands else 0} error={bool(err)}"
    )

    if pending > 0 and ui_sync == "inline":
        log_compact_line(
            f"[UICommand] WARN shell_pending={pending} after inline delivery — "
            "poll/SSE may still drain duplicate batches"
        )
    elif pending > 0 and ui_sync != "inline":
        log_compact_line(
            f"[UICommand] WARN possible_ui_sync_gap shell_pending={pending} "
            f"inline_cmds=0 enqueued_delta={enqueued_delta}"
        )

    structured = normalize_atlas_ui(ui)
    if err:
        structured = [
            *structured,
            {"type": "system_status", "level": "error", "message": err},
        ]
    return ChatResponse(
        structured_outputs=structured,
        raw_ui=ui if ui else None,
        error=err,
        ui_commands=ui_commands,
        ui_sync=cast(Literal["inline", "queued", "none"], ui_sync),
    )
