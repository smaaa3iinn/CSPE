from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from flask import Flask, jsonify, request

from src.core.cache_bundle import GRAPH_MODES, load_or_build_graph_bundle
from src.core.queries import search_stops_autocomplete, shortest_path


def create_app() -> Flask:
    app = Flask(__name__)
    _bundle: dict | None = None

    def get_bundle() -> dict:
        nonlocal _bundle
        if _bundle is None:
            bundle_path = ROOT / "data" / "derived" / "routing" / "graph_bundle.pkl"
            popup_path = ROOT / "data" / "derived" / "stops" / "stop_popup_index.parquet"
            if not bundle_path.is_file():
                raise FileNotFoundError(f"Missing graph bundle: {bundle_path}")
            _bundle = load_or_build_graph_bundle(
                str(ROOT),
                cache_path=str(bundle_path),
                stop_popup_index_path=str(popup_path),
            )
        return _bundle

    @app.get("/health")
    def health():
        try:
            b = get_bundle()
            return jsonify(
                ok=True,
                cache_version=b.get("cache_version"),
                modes=list((b.get("graphs") or {}).keys()),
            )
        except Exception as e:
            return jsonify(ok=False, error=str(e)), 503

    @app.post("/v1/search_stops")
    def search_stops():
        try:
            body = request.get_json(silent=True) or {}
            query = (body.get("query") or "").strip()
            if not query:
                return jsonify(ok=False, error="missing_query"), 400
            limit = int(body.get("limit") or 20)
            mode = body.get("mode")
            if mode is not None and mode not in GRAPH_MODES:
                return jsonify(ok=False, error="invalid_mode"), 400
            use_lcc = bool(body.get("use_lcc", True))
            b = get_bundle()
            graph_key = mode or "all"
            G = (b["graphs_lcc"] if use_lcc else b["graphs"])[graph_key]
            rows = search_stops_autocomplete(G, query, limit=limit, mode=mode)
            return jsonify(ok=True, query=query, graph_mode=graph_key, stops=rows, count=len(rows))
        except Exception as e:
            return jsonify(ok=False, error=str(e)), 500

    @app.post("/v1/route")
    def route():
        try:
            body = request.get_json(silent=True) or {}
            a = str(body.get("from_stop_id") or body.get("from") or "").strip()
            b = str(body.get("to_stop_id") or body.get("to") or "").strip()
            if not a or not b:
                return jsonify(ok=False, error="missing_from_or_to"), 400
            mode = body.get("mode") or "all"
            if mode not in GRAPH_MODES:
                return jsonify(ok=False, error="invalid_mode"), 400
            use_lcc = bool(body.get("use_lcc", True))
            bundle = get_bundle()
            G = (bundle["graphs_lcc"] if use_lcc else bundle["graphs"])[mode]
            res = shortest_path(G, a, b)
            return jsonify(ok=True, graph_mode=mode, use_lcc=use_lcc, result=res)
        except Exception as e:
            return jsonify(ok=False, error=str(e)), 500

    return app


def main():
    import os

    app = create_app()
    host = os.getenv("CSPE_API_HOST", "127.0.0.1")
    port = int(os.getenv("CSPE_API_PORT", "5057"))
    app.run(host=host, port=port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    main()
