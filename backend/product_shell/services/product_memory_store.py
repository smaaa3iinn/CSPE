"""
Local SQLite for product-shell projects and tasks (separate from Atlas memory_items).
Path: <repo>/data/product_memory.sqlite
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

_REPO = Path(__file__).resolve().parents[3]
DB_PATH = _REPO / "data" / "product_memory.sqlite"

Status = Literal["todo", "in_progress", "done"]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@contextmanager
def _conn():
    _REPO.joinpath("data").mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    c.row_factory = sqlite3.Row
    try:
        c.execute("PRAGMA foreign_keys = ON")
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def init_db() -> None:
    with _conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS project_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'todo'
                    CHECK (status IN ('todo', 'in_progress', 'done')),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_project_items_project ON project_items(project_id);
            """
        )


def list_projects() -> list[dict[str, Any]]:
    init_db()
    with _conn() as c:
        rows = c.execute(
            """
            SELECT p.id, p.name, p.created_at, p.updated_at,
                   COUNT(i.id) AS item_count,
                   SUM(CASE WHEN i.status = 'done' THEN 1 ELSE 0 END) AS done_count
            FROM projects p
            LEFT JOIN project_items i ON i.project_id = p.id
            GROUP BY p.id
            ORDER BY lower(p.name)
            """
        ).fetchall()
        return [
            {
                "id": str(r["id"]),
                "name": r["name"],
                "count": int(r["item_count"]),
                "done_count": int(r["done_count"] or 0),
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]


def create_project(name: str) -> dict[str, Any]:
    init_db()
    n = (name or "").strip()
    if not n:
        raise ValueError("Project name is required")
    now = _utc_now()
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO projects (name, created_at, updated_at) VALUES (?, ?, ?)",
            (n, now, now),
        )
        pid = cur.lastrowid
    return get_project(pid)


def _done_count(project_id: int) -> int:
    with _conn() as c:
        r = c.execute(
            "SELECT COUNT(*) AS n FROM project_items WHERE project_id = ? AND status = 'done'",
            (project_id,),
        ).fetchone()
    return int(r["n"]) if r else 0


def get_project(project_id: int) -> dict[str, Any]:
    init_db()
    with _conn() as c:
        r = c.execute(
            "SELECT id, name, created_at, updated_at FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()
    if not r:
        raise KeyError("project not found")
    cnt = _item_count(project_id)
    dn = _done_count(project_id)
    return {
        "id": str(r["id"]),
        "name": r["name"],
        "count": cnt,
        "done_count": dn,
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }


def _item_count(project_id: int) -> int:
    with _conn() as c:
        r = c.execute(
            "SELECT COUNT(*) AS n FROM project_items WHERE project_id = ?",
            (project_id,),
        ).fetchone()
    return int(r["n"]) if r else 0


def update_project(project_id: int, name: str) -> dict[str, Any]:
    n = (name or "").strip()
    if not n:
        raise ValueError("Project name is required")
    now = _utc_now()
    with _conn() as c:
        cur = c.execute(
            "UPDATE projects SET name = ?, updated_at = ? WHERE id = ?",
            (n, now, project_id),
        )
        if cur.rowcount == 0:
            raise KeyError("project not found")
    return get_project(project_id)


def delete_project(project_id: int) -> None:
    init_db()
    with _conn() as c:
        cur = c.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        if cur.rowcount == 0:
            raise KeyError("project not found")


def list_items(project_id: int) -> list[dict[str, Any]]:
    init_db()
    with _conn() as c:
        ok = c.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not ok:
            raise KeyError("project not found")
        rows = c.execute(
            """
            SELECT id, project_id, title, status, created_at, updated_at
            FROM project_items
            WHERE project_id = ?
            ORDER BY
                CASE status
                    WHEN 'todo' THEN 0
                    WHEN 'in_progress' THEN 1
                    WHEN 'done' THEN 2
                END,
                datetime(created_at) DESC
            """,
            (project_id,),
        ).fetchall()
    out = []
    for r in rows:
        st = r["status"]
        out.append(
            {
                "id": str(r["id"]),
                "project_id": str(r["project_id"]),
                "title": r["title"],
                "status": st,
                "done": st == "done",
                "tags": [],
                "due_at": None,
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
            }
        )
    return out


def create_item(project_id: int, title: str, status: Status = "todo") -> dict[str, Any]:
    init_db()
    t = (title or "").strip()
    if not t:
        raise ValueError("Title is required")
    if status not in ("todo", "in_progress", "done"):
        raise ValueError("Invalid status")
    now = _utc_now()
    with _conn() as c:
        ok = c.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone()
        if not ok:
            raise KeyError("project not found")
        cur = c.execute(
            """
            INSERT INTO project_items (project_id, title, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (project_id, t, status, now, now),
        )
        iid = cur.lastrowid
    return get_item(iid)


def get_item(item_id: int) -> dict[str, Any]:
    init_db()
    with _conn() as c:
        r = c.execute(
            """
            SELECT id, project_id, title, status, created_at, updated_at
            FROM project_items WHERE id = ?
            """,
            (item_id,),
        ).fetchone()
    if not r:
        raise KeyError("item not found")
    st = r["status"]
    return {
        "id": str(r["id"]),
        "project_id": str(r["project_id"]),
        "title": r["title"],
        "status": st,
        "done": st == "done",
        "tags": [],
        "due_at": None,
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
    }


def update_item(
    item_id: int,
    *,
    title: str | None = None,
    status: Status | None = None,
) -> dict[str, Any]:
    init_db()
    now = _utc_now()
    parts: list[str] = []
    params: list[Any] = []
    if title is not None:
        t = title.strip()
        if not t:
            raise ValueError("Title cannot be empty")
        parts.append("title = ?")
        params.append(t)
    if status is not None:
        if status not in ("todo", "in_progress", "done"):
            raise ValueError("Invalid status")
        parts.append("status = ?")
        params.append(status)
    if not parts:
        return get_item(item_id)
    parts.append("updated_at = ?")
    params.append(now)
    params.append(item_id)
    with _conn() as c:
        cur = c.execute(
            f"UPDATE project_items SET {', '.join(parts)} WHERE id = ?",
            params,
        )
        if cur.rowcount == 0:
            raise KeyError("item not found")
    return get_item(item_id)


def delete_item(item_id: int) -> None:
    init_db()
    with _conn() as c:
        cur = c.execute("DELETE FROM project_items WHERE id = ?", (item_id,))
        if cur.rowcount == 0:
            raise KeyError("item not found")
