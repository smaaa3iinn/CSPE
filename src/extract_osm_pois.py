from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import TextIO

import osmium

RELEVANT_TAGS = ("amenity", "shop", "tourism", "leisure")


class POIExtractor(osmium.SimpleHandler):
    def __init__(self, output_file: TextIO) -> None:
        super().__init__()
        self.output_file = output_file
        self.category_counts: dict[str, int] = {}
        self.feature_count = 0
        self._wrote_feature = False

    def write_header(self) -> None:
        self.output_file.write('{"type":"FeatureCollection","features":[')

    def write_footer(self) -> None:
        self.output_file.write("]}")

    def node(self, node: osmium.osm.Node) -> None:
        if not node.location.valid():
            return

        tag_dict = {tag.k: tag.v for tag in node.tags}
        category_key = next((key for key in RELEVANT_TAGS if key in tag_dict and tag_dict[key]), None)
        if category_key is None:
            return

        category_value = tag_dict[category_key]
        category = f"{category_key}={category_value}"
        self.category_counts[category] = self.category_counts.get(category, 0) + 1

        feature = {
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [float(node.location.lon), float(node.location.lat)],
            },
            "properties": {
                "name": tag_dict.get("name"),
                "category": category,
                "category_key": category_key,
                "category_value": category_value,
            },
        }
        if self._wrote_feature:
            self.output_file.write(",")
        self.output_file.write(json.dumps(feature, ensure_ascii=False, separators=(",", ":")))
        self._wrote_feature = True
        self.feature_count += 1


def extract_pois(input_path: Path, output_path: Path) -> dict:
    with output_path.open("w", encoding="utf-8") as output_file:
        handler = POIExtractor(output_file)
        handler.write_header()
        handler.apply_file(str(input_path), locations=True)
        handler.write_footer()

    category_counts = dict(sorted(handler.category_counts.items(), key=lambda item: (-item[1], item[0])))
    return {
        "input_path": str(input_path),
        "output_path": str(output_path),
        "feature_count": handler.feature_count,
        "category_count": len(category_counts),
        "output_size_bytes": output_path.stat().st_size,
        "top_categories": list(category_counts.items())[:25],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract point-of-interest nodes from an OSM PBF file.")
    parser.add_argument("input_path", type=Path, help="Path to the .osm.pbf file")
    parser.add_argument("output_path", type=Path, help="Path to the output GeoJSON file")
    args = parser.parse_args()

    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    summary = extract_pois(args.input_path, args.output_path)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
