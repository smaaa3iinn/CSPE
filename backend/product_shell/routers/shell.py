"""Queued commands from Atlas tools → React shell (polled by the browser)."""

from __future__ import annotations

import json
import queue
import threading
import time
from collections import deque
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.product_shell import ui_transport_logger as ui_log

router = APIRouter(tags=["shell"])

_MAX = 256
_lock = threading.Lock()
_queue: deque[dict[str, Any]] = deque(maxlen=_MAX)
_sse_subscribers: list[queue.Queue[str]] = []


class ShellEnqueueBody(BaseModel):
    commands: list[dict[str, Any]] = Field(..., min_length=1)


def enqueue_commands(commands: list[dict[str, Any]]) -> int:
    """Append shell commands (used by Atlas tools and agent composite actions)."""
    n = 0
    batch: list[dict[str, Any]] = []
    with _lock:
        for c in commands:
            if isinstance(c, dict) and c.get("kind"):
                cc = dict(c)
                _queue.append(cc)
                batch.append(cc)
                n += 1
                k = cc.get("kind")
                if k == "atlas_transport_intent":
                    ui_log.log_atlas_transport_intent_enqueued(cc)
                elif k == "atlas_transport_action":
                    ui_log.log_atlas_transport_action_enqueued(cc)
                elif k == "transport_exploration_view":
                    ui_log.log_exploration_shell_enqueue(cc)
        subs = list(_sse_subscribers)
    if batch and subs:
        payload = json.dumps({"commands": batch}, default=str)
        for q in subs:
            try:
                q.put_nowait(payload)
            except queue.Full:
                pass
    return n


@router.post("/shell/enqueue")
def shell_enqueue(body: ShellEnqueueBody) -> dict[str, Any]:
    """Atlas (or tests) POSTs UI commands; the product UI polls and applies them."""
    n = enqueue_commands(body.commands)
    return {"ok": True, "queued": n}


class ShellClientLogBody(BaseModel):
    event: str = Field(..., min_length=1)
    data: dict[str, Any] = Field(default_factory=dict)


@router.post("/shell/client-log")
def shell_client_log(body: ShellClientLogBody) -> dict[str, Any]:
    """Browser posts structured Atlas transport pipeline milestones to logs/activity.log."""
    ui_log.log_atlas_transport_client_event(body.event, body.data)
    return {"ok": True}


@router.get("/shell/poll")
def shell_poll() -> dict[str, Any]:
    """Return and drain all pending commands (single consumer — the open browser)."""
    with _lock:
        cmds = list(_queue)
        _queue.clear()
    return {"commands": cmds}


@router.get("/shell/stream")
def shell_stream() -> StreamingResponse:
    """Server-Sent Events stream of shell commands (alternative to polling)."""

    def _gen():
        q: queue.Queue[str] = queue.Queue(maxsize=64)
        with _lock:
            _sse_subscribers.append(q)
        try:
            yield "event: connected\ndata: {}\n\n"
            while True:
                try:
                    payload = q.get(timeout=25.0)
                    yield f"event: commands\ndata: {payload}\n\n"
                except queue.Empty:
                    yield ": keepalive\n\n"
        finally:
            with _lock:
                try:
                    _sse_subscribers.remove(q)
                except ValueError:
                    pass

    return StreamingResponse(_gen(), media_type="text/event-stream")
