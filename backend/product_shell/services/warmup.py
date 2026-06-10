"""Best-effort product shell warmup for first-turn transport reliability.

The warmup runs in a background thread. It should never prevent the API from
starting; failures are captured in status and normal endpoints still report
their own errors (for example missing data bundle or Mapbox token).
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

from src.core.project_logs import log_compact_line, log_startup

_lock = threading.Lock()
_started = False
_status: dict[str, Any] = {
    "started": False,
    "running": False,
    "complete": False,
    "ok": None,
    "started_at": None,
    "finished_at": None,
    "elapsed_ms": None,
    "steps": [],
    "errors": [],
}


def warmup_status() -> dict[str, Any]:
    with _lock:
        return {
            **_status,
            "steps": list(_status.get("steps") or []),
            "errors": list(_status.get("errors") or []),
        }


def start_background_warmup() -> None:
    """Start warmup once unless disabled by PRODUCT_SHELL_WARMUP=0."""

    global _started
    if os.getenv("PRODUCT_SHELL_WARMUP", "1").strip().lower() in {"0", "false", "no"}:
        with _lock:
            _status.update({"started": False, "running": False, "complete": True, "ok": True})
        log_startup("Transport warmup disabled")
        return

    with _lock:
        if _started:
            return
        _started = True
        _status.update(
            {
                "started": True,
                "running": True,
                "complete": False,
                "ok": None,
                "started_at": time.time(),
                "finished_at": None,
                "elapsed_ms": None,
                "steps": [],
                "errors": [],
            }
        )

    thread = threading.Thread(target=_run_warmup, name="cspe-transport-warmup", daemon=True)
    thread.start()


def _record_step(name: str, elapsed_ms: float, ok: bool, error: str | None = None) -> None:
    row = {"name": name, "elapsed_ms": round(elapsed_ms, 1), "ok": ok}
    if error:
        row["error"] = error
    with _lock:
        _status.setdefault("steps", []).append(row)
        if error:
            _status.setdefault("errors", []).append(row)


def _timed_step(name: str, fn) -> None:
    t0 = time.perf_counter()
    try:
        fn()
    except Exception as exc:  # noqa: BLE001 - warmup must be best-effort
        elapsed = (time.perf_counter() - t0) * 1000.0
        _record_step(name, elapsed, False, str(exc))
        log_compact_line(f"[Startup] warmup step failed name={name} ms={elapsed:.0f} err={exc!r}")
        return
    elapsed = (time.perf_counter() - t0) * 1000.0
    _record_step(name, elapsed, True)
    log_compact_line(f"[Startup] warmup step ok name={name} ms={elapsed:.0f}")


def _run_warmup() -> None:
    from backend.product_shell import transport_engine as te

    log_startup("Transport warmup started")
    t0 = time.perf_counter()

    _timed_step("bundle", te.get_bundle)
    _timed_step("stats:metro", lambda: te.graph_stats("metro", False))
    _timed_step("stats:all", lambda: te.graph_stats("all", False))
    _timed_step("station_layer:metro:false", lambda: te.station_layer_for("metro", False))
    _timed_step("station_layer:metro:true", lambda: te.station_layer_for("metro", True))
    _timed_step("line_geometries", te._line_geometries)
    _timed_step("render_graphs", te._render_graphs)
    _timed_step("poi_lookup", te._poi_lookup)

    # Warm the two most common static map variants if a Mapbox token is present.
    token, _src = te.get_mapbox_token()
    if token:
        for viz_mode in ("geographic", "network_3d"):
            _timed_step(
                f"map:metro:{viz_mode}:station",
                lambda viz_mode=viz_mode: te.render_transport_map_html(
                    mode="metro",
                    use_lcc=False,
                    viz_mode=viz_mode,
                    graph_viz_mode="station",
                    path_stop_ids=None,
                    path_station_ids=None,
                    selected_stop_id=None,
                    selected_station_id=None,
                    show_transfers=False,
                    poi_radius_m=300,
                    poi_limit=25,
                    poi_category_key=None,
                ),
            )
    else:
        _record_step("map:skipped", 0.0, True, "Mapbox token missing")

    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    with _lock:
        errors = list(_status.get("errors") or [])
        _status.update(
            {
                "running": False,
                "complete": True,
                "ok": not errors,
                "finished_at": time.time(),
                "elapsed_ms": round(elapsed_ms, 1),
            }
        )
    log_startup(f"Transport warmup complete ok={not bool(errors)} elapsed_ms={elapsed_ms:.0f}")
