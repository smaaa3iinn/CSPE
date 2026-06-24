from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parent
DATA_ROOT = PROJECT_ROOT / "data"

RAW_GEOJSON = DATA_ROOT / "raw" / "geo" / "traces-des-lignes-de-transport-en-commun-idfm.geojson"

DERIVED_MAPS = DATA_ROOT / "derived" / "maps"
NORMALIZED_GEO = DATA_ROOT / "normalized" / "geo"


def ensure_dirs() -> None:
    DERIVED_MAPS.mkdir(parents=True, exist_ok=True)
    NORMALIZED_GEO.mkdir(parents=True, exist_ok=True)


def detect_mode_from_row(row: pd.Series) -> str:
    rt = str(row.get("route_type", "")).strip().lower()

    mapping = {
        "bus": "bus",
        "subway": "metro",
        "rail": "rail",
        "tram": "tram",
        "cableway": "other",
        "funicular": "other",
    }

    if rt in mapping:
        return mapping[rt]

    text = " ".join([
        str(row.get("networkname", "")),
        str(row.get("operatorname", "")),
        str(row.get("route_short_name", "")),
        str(row.get("route_long_name", "")),
        str(row.get("long_name_first", "")),
    ]).lower()

    if "tram" in text:
        return "tram"
    if "metro" in text or "métro" in text or "subway" in text:
        return "metro"
    if any(x in text for x in ["rer", "transilien", "train", "rail", "sncf"]):
        return "rail"
    if "bus" in text:
        return "bus"

    return "other"


def simplify_for_web(gdf: gpd.GeoDataFrame, tolerance: float = 0.00005) -> gpd.GeoDataFrame:
    out = gdf.copy()
    out["geometry"] = out.geometry.simplify(tolerance=tolerance, preserve_topology=True)
    return out


def main() -> None:
    ensure_dirs()

    if not RAW_GEOJSON.exists():
        raise FileNotFoundError(f"Missing file: {RAW_GEOJSON}")

    print("Loading raw GeoJSON...")
    gdf = gpd.read_file(RAW_GEOJSON)

    print("Columns found:")
    print(list(gdf.columns))

    gdf["mode_detected"] = gdf.apply(detect_mode_from_row, axis=1)

    print("\nDetected mode counts:")
    print(gdf["mode_detected"].value_counts(dropna=False))

    keep = [
        "route_id",
        "route_short_name",
        "route_long_name",
        "route_type",
        "networkname",
        "operatorname",
        "mode_detected",
        "geometry",
    ]

    for c in keep:
        if c not in gdf.columns:
            gdf[c] = ""

    geo = gdf[keep].copy()

    geo["route_id"] = geo["route_id"].fillna("").astype(str)
    geo["route_short_name"] = geo["route_short_name"].fillna("").astype(str)
    geo["route_long_name"] = geo["route_long_name"].fillna("").astype(str)
    geo["route_type"] = geo["route_type"].fillna("").astype(str)
    geo["networkname"] = geo["networkname"].fillna("").astype(str)
    geo["operatorname"] = geo["operatorname"].fillna("").astype(str)

    geo["route_label"] = geo["route_short_name"]
    geo.loc[geo["route_label"].str.strip() == "", "route_label"] = geo["route_long_name"]

    geo = geo[geo.geometry.notna()].copy()
    geo = geo[geo["mode_detected"].isin(["bus", "metro", "rail", "tram"])].copy()

    print("Saving normalized parquet summary...")
    summary = geo.drop(columns="geometry").copy()
    summary.to_parquet(NORMALIZED_GEO / "line_geometries.parquet", index=False)

    for mode in ["bus", "metro", "rail", "tram"]:
        sub = geo[geo["mode_detected"] == mode].copy()
        if sub.empty:
            print(f"No features for mode={mode}, skipping")
            continue

        print(f"Processing {mode}: {len(sub)} features")

        sub_simple = simplify_for_web(sub, tolerance=0.00005)

        out_geojson = DERIVED_MAPS / f"{mode}.network.geojson"
        sub_simple.to_file(out_geojson, driver="GeoJSON")

        meta = {
            "mode": mode,
            "feature_count": int(len(sub_simple)),
            "source": str(RAW_GEOJSON),
            "crs": str(sub_simple.crs),
        }
        with (DERIVED_MAPS / f"{mode}.network.meta.json").open("w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

        print(f"Saved {out_geojson}")

    print("Done.")


if __name__ == "__main__":
    main()