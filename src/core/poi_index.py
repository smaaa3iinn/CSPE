from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import pickle

import numpy as np
import pandas as pd
from sklearn.neighbors import BallTree

EARTH_RADIUS_M = 6_371_000.0


@dataclass(frozen=True)
class POILookupStats:
    data_path: str
    poi_count: int
    memory_bytes: int


class LocalPOILookup:
    """Fast local POI lookup based on a BallTree over haversine distance."""

    def __init__(
        self,
        data_path: str | Path,
        *,
        tree_path: str | Path | None = None,
        npz_path: str | Path | None = None,
    ):
        self.data_path = Path(data_path)
        self.tree_path = None if tree_path is None else Path(tree_path)
        self.npz_path = None if npz_path is None else Path(npz_path)
        self.df = self._load_parquet(self.data_path)
        coords_deg = self.df[["lat", "lon"]].to_numpy(dtype=np.float64, copy=True)
        self.coords_rad = np.radians(coords_deg)
        self.tree = self._load_tree(self.tree_path, self.npz_path, self.coords_rad)
        self.stats = POILookupStats(
            data_path=str(self.data_path),
            poi_count=len(self.df),
            memory_bytes=int(self.df.memory_usage(deep=True).sum() + self.coords_rad.nbytes),
        )

    @staticmethod
    def _load_parquet(data_path: Path) -> pd.DataFrame:
        df = pd.read_parquet(data_path)
        required_columns = {"id", "name", "category_key", "category_value", "lat", "lon"}
        if not required_columns.issubset(df.columns):
            raise ValueError(
                "Unsupported POI parquet schema. Expected columns "
                "`id`, `name`, `category_key`, `category_value`, `lat`, and `lon`."
            )
        df = df[["id", "name", "category_key", "category_value", "lat", "lon"]].copy()
        df = df.dropna(subset=["lat", "lon"]).copy()
        df["name"] = df["name"].fillna("").astype(str)
        df["category_key"] = df["category_key"].fillna("").astype(str)
        df["category_value"] = df["category_value"].fillna("").astype(str)
        df["lat"] = df["lat"].astype(float)
        df["lon"] = df["lon"].astype(float)
        df = df.reset_index(drop=True)
        return df

    @staticmethod
    def _load_tree(tree_path: Path | None, npz_path: Path | None, coords_rad: np.ndarray) -> BallTree:
        if tree_path is not None and tree_path.exists():
            with tree_path.open("rb") as fh:
                tree = pickle.load(fh)
            if isinstance(tree, BallTree):
                return tree

        if npz_path is not None and npz_path.exists():
            npz = np.load(npz_path, allow_pickle=True)
            stored_coords = npz["coords_rad"]
            if stored_coords.shape == coords_rad.shape and np.allclose(stored_coords, coords_rad):
                return BallTree(stored_coords, metric="haversine")

        return BallTree(coords_rad, metric="haversine")

    @lru_cache(maxsize=4096)
    def _query_cached(
        self,
        lat: float,
        lon: float,
        radius_m: float,
        category_key: str | None,
        category_value: str | None,
        limit: int | None,
    ) -> tuple[tuple, ...]:
        radius_m = float(radius_m)
        query_point = np.radians(np.array([[float(lat), float(lon)]], dtype=np.float64))
        radius_rad = radius_m / EARTH_RADIUS_M

        indices_arr, distances_arr = self.tree.query_radius(
            query_point,
            r=radius_rad,
            return_distance=True,
            sort_results=True,
        )
        indices = indices_arr[0]
        distances_m = distances_arr[0] * EARTH_RADIUS_M

        results: list[tuple] = []
        for idx, distance_m in zip(indices, distances_m):
            row = self.df.iloc[int(idx)]
            if category_key is not None and row["category_key"] != category_key:
                continue
            if category_value is not None and row["category_value"] != category_value:
                continue
            results.append(
                (
                    row["name"],
                    row["category_key"],
                    row["category_value"],
                    float(row["lat"]),
                    float(row["lon"]),
                    float(distance_m),
                )
            )
            if limit is not None and len(results) >= limit:
                break

        return tuple(results)

    def query(
        self,
        lat: float,
        lon: float,
        radius_m: float = 300.0,
        *,
        category_key: str | None = None,
        category_value: str | None = None,
        limit: int | None = None,
    ) -> list[dict]:
        rows = self._query_cached(
            round(float(lat), 7),
            round(float(lon), 7),
            round(float(radius_m), 3),
            None if category_key is None else str(category_key),
            None if category_value is None else str(category_value),
            None if limit is None else int(limit),
        )
        return [
            {
                "name": name,
                "category": category_key_value,
                "type": category_value_value,
                "lat": poi_lat,
                "lon": poi_lon,
                "distance_m": distance_m,
            }
            for name, category_key_value, category_value_value, poi_lat, poi_lon, distance_m in rows
        ]


@lru_cache(maxsize=8)
def load_poi_lookup(
    data_path: str | Path,
    *,
    tree_path: str | Path | None = None,
    npz_path: str | Path | None = None,
) -> LocalPOILookup:
    return LocalPOILookup(data_path, tree_path=tree_path, npz_path=npz_path)
