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
    text = " ".join([
        str(row.get("mode", "")),
        str(row.get("type", "")),
        str(row.get("route_type", "")),
        str(row.get("transport_mode", "")),
        str(row.get("reseau", "")),
        str(row.get("network", "")),
        str(row.get("nom_mode", "")),
        str(row.get("mode_transport", "")),
        str(row.get("name", "")),
        str(row.get("route_name", "")),
        str(row.get("route_long_name", "")),
        str(row.get("route_short_name", "")),
    ]).lower()

    if "tram" in text:
        return "tram"
    if "metro" in text or "métro" in text:
        return "metro"
    if any(x in text for x in ["rer", "transilien", "train", "rail", "sncf"]):
        return "rail"
    if "bus" in text:
        return "bus"
    return "other"


def pick_first_existing(columns: list[str], candidates: list[str]) -> str | None:
    for c in candidates:
        if c in columns:
            return c
    return None


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

    cols = list(gdf.columns)

    route_id_col = pick_first_existing(cols, [
        "route_id", "id_line", "idligne", "line_id", "objectid", "id"
    ])
    short_name_col = pick_first_existing(cols, [
        "route_short_name", "short_name", "ligne", "line", "indice_lig", "code"
    ])
    long_name_col = pick_first_existing(cols, [
        "route_long_name", "long_name", "nom_ligne", "name", "libelle", "nom"
    ])

    print("Selected columns:")
    print("route_id:", route_id_col)
    print("short_name:", short_name_col)
    print("long_name:", long_name_col)

    keep = ["mode_detected", "geometry"]
    for c in [route_id_col, short_name_col, long_name_col]:
        if c and c not in keep:
            keep.append(c)

    geo = gdf[keep].copy()

    rename_map = {}
    if route_id_col:
        rename_map[route_id_col] = "route_id"
    if short_name_col:
        rename_map[short_name_col] = "route_short_name"
    if long_name_col:
        rename_map[long_name_col] = "route_long_name"

    geo = geo.rename(columns=rename_map)

    for c in ["route_id", "route_short_name", "route_long_name"]:
        if c not in geo.columns:
            geo[c] = ""

    geo["route_id"] = geo["route_id"].fillna("").astype(str)
    geo["route_short_name"] = geo["route_short_name"].fillna("").astype(str)
    geo["route_long_name"] = geo["route_long_name"].fillna("").astype(str)
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

        # optional simplification for lighter runtime files
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