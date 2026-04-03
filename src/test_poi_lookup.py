from __future__ import annotations

from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.poi_index import load_poi_lookup

POI_CSV = "data/gtfs/ile-de-france-poi.csv"


def main():
    t0 = time.perf_counter()
    lookup = load_poi_lookup(POI_CSV)
    build_ms = (time.perf_counter() - t0) * 1000.0
    print(
        f"loaded {lookup.stats.poi_count} POIs "
        f"in {build_ms:.1f} ms "
        f"(approx memory {lookup.stats.memory_bytes / (1024 * 1024):.2f} MB)"
    )

    # Chatelet - Les Halles area
    lat = 48.8606
    lon = 2.3470

    t1 = time.perf_counter()
    results = lookup.query(lat, lon, radius_m=300.0, limit=10)
    query_ms = (time.perf_counter() - t1) * 1000.0
    print(f"query returned {len(results)} POIs in {query_ms:.2f} ms")

    for row in results[:10]:
        print(row)

    t2 = time.perf_counter()
    cached_results = lookup.query(lat, lon, radius_m=300.0, limit=10)
    cached_ms = (time.perf_counter() - t2) * 1000.0
    print(f"cached query returned {len(cached_results)} POIs in {cached_ms:.4f} ms")


if __name__ == "__main__":
    main()
