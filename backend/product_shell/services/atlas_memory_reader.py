"""
Read-only access to Atlas memory SQLite (same schema as atlas_client.storage.memory_store).
DB default: src/work/atlas/data/atlas_memory.sqlite under the CSPE repo root.
Override with ATLAS_MEMORY_SQLITE.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

# backend/product_shell/services/atlas_memory_reader.py -> parents[3] = repo root (CSPE)
_REPO_ROOT = Path(__file__).resolve().parents[3]


def memory_db_path() -> Path:
    env = (os.getenv("ATLAS_MEMORY_SQLITE") or "").strip()
    if env:
        return Path(env)
    return _REPO_ROOT / "src" / "work" / "atlas" / "data" / "atlas_memory.sqlite"


def _row_to_item(row: sqlite3.Row) -> dict[str, Any]:
    try:
        tags = json.loads(row["tags"]) if row["tags"] else []
    except (json.JSONDecodeError, TypeError):
        tags = []
    if not isinstance(tags, list):
        tags = []
    tags = [str(t) for t in tags if t is not None and str(t).strip()]
    return {
        "id": int(row["id"]),
        "text": row["text"] or "",
        "tags": tags,
        "due_at": row["due_at"],
        "status": row["status"] or "open",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def fetch_all_items(*, limit: int = 2000) -> list[dict[str, Any]]:
    path = memory_db_path()
    if not path.is_file():
        return []
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            """
            SELECT id, text, tags, due_at, status, created_at, updated_at
            FROM memory_items
            ORDER BY datetime(created_at) DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [_row_to_item(r) for r in cur.fetchall()]
    except sqlite3.OperationalError:
        return []
    finally:
        conn.close()


def list_projects_from_db() -> list[dict[str, Any]]:
    """Synthetic 'projects' from unique tags + '__all__'."""
    items = fetch_all_items()
    if not items:
        return [{"id": "__all__", "name": "All items", "count": 0}]

    tag_counts: Counter[str] = Counter()
    for it in items:
        for t in it["tags"]:
            tag_counts[t] += 1

    out: list[dict[str, Any]] = [{"id": "__all__", "name": "All items", "count": len(items)}]
    for tag, cnt in sorted(tag_counts.items(), key=lambda x: x[0].lower()):
        out.append({"id": tag, "name": _pretty_tag_name(tag), "count": cnt})
    return out


def _pretty_tag_name(tag: str) -> str:
    t = tag.strip()
    if not t:
        return tag
    return t.replace("_", " ").replace("-", " ").title() if t.islower() or "_" in t else t


def list_tasks_for_project(project_id: str, *, limit: int = 500) -> list[dict[str, Any]]:
    items = fetch_all_items(limit=max(limit, 500))
    if project_id == "__all__":
        filtered = items
    else:
        filtered = [it for it in items if project_id in it["tags"]]
    filtered = filtered[:limit]
    out = []
    for it in filtered:
        out.append(
            {
                "id": str(it["id"]),
                "title": it["text"].strip() or "(empty)",
                "done": (it["status"] or "").lower() == "done",
                "status": it["status"],
                "tags": it["tags"],
                "due_at": it["due_at"],
                "created_at": it["created_at"],
                "updated_at": it["updated_at"],
            }
        )
    return out
