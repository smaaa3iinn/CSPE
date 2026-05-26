"""Queued commands from Atlas tools → React shell (polled by the browser)."""

from __future__ import annotations

import threading
from collections import deque
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from backend.product_shell import ui_transport_logger as ui_log

router = APIRouter(tags=["shell"])

_MAX = 256
_lock = threading.Lock()
_queue: deque[dict[str, Any]] = deque(maxlen=_MAX)


class ShellEnqueueBody(BaseModel):
    commands: list[dict[str, Any]] = Field(..., min_length=1)


@router.post("/shell/enqueue")
def shell_enqueue(body: ShellEnqueueBody) -> dict[str, Any]:
    """Atlas (or tests) POSTs UI commands; the product UI polls and applies them."""
    n = 0
    with _lock:
        for c in body.commands:
            if isinstance(c, dict) and c.get("kind"):
                cc = dict(c)
                _queue.append(cc)
                n += 1
                k = cc.get("kind")
                if k == "atlas_transport_intent":
                    ui_log.log_atlas_transport_intent_enqueued(cc)
                elif k == "atlas_transport_action":
                    ui_log.log_atlas_transport_action_enqueued(cc)
    return {"ok": True, "queued": n}


class ShellClientLogBody(BaseModel):
    event: str = Field(..., min_length=1)
    data: dict[str, Any] = Field(default_factory=dict)


@router.post("/shell/client-log")
def shell_client_log(body: ShellClientLogBody) -> dict[str, Any]:
    """Browser posts structured Atlas transport pipeline milestones to product_ui_transport.log."""
    ui_log.log_atlas_transport_client_event(body.event, body.data)
    return {"ok": True}


@router.get("/shell/poll")
def shell_poll() -> dict[str, Any]:
    """Return and drain all pending commands (single consumer — the open browser)."""
    with _lock:
        cmds = list(_queue)
        _queue.clear()
    return {"commands": cmds}
