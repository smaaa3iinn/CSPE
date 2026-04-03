"""Mapbox mask: world polygon with Île-de-France (or Paris) administrative boundary as hole(s)."""

from __future__ import annotations

import json
import math
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
# Région 11 — same extent as the eight départements: Paris 75, Seine-et-Marne 77,
# Yvelines 78, Essonne 91, Hauts-de-Seine 92, Seine-Saint-Denis 93, Val-de-Marne 94, Val-d'Oise 95.
IDF_DEPARTEMENTS_INSEE: tuple[str, ...] = ("75", "77", "78", "91", "92", "93", "94", "95")

_IDF_BOUNDARY = _PROJECT_ROOT / "data" / "derived" / "geo" / "ile_de_france_admin_boundary.geojson"
_PARIS_BOUNDARY = _PROJECT_ROOT / "data" / "derived" / "geo" / "paris_admin_boundary.geojson"

# Full-world outer ring (lon, lat), closed. Inner rings = visible region (holes in the dimmed overlay).
WORLD_OUTER_RING: list[list[float]] = [
    [-180.0, -85.0],
    [180.0, -85.0],
    [180.0, 85.0],
    [-180.0, 85.0],
    [-180.0, -85.0],
]


def _signed_area_lon_lat(ring: list[list[float]]) -> float:
    s = 0.0
    for i in range(len(ring) - 1):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[i + 1][0], ring[i + 1][1]
        s += x1 * y2 - x2 * y1
    return 0.5 * s


def _ensure_closed(ring: list[list[float]]) -> list[list[float]]:
    if not ring:
        return ring
    if ring[0][0] == ring[-1][0] and ring[0][1] == ring[-1][1]:
        return ring
    return ring + [list(ring[0])]


def _reverse_ring(ring: list[list[float]]) -> list[list[float]]:
    r = _ensure_closed(ring)
    if len(r) <= 1:
        return r
    inner = r[:-1][::-1]
    return _ensure_closed(inner)


def _geometry_from_geojson(data: dict[str, Any]) -> dict[str, Any]:
    t = data.get("type")
    if t == "FeatureCollection":
        feats = data.get("features") or []
        if not feats:
            raise ValueError("empty FeatureCollection")
        return _geometry_from_geojson(feats[0])
    if t == "Feature":
        geom = data.get("geometry")
        if not isinstance(geom, dict):
            raise ValueError("feature missing geometry")
        return geom
    if t in ("Polygon", "MultiPolygon"):
        return data
    raise ValueError(f"unsupported geojson type: {t}")


def _exterior_rings(geom: dict[str, Any]) -> list[list[list[float]]]:
    t = geom.get("type")
    coords = geom.get("coordinates")
    if t == "Polygon":
        if not coords:
            return []
        return [_ensure_closed([list(map(float, p)) for p in coords[0]])]
    if t == "MultiPolygon":
        out: list[list[list[float]]] = []
        for poly in coords or []:
            if not poly:
                continue
            out.append(_ensure_closed([list(map(float, p)) for p in poly[0]]))
        return out
    raise ValueError(f"geometry must be Polygon or MultiPolygon, got {t}")


def _bounds_from_rings(rings: list[list[list[float]]]) -> tuple[float, float, float, float]:
    lons: list[float] = []
    lats: list[float] = []
    for ring in rings:
        for lon, lat in ring:
            lons.append(float(lon))
            lats.append(float(lat))
    if not lons:
        return -180.0, -85.0, 180.0, 85.0
    return min(lons), min(lats), max(lons), max(lats)


def _estimate_zoom(lon_span: float, lat_span: float) -> float:
    span = max(lon_span, lat_span * 1.25, 1e-6)
    z = math.log2(360.0 / span) - 0.75
    return float(max(7.2, min(13.5, z)))


@lru_cache(maxsize=2)
def _load_boundary_raw(path_str: str) -> str:
    path = Path(path_str)
    return path.read_text(encoding="utf-8")


def resolve_region_mask_path(boundary_geojson_path: str | None = None) -> Path:
    if boundary_geojson_path:
        p = Path(boundary_geojson_path)
        if not p.is_file():
            raise FileNotFoundError(str(p))
        return p
    for env_key in ("REGION_MASK_GEOJSON", "IDF_BOUNDARY_GEOJSON", "PARIS_BOUNDARY_GEOJSON"):
        env_val = os.environ.get(env_key)
        if env_val and Path(env_val).is_file():
            return Path(env_val)
    if _IDF_BOUNDARY.is_file():
        return _IDF_BOUNDARY
    if _PARIS_BOUNDARY.is_file():
        return _PARIS_BOUNDARY
    raise FileNotFoundError(
        f"no region mask GeoJSON (tried {_IDF_BOUNDARY.name}, {_PARIS_BOUNDARY.name}, or env REGION_MASK_GEOJSON)"
    )


def build_region_world_mask_feature(boundary_geojson_path: str | None = None) -> dict[str, Any]:
    path = resolve_region_mask_path(boundary_geojson_path)
    raw = _load_boundary_raw(str(path.resolve()))
    data = json.loads(raw)
    geom = _geometry_from_geojson(data)
    region_exteriors = _exterior_rings(geom)
    if not region_exteriors:
        raise ValueError("no exterior rings in region boundary")

    outer = _ensure_closed([list(p) for p in WORLD_OUTER_RING])
    outer_sign = _signed_area_lon_lat(outer)

    inners: list[list[list[float]]] = []
    for ring in region_exteriors:
        r = _ensure_closed(ring)
        if _signed_area_lon_lat(r) * outer_sign > 0:
            r = _reverse_ring(r)
        inners.append(r)

    return {
        "type": "Feature",
        "properties": {"id": "region-world-mask", "source_file": path.name},
        "geometry": {"type": "Polygon", "coordinates": [outer] + inners},
    }


def build_paris_world_mask_feature(boundary_geojson_path: str | None = None) -> dict[str, Any]:
    """Backward-compatible alias for :func:`build_region_world_mask_feature`."""
    return build_region_world_mask_feature(boundary_geojson_path)


def paris_view_and_bounds(
    boundary_geojson_path: str | None = None,
    pad_deg: float = 0.06,
) -> dict[str, Any]:
    path = resolve_region_mask_path(boundary_geojson_path)
    raw = _load_boundary_raw(str(path.resolve()))
    data = json.loads(raw)
    geom = _geometry_from_geojson(data)
    rings = _exterior_rings(geom)
    w, s, e, n = _bounds_from_rings(rings)
    w, s, e, n = w - pad_deg, s - pad_deg, e + pad_deg, n + pad_deg
    lon_c = 0.5 * (w + e)
    lat_c = 0.5 * (s + n)
    zoom = _estimate_zoom(e - w, n - s)
    return {
        "max_bounds": [[w, s], [e, n]],
        "center": {"lon": lon_c, "lat": lat_c},
        "zoom": zoom,
    }


def build_paris_mask_payload(boundary_geojson_path: str | None = None) -> dict[str, Any]:
    mask_feature = build_paris_world_mask_feature(boundary_geojson_path)
    vb = paris_view_and_bounds(boundary_geojson_path)
    return {"mask_feature": mask_feature, **vb}
