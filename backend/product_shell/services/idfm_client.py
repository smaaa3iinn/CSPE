"""Île-de-France Mobilités PRIM Navitia API client (backend-only; uses IDFM_API_KEY)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

import requests

from src.core.project_logs import log_compact_line

NAVITIA_BASE = "https://prim.iledefrance-mobilites.fr/marketplace/v2/navitia"
DEFAULT_TIMEOUT_S = 10.0
_LOCAL_IDFM_NUM = re.compile(r"IDFM:(\d+)", re.I)


@dataclass(frozen=True)
class IdfmApiFailure(Exception):
    reason: str
    detail: str
    status_code: int | None = None

    def log_line(self, *, path: str) -> str:
        bits = [f"reason={self.reason}", f'path="{path}"', f'detail="{self.detail}"']
        if self.status_code is not None:
            bits.append(f"status_code={self.status_code}")
        return " ".join(bits)


def api_key() -> str | None:
    key = (os.getenv("IDFM_API_KEY") or "").strip()
    return key or None


def local_id_to_stop_point_id(local_stop_id: str | None) -> str | None:
    """Map a CSPE stop id (e.g. IDFM:22006) to a Navitia stop_point id."""
    raw = (local_stop_id or "").strip()
    if not raw:
        return None
    if raw.startswith("stop_point:"):
        return raw
    match = _LOCAL_IDFM_NUM.search(raw)
    if match:
        return f"stop_point:IDFM:{match.group(1)}"
    if raw.isdigit():
        return f"stop_point:IDFM:{raw}"
    return None


def primary_stop_point_id(
    *,
    stop_id: str | None,
    stop_ids: list[str] | None,
    station_id: str | None,
) -> str | None:
    for candidate in [stop_id, *(stop_ids or []), station_id]:
        mapped = local_id_to_stop_point_id(str(candidate or "").strip() or None)
        if mapped:
            return mapped
    return None


class IdfmNavitiaClient:
    def __init__(self, *, timeout_s: float = DEFAULT_TIMEOUT_S) -> None:
        self._timeout_s = timeout_s
        self._session = requests.Session()

    def _headers(self) -> dict[str, str]:
        key = api_key()
        if not key:
            raise IdfmApiFailure("missing_api_key", "IDFM_API_KEY environment variable is not set")
        return {"apiKey": key}

    def get_json(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not path.startswith("/"):
            path = f"/{path}"
        url = f"{NAVITIA_BASE}{path}"
        try:
            resp = self._session.get(
                url,
                headers=self._headers(),
                params=params or {},
                timeout=self._timeout_s,
            )
        except requests.exceptions.Timeout as exc:
            failure = IdfmApiFailure(
                "timeout",
                f"IDFM Navitia read timed out after {self._timeout_s:g}s",
            )
            log_compact_line(f"[IDFM] request failed {failure.log_line(path=path)}")
            raise failure from exc
        except requests.exceptions.RequestException as exc:
            failure = IdfmApiFailure("connection_error", str(exc))
            log_compact_line(f"[IDFM] request failed {failure.log_line(path=path)}")
            raise failure from exc

        if resp.status_code >= 400:
            detail = (resp.text or "")[:240] or f"HTTP {resp.status_code}"
            reason = "invalid_api_key" if resp.status_code in (401, 403) else "http_error"
            failure = IdfmApiFailure(reason, detail, status_code=resp.status_code)
            log_compact_line(f"[IDFM] request failed {failure.log_line(path=path)}")
            raise failure

        try:
            body = resp.json()
        except Exception as exc:
            failure = IdfmApiFailure("invalid_json", str(exc), status_code=resp.status_code)
            log_compact_line(f"[IDFM] request failed {failure.log_line(path=path)}")
            raise failure from exc
        return body if isinstance(body, dict) else {}

    def stop_area_id_for_stop_point(self, stop_point_id: str) -> str | None:
        body = self.get_json(f"/stop_points/{stop_point_id}/stop_areas")
        rows = body.get("stop_areas") if isinstance(body.get("stop_areas"), list) else []
        if not rows:
            return None
        first = rows[0] if isinstance(rows[0], dict) else {}
        return str(first.get("id") or "").strip() or None

    def fetch_stop_area(self, stop_area_id: str) -> dict[str, Any]:
        body = self.get_json(f"/stop_areas/{stop_area_id}")
        rows = body.get("stop_areas") if isinstance(body.get("stop_areas"), list) else []
        return rows[0] if rows and isinstance(rows[0], dict) else {}

    def fetch_lines(self, stop_area_id: str) -> list[dict[str, Any]]:
        body = self.get_json(f"/stop_areas/{stop_area_id}/lines")
        rows = body.get("lines") if isinstance(body.get("lines"), list) else []
        return [row for row in rows if isinstance(row, dict)]

    def fetch_stop_points(self, stop_area_id: str) -> list[dict[str, Any]]:
        body = self.get_json(f"/stop_areas/{stop_area_id}/stop_points")
        rows = body.get("stop_points") if isinstance(body.get("stop_points"), list) else []
        return [row for row in rows if isinstance(row, dict)]

    def fetch_physical_modes(self, stop_area_id: str) -> list[dict[str, Any]]:
        body = self.get_json(f"/stop_areas/{stop_area_id}/physical_modes")
        rows = body.get("physical_modes") if isinstance(body.get("physical_modes"), list) else []
        return [row for row in rows if isinstance(row, dict)]

    def fetch_disruptions_for_line(self, line_id: str, *, count: int = 5) -> list[dict[str, Any]]:
        body = self.get_json(
            "/disruptions",
            params={"count": count, "filter": f"line.id={line_id}"},
        )
        rows = body.get("disruptions") if isinstance(body.get("disruptions"), list) else []
        return [row for row in rows if isinstance(row, dict)]

    def fetch_departures(self, stop_uri_id: str, *, count: int = 8) -> list[dict[str, Any]]:
        """Next departures at a stop_area or stop_point (Navitia / PRIM v2)."""
        resource = "stop_points" if str(stop_uri_id).startswith("stop_point:") else "stop_areas"
        body = self.get_json(
            f"/{resource}/{stop_uri_id}/departures",
            params={"count": count},
        )
        rows = body.get("departures") if isinstance(body.get("departures"), list) else []
        return [row for row in rows if isinstance(row, dict)]

    def fetch_stop_schedules(self, stop_area_id: str, *, count: int = 20) -> list[dict[str, Any]]:
        """Theoretical passage times (first/last/date_times) at a stop area."""
        body = self.get_json(
            f"/stop_areas/{stop_area_id}/stop_schedules",
            params={"count": count},
        )
        rows = body.get("stop_schedules") if isinstance(body.get("stop_schedules"), list) else []
        return [row for row in rows if isinstance(row, dict)]


_default_client: IdfmNavitiaClient | None = None


def navitia_client() -> IdfmNavitiaClient:
    global _default_client
    if _default_client is None:
        _default_client = IdfmNavitiaClient()
    return _default_client
