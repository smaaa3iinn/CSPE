"""Shared agent world state, UI snapshots, and event log for Atlas planner feedback."""

from __future__ import annotations

import threading
import time
import uuid
from collections import deque
from typing import Any

_lock = threading.Lock()
_MAX_EVENTS = 500
_events: deque[dict[str, Any]] = deque(maxlen=_MAX_EVENTS)

_world_state: dict[str, Any] = {
    "ui_mode": "transport",
    "transport": {},
    "last_shell_commands": [],
    "updated_at": None,
}

_pending_tasks: dict[str, dict[str, Any]] = {}


def utc_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def get_context() -> dict[str, Any]:
    with _lock:
        return {
            "world": dict(_world_state),
            "recent_events": list(_events)[-20:],
            "pending_tasks": list(_pending_tasks.values())[-10:],
            "capabilities": {
                "transport": [
                    "search_stops",
                    "nearby_stops",
                    "nearby_pois",
                    "explore_area",
                    "filter_results",
                    "compute_route",
                    "map",
                    "graph3d",
                ],
                "ui": ["set_mode", "transport_action", "structured_outputs"],
                "search": ["place_lookup_online"],
            },
        }


def patch_world_state(patch: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        for k, v in patch.items():
            if k == "transport" and isinstance(v, dict):
                cur = _world_state.get("transport")
                if not isinstance(cur, dict):
                    cur = {}
                cur.update(v)
                _world_state["transport"] = cur
            else:
                _world_state[k] = v
        _world_state["updated_at"] = utc_iso()
        return dict(_world_state)


def record_event(event: str, data: dict[str, Any] | None = None, *, source: str = "unknown") -> dict[str, Any]:
    entry = {
        "id": str(uuid.uuid4()),
        "event": event,
        "source": source,
        "data": data or {},
        "ts": utc_iso(),
    }
    with _lock:
        _events.append(entry)
    return entry


def recent_events(*, since_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    with _lock:
        items = list(_events)
    if since_id:
        idx = next((i for i, e in enumerate(items) if e.get("id") == since_id), -1)
        if idx >= 0:
            items = items[idx + 1 :]
    return items[-limit:]


def register_task(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    task_id = str(uuid.uuid4())
    task = {
        "id": task_id,
        "kind": kind,
        "status": "pending",
        "payload": payload,
        "created_at": utc_iso(),
        "updated_at": utc_iso(),
    }
    with _lock:
        _pending_tasks[task_id] = task
    return task


def update_task(task_id: str, **fields: Any) -> dict[str, Any] | None:
    with _lock:
        task = _pending_tasks.get(task_id)
        if not task:
            return None
        task.update(fields)
        task["updated_at"] = utc_iso()
        return dict(task)


def complete_task(task_id: str, result: dict[str, Any] | None = None) -> dict[str, Any] | None:
    return update_task(task_id, status="done", result=result or {})
