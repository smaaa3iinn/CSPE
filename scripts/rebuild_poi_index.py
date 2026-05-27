"""Rebuild data/normalized/poi/poi.parquet and derived BallTree indexes."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    spec = importlib.util.spec_from_file_location(
        "build_bus_render_graph",
        ROOT / "data" / "build_bus_render_graph.py",
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load data/build_bus_render_graph.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["build_bus_render_graph"] = mod
    spec.loader.exec_module(mod)

    mod.ensure_dirs()
    print("Loading and normalizing POIs...")
    poi = mod.load_and_normalize_poi()
    mod.NORMALIZED_POI.mkdir(parents=True, exist_ok=True)
    out = mod.NORMALIZED_POI / "poi.parquet"
    poi.to_parquet(out, index=False)
    print(f"Saved {out} ({len(poi):,} rows)")
    print("\nFamily distribution:")
    print(poi["family"].value_counts().to_string())
    key_pct = 100.0 * poi["category_key"].ne("").mean()
    print(f"\ncategory_key populated: {int(poi['category_key'].ne('').sum()):,} ({key_pct:.1f}%)")
    print("Building BallTree index...")
    mod.build_poi_index(poi)
    print("Done.")


if __name__ == "__main__":
    main()
