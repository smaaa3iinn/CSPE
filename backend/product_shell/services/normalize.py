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

    panels = ui.get("panels") or []
    panel_items: list[dict[str, Any]] = []
    if isinstance(panels, list):
        for p in panels:
            if not isinstance(p, dict):
                continue
            urls = [str(u) for u in (p.get("urls") or []) if str(u).startswith("http")]
            panel_items.append(
                {
                    "title": (p.get("title") or "Panel").strip(),
                    "query": (p.get("query") or "").strip(),
                    "urls": urls,
                }
            )

    if panel_items:
        out.append({"type": "visual_board", "panels": panel_items})
        flat: list[dict[str, str]] = []
        for pi in panel_items:
            for u in pi["urls"]:
                flat.append({"url": u, "caption": pi.get("title") or ""})
        if flat:
            out.append({"type": "image_results", "images": flat})

    status = ui.get("status") or ui.get("system")
    if isinstance(status, dict) and status:
        out.append({"type": "system_status", "status": status})

    return out
