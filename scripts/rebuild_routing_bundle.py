"""Rebuild data/derived/routing/graph_bundle.pkl with ride + GTFS + inferred transfers."""

from __future__ import annotations

import argparse
import pickle
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.core.graph_loader import (  # noqa: E402
    _edge_pairs_from_frame,
    _empty_edges_df,
    build_gtfs_transfer_edges,
    build_pos_all,
    build_ride_edges,
    build_transfer_edges,
    combine_edges,
    edges_dataframe_to_records,
    load_gtfs,
    to_pos_dict,
)

DEFAULT_GTFS_DIR = ROOT / "data" / "gtfs"
DEFAULT_OUT = ROOT / "data" / "derived" / "routing" / "graph_bundle.pkl"
BUNDLE_CACHE_VERSION = 5


def _count_kinds(edges) -> dict[str, int]:
    if edges.empty:
        return {}
    return edges["edge_kind"].astype(str).value_counts().to_dict()


def build_bundle_payload(
    gtfs_dir: Path,
    *,
    use_gtfs_transfers: bool = True,
    use_inferred_transfers: bool = True,
) -> dict[str, object]:
    t0 = time.time()
    data = load_gtfs(gtfs_dir)
    pos_all = build_pos_all(data.stops)
    ride_edges = build_ride_edges(data, pos_all=pos_all)
    gtfs_transfer_edges = (
        build_gtfs_transfer_edges(data, pos_all=pos_all, ride_edges=ride_edges)
        if use_gtfs_transfers
        else _empty_edges_df()
    )
    blocked_pairs = _edge_pairs_from_frame(ride_edges)
    blocked_pairs.update(_edge_pairs_from_frame(gtfs_transfer_edges))
    inferred_transfer_edges = (
        build_transfer_edges(
            data,
            pos_all=pos_all,
            ride_edges=ride_edges,
            existing_pairs=blocked_pairs,
        )
        if use_inferred_transfers
        else _empty_edges_df()
    )
    edges = combine_edges(ride_edges, gtfs_transfer_edges, inferred_transfer_edges)

    ride_count = int((edges["edge_kind"] == "ride").sum())
    transfer_count = int((edges["edge_kind"] == "transfer").sum())
    elapsed_s = round(time.time() - t0, 1)

    return {
        "cache_version": BUNDLE_CACHE_VERSION,
        "built_at": datetime.now(timezone.utc).isoformat(),
        "pos_all": to_pos_dict(pos_all),
        "edges_clean": edges_dataframe_to_records(edges),
        "stats": {
            "stops": int(len(pos_all)),
            "edges_total": int(len(edges)),
            "edges_ride": ride_count,
            "edges_transfer": transfer_count,
            "edges_gtfs_transfer": int(len(gtfs_transfer_edges)),
            "edges_inferred_transfer": int(len(inferred_transfer_edges)),
            "gtfs_transfers_rows": int(len(data.transfers)) if data.transfers is not None else 0,
            "build_seconds": elapsed_s,
            "edge_kinds": _count_kinds(edges),
            "use_gtfs_transfers": use_gtfs_transfers,
            "use_inferred_transfers": use_inferred_transfers,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gtfs-dir", type=Path, default=DEFAULT_GTFS_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--no-gtfs-transfers", action="store_true")
    parser.add_argument("--no-inferred-transfers", action="store_true")
    args = parser.parse_args()

    gtfs_dir = args.gtfs_dir.resolve()
    out_path = args.out.resolve()
    if not gtfs_dir.is_dir():
        raise SystemExit(f"GTFS directory not found: {gtfs_dir}")

    print(f"Loading GTFS from {gtfs_dir} ...")
    payload = build_bundle_payload(
        gtfs_dir,
        use_gtfs_transfers=not args.no_gtfs_transfers,
        use_inferred_transfers=not args.no_inferred_transfers,
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("wb") as fh:
        pickle.dump(payload, fh, protocol=pickle.HIGHEST_PROTOCOL)

    stats = payload["stats"]
    print(f"Saved {out_path}")
    print(f"  stops={stats['stops']:,}")
    print(f"  edges_total={stats['edges_total']:,}")
    print(f"  edges_ride={stats['edges_ride']:,}")
    print(f"  edges_transfer={stats['edges_transfer']:,}")
    print(f"  edges_gtfs_transfer={stats['edges_gtfs_transfer']:,}")
    print(f"  edges_inferred_transfer={stats['edges_inferred_transfer']:,}")
    print(f"  gtfs_transfers_rows={stats['gtfs_transfers_rows']:,}")
    print(f"  build_seconds={stats['build_seconds']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
