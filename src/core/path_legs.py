"""Structured route leg breakdown for UI text and map styling."""

from __future__ import annotations

from typing import Any

import networkx as nx

from src.core.route_styles import path_edge_style, ride_leg_key


def _safe_number(value: Any) -> float | None:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if num != num:
        return None
    return num


def _stop_name(G: nx.Graph, stop_id: str) -> str:
    stop_id = str(stop_id)
    if stop_id not in G:
        return stop_id
    return str(G.nodes[stop_id].get("stop_name") or stop_id)


def _station_for_stop(station_idx: Any | None, stop_id: str) -> tuple[str | None, str | None]:
    if station_idx is None:
        return None, None
    stop_id = str(stop_id)
    station_id = station_idx.stop_to_station.get(stop_id)
    if not station_id:
        return None, None
    station_name = station_idx.station_label.get(station_id, station_id)
    return str(station_id), str(station_name)


def _stop_row(G: nx.Graph, stop_id: str, station_idx: Any | None) -> dict[str, str | None]:
    station_id, station_name = _station_for_stop(station_idx, stop_id)
    return {
        "stop_id": str(stop_id),
        "stop_name": _stop_name(G, stop_id),
        "station_id": station_id,
        "station_name": station_name,
    }


def _collapse_station_names(stops: list[dict[str, str | None]]) -> list[str]:
    labels: list[str] = []
    for stop in stops:
        label = str(stop.get("station_name") or stop.get("stop_name") or stop.get("stop_id") or "?")
        if labels and labels[-1] == label:
            continue
        labels.append(label)
    return labels


def _format_transfer_summary(
    G: nx.Graph,
    from_stop: str,
    to_stop: str,
    *,
    station_idx: Any | None,
    time_s: float | None,
    distance_m: float | None,
) -> str:
    from_row = _stop_row(G, from_stop, station_idx)
    to_row = _stop_row(G, to_stop, station_idx)
    from_station = from_row.get("station_id")
    to_station = to_row.get("station_id")
    time_bit = ""
    if time_s is not None and time_s > 0:
        if time_s >= 60:
            time_bit = f" (~{time_s / 60:.0f} min)"
        else:
            time_bit = f" (~{int(time_s)} s)"
    dist_bit = ""
    if distance_m is not None and distance_m > 0:
        dist_bit = f", {distance_m:.0f} m" if distance_m < 1000 else f", {distance_m / 1000:.1f} km"

    if from_station and to_station and from_station == to_station:
        station_name = from_row.get("station_name") or from_station
        return f"Transfer at {station_name}{time_bit}"

    from_label = str(from_row.get("station_name") or from_row.get("stop_name") or from_stop)
    to_label = str(to_row.get("station_name") or to_row.get("stop_name") or to_stop)
    return f"Walk transfer{time_bit}{dist_bit}: {from_label} → {to_label}"


def describe_path_legs(
    G: nx.Graph,
    path: list[str] | None,
    *,
    station_idx: Any | None = None,
    current_mode: str = "all",
) -> dict[str, Any]:
    if not path or len(path) < 1:
        return {"legs": [], "text_lines": []}

    path = [str(x) for x in path]
    if len(path) == 1:
        stop = _stop_row(G, path[0], station_idx)
        label = str(stop.get("station_name") or stop.get("stop_name") or path[0])
        leg = {
            "kind": "ride",
            "mode": current_mode if current_mode != "all" else "other",
            "line_label": "Start",
            "color": path_edge_style({}, current_mode)["color"],
            "stops": [stop],
            "distance_m": 0.0,
            "time_s": 0.0,
            "summary": label,
        }
        return {"legs": [leg], "text_lines": [label]}

    legs: list[dict[str, Any]] = []
    current_ride: dict[str, Any] | None = None

    def flush_ride() -> None:
        nonlocal current_ride
        if not current_ride:
            return
        stops = current_ride["stops"]
        labels = _collapse_station_names(stops)
        current_ride["summary"] = f"{current_ride['line_label']}: {' → '.join(labels)}"
        legs.append(current_ride)
        current_ride = None

    for u, v in zip(path, path[1:]):
        data = G.get_edge_data(u, v) or {}
        style = path_edge_style(data, current_mode)
        distance_m = _safe_number(data.get("distance_m"))
        if distance_m is None:
            distance_m = _safe_number(data.get("weight_m"))
        time_s = _safe_number(data.get("time_s"))

        if style["edge_kind"] == "transfer":
            flush_ride()
            summary = _format_transfer_summary(
                G,
                u,
                v,
                station_idx=station_idx,
                time_s=time_s,
                distance_m=distance_m,
            )
            legs.append(
                {
                    "kind": "transfer",
                    "mode": "transfer",
                    "line_label": "Walk transfer",
                    "color": style["color"],
                    "stops": [_stop_row(G, u, station_idx), _stop_row(G, v, station_idx)],
                    "distance_m": distance_m,
                    "time_s": time_s,
                    "summary": summary,
                }
            )
            continue

        key = ride_leg_key(style)
        if current_ride and current_ride.get("_key") == key:
            current_ride["stops"].append(_stop_row(G, v, station_idx))
            if distance_m is not None:
                current_ride["distance_m"] = (current_ride.get("distance_m") or 0.0) + distance_m
            if time_s is not None:
                current_ride["time_s"] = (current_ride.get("time_s") or 0.0) + time_s
            continue

        flush_ride()
        current_ride = {
            "_key": key,
            "kind": "ride",
            "mode": style["mode"],
            "line_label": style["line_label"],
            "color": style["color"],
            "stops": [_stop_row(G, u, station_idx), _stop_row(G, v, station_idx)],
            "distance_m": distance_m,
            "time_s": time_s,
            "summary": "",
        }

    flush_ride()

    text_lines = [str(leg["summary"]) for leg in legs if leg.get("summary")]
    for leg in legs:
        leg.pop("_key", None)
    return {"legs": legs, "text_lines": text_lines}
