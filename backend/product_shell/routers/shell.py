"""Queued commands from Atlas tools → React shell (polled by the browser)."""

from __future__ import annotations

import threading
from collections import deque
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

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
                _queue.append(dict(c))
                n += 1
    return {"ok": True, "queued": n}


@router.get("/shell/poll")
def shell_poll() -> dict[str, Any]:
    """Return and drain all pending commands (single consumer — the open browser)."""
    with _lock:
        cmds = list(_queue)
        _queue.clear()
    return {"commands": cmds}
