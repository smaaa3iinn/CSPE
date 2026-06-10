"""Cached IDFM referential datasets (arrets, accessibilite-en-gare) for local stop ids."""

from __future__ import annotations

import csv
import io
import re
import time
from pathlib import Path
from typing import Any

import requests

from src.core.project_logs import log_compact_line

_LOCAL_IDFM_NUM = re.compile(r"IDFM:(\d+)", re.I)
_CACHE_TTL_S = 24 * 3600
_DATASETS = {
    "arrets": "https://data.iledefrance-mobilites.fr/explore/dataset/arrets/download/?format=csv",
    "accessibilite_en_gare": (
        "https://data.iledefrance-mobilites.fr/explore/dataset/accessibilite-en-gare/download/?format=csv"
    ),
}


def _cache_dir() -> Path:
    root = Path(__file__).resolve().parents[3]
    path = root / "data" / "derived" / "idfm"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _local_arrid(local_stop_id: str | None) -> str | None:
    raw = (local_stop_id or "").strip()
    if not raw:
        return None
    match = _LOCAL_IDFM_NUM.search(raw)
    if match:
        return match.group(1)
    if raw.isdigit():
        return raw
    return None


def _download_csv(dataset: str, url: str) -> str:
    cache_path = _cache_dir() / f"{dataset}.csv"
    if cache_path.is_file():
        age_s = time.time() - cache_path.stat().st_mtime
        if age_s < _CACHE_TTL_S:
            return cache_path.read_text(encoding="utf-8-sig")

    log_compact_line(f"[IDFM] downloading referential dataset={dataset}")
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    text = resp.text
    cache_path.write_text(text, encoding="utf-8")
    return text


class IdfmReferentialStore:
    def __init__(self) -> None:
        self._arrets_by_arrid: dict[str, dict[str, str]] | None = None
        self._access_by_stop_point: dict[str, dict[str, str]] | None = None

    def _load_arrets(self) -> dict[str, dict[str, str]]:
        if self._arrets_by_arrid is not None:
            return self._arrets_by_arrid
        text = _download_csv("arrets", _DATASETS["arrets"])
        out: dict[str, dict[str, str]] = {}
        reader = csv.DictReader(io.StringIO(text), delimiter=";")
        for row in reader:
            arrid = str(row.get("arrid") or "").strip()
            if arrid:
                out[arrid] = {k: str(v or "") for k, v in row.items()}
        self._arrets_by_arrid = out
        log_compact_line(f"[IDFM] arrets index loaded rows={len(out)}")
        return out

    def _load_accessibilite(self) -> dict[str, dict[str, str]]:
        if self._access_by_stop_point is not None:
            return self._access_by_stop_point
        text = _download_csv("accessibilite_en_gare", _DATASETS["accessibilite_en_gare"])
        out: dict[str, dict[str, str]] = {}
        reader = csv.DictReader(io.StringIO(text), delimiter=";")
        for row in reader:
            spid = str(row.get("stop_point_id") or "").strip()
            if spid:
                out[spid] = {k: str(v or "") for k, v in row.items()}
        self._access_by_stop_point = out
        log_compact_line(f"[IDFM] accessibilite-en-gare index loaded rows={len(out)}")
        return out

    def accessibility_for_local_stop(self, local_stop_id: str | None) -> dict[str, Any] | None:
        arrid = _local_arrid(local_stop_id)
        if not arrid:
            return None
        row = self._load_arrets().get(arrid)
        if not row:
            return None
        level = str(row.get("arraccessibility") or "").strip().lower()
        if not level:
            return None
        return {
            "source": "arrets",
            "arrid": arrid,
            "name": row.get("arrname") or "",
            "type": row.get("arrtype") or "",
            "accessibility": level,
            "zone_id": row.get("zdaid") or "",
        }

    def gare_accessibility_for_stop_point(self, stop_point_id: str | None) -> dict[str, Any] | None:
        spid = (stop_point_id or "").strip()
        if not spid:
            return None
        row = self._load_accessibilite().get(spid)
        if not row:
            return None
        return {
            "source": "accessibilite-en-gare",
            "stop_point_id": spid,
            "level_id": row.get("accessibility_level_id") or "",
            "level_name": row.get("accessibility_level_name") or "",
            "stop_name": row.get("stop_name") or "",
            "comment": row.get("commentaire") or "",
        }


_store: IdfmReferentialStore | None = None


def referential_store() -> IdfmReferentialStore:
    global _store
    if _store is None:
        _store = IdfmReferentialStore()
    return _store


def describe_accessibility_level(level: str) -> str:
    normalized = (level or "").strip().lower()
    mapping = {
        "true": "accessible",
        "false": "not accessible",
        "partial": "partially accessible",
        "unknown": "accessibility not declared",
    }
    return mapping.get(normalized, normalized or "unknown")
