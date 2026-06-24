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
from src.core.project_logs import generate_correlation_id, log_compact_line

router = APIRouter(tags=["shell"])

_MAX = 256
_lock = threading.Lock()
_queue: deque[dict[str, Any]] = deque(maxlen=_MAX)
_sse_subscribers: list[queue.Queue[str]] = []
_total_enqueued = 0

_turn_local = threading.local()


class ShellEnqueueBody(BaseModel):
    commands: list[dict[str, Any]] = Field(..., min_length=1)


def begin_turn_capture(command_id: str | None = None) -> str:
    """Start collecting shell commands enqueued during one `/api/chat` turn."""
    cid = (command_id or "").strip() or generate_correlation_id()
    _turn_local.capture_id = cid
    _turn_local.commands: list[dict[str, Any]] = []
    return cid


def end_turn_capture() -> dict[str, Any] | None:
    """Return captured commands for inline delivery; clears turn capture state."""
    cid = getattr(_turn_local, "capture_id", None)
    cmds = getattr(_turn_local, "commands", None) or []
    _turn_local.capture_id = None
    _turn_local.commands = []
    if not cmds:
        return None
    return {"command_id": str(cid or generate_correlation_id()), "commands": list(cmds)}


def is_turn_capture_active() -> bool:
    return bool(getattr(_turn_local, "capture_id", None))


def enqueue_commands(commands: list[dict[str, Any]]) -> int:
    """Append shell commands (used by Atlas tools and agent composite actions)."""
    global _total_enqueued
    n = 0
    batch: list[dict[str, Any]] = []
    with _lock:
        subs = list(_sse_subscribers)
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
        _total_enqueued += n
        pending_after = len(_queue)

    if batch:
        kinds = ",".join(str(c.get("kind") or "?") for c in batch)
        log_compact_line(
            f"[UICommand] phase=enqueued count={len(batch)} pending={pending_after} kinds={kinds}"
        )

    capture_id = getattr(_turn_local, "capture_id", None)
    if capture_id and batch:
        turn_cmds = getattr(_turn_local, "commands", None)
        if turn_cmds is not None:
            turn_cmds.extend(batch)
        kinds = ",".join(str(c.get("kind") or "?") for c in batch)
        log_compact_line(
            f"[UICommand] phase=captured cid={capture_id} count={len(batch)} kinds={kinds}"
        )

    if batch and subs:
        payload = json.dumps({"commands": batch}, default=str)
        for q in subs:
            try:
                q.put_nowait(payload)
            except queue.Full:
                try:
                    q.get_nowait()
                except queue.Empty:
                    pass
                try:
                    q.put_nowait(payload)
                except queue.Full:
                    ui_log.log_atlas_transport_client_event(
                        "shell_sse_queue_drop",
                        {"dropped_commands": len(batch)},
                    )
    return n


def shell_stats() -> dict[str, Any]:
    with _lock:
        return {"pending": len(_queue), "total_enqueued": _total_enqueued}


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


@router.get("/shell/stats")
def shell_stats_route() -> dict[str, Any]:
    """Current shell queue counters for first-turn diagnostics."""
    return shell_stats()


@router.get("/shell/stream")
def shell_stream() -> StreamingResponse:
    """Server-Sent Events stream of shell commands (alternative to polling)."""

    def _gen():
        q: queue.Queue[str] = queue.Queue(maxsize=64)
        with _lock:
            _sse_subscribers.append(q)
            if _queue:
                pending = list(_queue)
                _queue.clear()
                try:
                    q.put_nowait(json.dumps({"commands": pending}, default=str))
                except queue.Full:
                    pass
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
