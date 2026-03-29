from __future__ import annotations

from pathlib import Path
import pickle
from typing import Any

from src.core.graph_loader import (
    build_edges_enriched,
    build_graphs_by_mode_with_lines,
    build_pos_all,
    load_gtfs,
)

CACHE_VERSION = 1
CORE_GTFS_FILES = ("stops.txt", "routes.txt", "trips.txt", "stop_times.txt")


def _default_cache_path(gtfs_dir: str | Path) -> Path:
    gtfs_dir = Path(gtfs_dir)
    return gtfs_dir.parent / "cache" / "graph_bundle.pkl"


def _gtfs_signature(gtfs_dir: str | Path) -> dict[str, int]:
    gtfs_dir = Path(gtfs_dir)
    return {name: (gtfs_dir / name).stat().st_mtime_ns for name in CORE_GTFS_FILES}


def _is_cache_valid(bundle: dict[str, Any], signature: dict[str, int]) -> bool:
    return (
        bundle.get("cache_version") == CACHE_VERSION
        and bundle.get("gtfs_signature") == signature
        and "pos_all" in bundle
        and "edges_clean" in bundle
        and "graphs" in bundle
        and "graphs_lcc" in bundle
    )


def _build_bundle(gtfs_dir: str | Path, signature: dict[str, int]) -> dict[str, Any]:
    data = load_gtfs(gtfs_dir)
    pos_all = build_pos_all(data.stops)
    edges_clean = build_edges_enriched(data, pos_all=pos_all)
    graphs, graphs_lcc = build_graphs_by_mode_with_lines(data, edges_clean, pos_all=pos_all)
    return {
        "cache_version": CACHE_VERSION,
        "gtfs_signature": signature,
        "pos_all": pos_all,
        "edges_clean": edges_clean,
        "graphs": graphs,
        "graphs_lcc": graphs_lcc,
    }


def load_or_build_graph_bundle(
    gtfs_dir: str | Path,
    cache_path: str | Path | None = None,
    force_rebuild: bool = False,
) -> dict[str, Any]:
    gtfs_dir = Path(gtfs_dir)
    cache_path = Path(cache_path) if cache_path is not None else _default_cache_path(gtfs_dir)
    signature = _gtfs_signature(gtfs_dir)

    if not force_rebuild and cache_path.exists():
        try:
            with cache_path.open("rb") as fh:
                bundle = pickle.load(fh)
            if isinstance(bundle, dict) and _is_cache_valid(bundle, signature):
                return bundle
        except Exception:
            pass

    bundle = _build_bundle(gtfs_dir, signature)
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    tmp_path = cache_path.with_suffix(cache_path.suffix + ".tmp")
    with tmp_path.open("wb") as fh:
        pickle.dump(bundle, fh, protocol=pickle.HIGHEST_PROTOCOL)
    tmp_path.replace(cache_path)

    return bundle
