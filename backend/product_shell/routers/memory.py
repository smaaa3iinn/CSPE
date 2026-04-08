from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from backend.product_shell.schemas import MemoryProjectsResponse, MemoryTasksResponse, MemoryTaskItem, MemoryProject

router = APIRouter(tags=["memory"])

# Placeholder data until memory service is wired to real storage.
_PROJECTS: list[MemoryProject] = [
    MemoryProject(id="atlas", name="Project ATLAS"),
    MemoryProject(id="university", name="Project University"),
    MemoryProject(id="personal", name="Personal"),
]

_TASKS: dict[str, list[MemoryTaskItem]] = {
    "atlas": [
        MemoryTaskItem(id="a1", title="Structured UI payload contract", done=True),
        MemoryTaskItem(id="a2", title="Headless Atlas session bridge", done=False),
    ],
    "university": [
        MemoryTaskItem(id="u1", title="Literature review outline", done=False),
        MemoryTaskItem(id="u2", title="Experiment notes", done=True),
    ],
    "personal": [
        MemoryTaskItem(id="p1", title="Follow up on migration plan", done=False),
    ],
}


@router.get("/memory/projects", response_model=MemoryProjectsResponse)
def list_projects() -> MemoryProjectsResponse:
    return MemoryProjectsResponse(projects=_PROJECTS)


@router.get("/memory/tasks", response_model=MemoryTasksResponse)
def list_tasks(project_id: str = Query(..., min_length=1)) -> MemoryTasksResponse:
    if project_id not in _TASKS:
        raise HTTPException(status_code=404, detail="Unknown project")
    return MemoryTasksResponse(project_id=project_id, tasks=_TASKS[project_id])
