"""Shared text normalization for transport station/stop search."""

from __future__ import annotations

import re
import unicodedata


def normalize_search_text(s: str) -> str:
    """
    Normalize user queries and station labels for matching:
    lowercase, strip accents, unify apostrophes/hyphens, drop punctuation, collapse space.
    """
    text = str(s or "").strip().lower()
    if not text:
        return ""
    text = unicodedata.normalize("NFD", text)
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.replace("œ", "oe").replace("æ", "ae")
    text = re.sub(r"[''`´]", " ", text)
    text = re.sub(r"[-–—/\\.,;:()]", " ", text)
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# Backwards-compatible alias used across src/core
normalize_text = normalize_search_text
