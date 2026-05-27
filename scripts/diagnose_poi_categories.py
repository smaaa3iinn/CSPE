"""POI category diagnostic — prints distribution and sample rows from POI data files."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PARQUET = ROOT / "data" / "normalized" / "poi" / "poi.parquet"
RAW_CSV = ROOT / "data" / "raw" / "poi" / "ile-de-france-poi-clean.csv"
GTFS_CSV = ROOT / "data" / "gtfs" / "ile-de-france-poi-clean.csv"
RAW_OSM_CSV = ROOT / "data" / "gtfs" / "ile-de-france-poi.csv"


def summarize_df(label: str, df: pd.DataFrame) -> None:
    print(f"\n{'=' * 72}")
    print(label)
    print(f"{'=' * 72}")
    print(f"Total POIs: {len(df):,}")
    print(f"Columns: {list(df.columns)}")

    for col in [
        "family",
        "category",
        "type",
        "category_key",
        "category_value",
        "raw_category_key",
        "raw_category_value",
    ]:
        if col not in df.columns:
            continue
        vc = df[col].fillna("").astype(str).str.strip().value_counts()
        print(f"\nTop 20 values for `{col}` ({vc.shape[0]} distinct):")
        print(vc.head(20).to_string())
        if col == "family":
            other_n = int((vc.index.str.lower() == "other").sum())
            other_rows = int(df[col].fillna("").astype(str).str.strip().str.lower().eq("other").sum())
            print(f"\nRows with family='other': {other_rows:,} ({100 * other_rows / len(df):.1f}%)")

    if "family" in df.columns and "category_value" in df.columns:
        other = df[df["family"].fillna("").astype(str).str.strip().str.lower() == "other"].head(10)
        if not other.empty:
            print("\nSample POIs classified as family=other:")
            show = [c for c in ["name", "category_key", "category_value", "category", "type", "family"] if c in other.columns]
            print(other[show].to_string(index=False))


def main() -> None:
    for path in [PARQUET, RAW_CSV, GTFS_CSV, RAW_OSM_CSV]:
        if not path.exists():
            print(f"MISSING: {path}")
            continue
        if path.suffix == ".parquet":
            df = pd.read_parquet(path)
        else:
            df = pd.read_csv(path, low_memory=False)
        summarize_df(str(path.relative_to(ROOT)), df)

    if PARQUET.exists():
        df = pd.read_parquet(PARQUET)
        print(f"\n{'=' * 72}")
        print("Cross-check: poi_index query field mapping")
        print(f"{'=' * 72}")
        from src.core.poi_index import load_poi_lookup

        lookup = load_poi_lookup(PARQUET)
        sample = lookup.query(48.8566, 2.3522, radius_m=500, limit=5)
        for row in sample:
            print(row)


if __name__ == "__main__":
    main()
