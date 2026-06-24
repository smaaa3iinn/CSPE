"""Display session metadata for structured UI command batches."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

UiCommandTarget = Literal["active_display", "2d", "vr_dev", "vr_real"]
UiCommandSource = Literal["atlas_chat", "atlas_voice", "shell_poll", "shell_sse", "manual_ui"]


def enrich_ui_command_batch(
    batch: dict[str, Any] | None,
    *,
    source: UiCommandSource = "atlas_chat",
    target: UiCommandTarget = "active_display",
    session_id: str | None = None,
) -> dict[str, Any] | None:
    """Attach display-session routing metadata to a captured command batch."""
    if not batch or not batch.get("commands"):
        return None
    out = dict(batch)
    out.setdefault("target", target)
    out.setdefault("source", source)
    out.setdefault("session_id", session_id)
    out.setdefault("created_at", datetime.now(timezone.utc).isoformat())
    return out
