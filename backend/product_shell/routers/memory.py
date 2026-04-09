from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from backend.product_shell.schemas import (
    MemoryProject,
    MemoryProjectCreate,
    MemoryProjectPatch,
    MemoryProjectsResponse,
    MemoryTaskCreate,
    MemoryTaskItem,
    MemoryTaskPatch,
    MemoryTasksResponse,
)
from backend.product_shell.services import product_memory_store as pmem

router = APIRouter(tags=["memory"])


def _parse_id(s: str, label: str) -> int:
    s = (s or "").strip()
    if not s.isdigit():
        raise HTTPException(status_code=400, detail=f"Invalid {label}")
    return int(s)


def _to_project(m: dict) -> MemoryProject:
    return MemoryProject(
        id=m["id"],
        name=m["name"],
        count=m.get("count"),
        done_count=m.get("done_count"),
        created_at=m.get("created_at"),
        updated_at=m.get("updated_at"),
    )


def _to_task(m: dict) -> MemoryTaskItem:
    st = m["status"]
    return MemoryTaskItem(
        id=m["id"],
        title=m["title"],
        status=st,
        done=st == "done",
        tags=m.get("tags") or [],
        due_at=m.get("due_at"),
        created_at=m.get("created_at"),
        updated_at=m.get("updated_at"),
    )


@router.get("/memory/projects", response_model=MemoryProjectsResponse)
def list_projects() -> MemoryProjectsResponse:
    raw = pmem.list_projects()
    return MemoryProjectsResponse(projects=[_to_project(p) for p in raw])


@router.post("/memory/projects", response_model=MemoryProject)
def create_project(body: MemoryProjectCreate) -> MemoryProject:
    try:
        m = pmem.create_project(body.name)
        return _to_project(m)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.patch("/memory/projects/{project_id}", response_model=MemoryProject)
def patch_project(project_id: str, body: MemoryProjectPatch) -> MemoryProject:
    pid = _parse_id(project_id, "project id")
    try:
        m = pmem.update_project(pid, body.name)
        return _to_project(m)
    except KeyError:
        raise HTTPException(status_code=404, detail="Project not found") from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/memory/projects/{project_id}")
def delete_project(project_id: str) -> dict:
    pid = _parse_id(project_id, "project id")
    try:
        pmem.delete_project(pid)
        return {"ok": True}
    except KeyError:
        raise HTTPException(status_code=404, detail="Project not found") from None


@router.get("/memory/tasks", response_model=MemoryTasksResponse)
def list_tasks(project_id: str = Query(..., min_length=1)) -> MemoryTasksResponse:
    pid = _parse_id(project_id, "project_id")
    try:
        raw = pmem.list_items(pid)
    except KeyError:
        raise HTTPException(status_code=404, detail="Project not found") from None
    return MemoryTasksResponse(project_id=str(pid), tasks=[_to_task(t) for t in raw])


@router.post("/memory/tasks", response_model=MemoryTaskItem)
def create_task(body: MemoryTaskCreate) -> MemoryTaskItem:
    pid = _parse_id(body.project_id, "project_id")
    try:
        m = pmem.create_item(pid, body.title, body.status)
        return _to_task(m)
    except KeyError:
        raise HTTPException(status_code=404, detail="Project not found") from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.patch("/memory/tasks/{task_id}", response_model=MemoryTaskItem)
def patch_task(task_id: str, body: MemoryTaskPatch) -> MemoryTaskItem:
    tid = _parse_id(task_id, "task id")
    if body.title is None and body.status is None:
        raise HTTPException(status_code=400, detail="Nothing to update")
    try:
        m = pmem.update_item(tid, title=body.title, status=body.status)
        return _to_task(m)
    except KeyError:
        raise HTTPException(status_code=404, detail="Task not found") from None
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.delete("/memory/tasks/{task_id}")
def delete_task(task_id: str) -> dict:
    tid = _parse_id(task_id, "task id")
    try:
        pmem.delete_item(tid)
        return {"ok": True}
    except KeyError:
        raise HTTPException(status_code=404, detail="Task not found") from None
