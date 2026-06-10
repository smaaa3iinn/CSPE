"""Atlas /ui JSON -> normalized structured blocks for the React shell."""

from __future__ import annotations

from typing import Any


def normalize_atlas_ui(ui: dict[str, Any]) -> list[dict[str, Any]]:
    """Produce a list of typed payloads the frontend can render without parsing assistant text."""
    out: list[dict[str, Any]] = []
    if not ui:
        return out

    assistant = (ui.get("assistant") or "").strip()
    if assistant:
        out.append({"type": "text", "role": "assistant", "content": assistant})

    status = ui.get("status") or ui.get("system")
    if isinstance(status, dict) and status:
        out.append({"type": "system_status", "status": status})

    return out
