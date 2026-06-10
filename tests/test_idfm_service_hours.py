"""Unit tests for IDFM service hours parsing and summaries."""

from __future__ import annotations

from backend.product_shell.services.idfm_service_hours import (
    format_navitia_time,
    official_timetable_link,
    summarize_service_hours,
    _parse_departure,
    _parse_stop_schedule,
)


def test_format_navitia_time():
    assert format_navitia_time("20260610T053000") == "05:30"
    assert format_navitia_time("20260610T031400") == "03:14"


def test_parse_departure():
    row = _parse_departure(
        {
            "display_informations": {
                "code": "5",
                "direction": "Bobigny",
                "commercial_mode": "Metro",
            },
            "stop_date_time": {"departure_date_time": "20260610T053000"},
        }
    )
    assert row is not None
    assert row["line"] == "5"
    assert row["departure_time"] == "05:30"


def test_parse_stop_schedule():
    row = _parse_stop_schedule(
        {
            "display_informations": {"code": "6", "direction": "Nation", "commercial_mode": "Metro"},
            "first_datetime": {"date_time": "20260610T053442"},
            "last_datetime": {"date_time": "20260611T010337"},
        }
    )
    assert row is not None
    assert row["first_service"] == "05:34"
    assert row["last_service"] == "01:03"


def test_official_timetable_link_metro():
    url = official_timetable_link(line_code="5", commercial_mode="Metro")
    assert url is not None
    assert "metro-5" in url


def test_summarize_service_hours_includes_distinction():
    summary = summarize_service_hours(
        {
            "service_operating_hours": {
                "next_departures": [
                    {"line": "5", "direction": "Bobigny", "departure_time": "05:30", "mode": "Metro"}
                ],
                "line_service_windows": [
                    {
                        "line": "5",
                        "direction": "Bobigny",
                        "mode": "Metro",
                        "first_service": "05:30",
                        "last_service": "00:42",
                    }
                ],
                "timetable_links": [{"line": "5 (Metro)", "url": "https://www.ratp.fr/en/horaires?line=metro-5"}],
                "errors": [],
            }
        },
        station_label="Place d'Italie",
    )
    text = "\n".join(summary)
    assert "Station building opening hours" in text
    assert "Next scheduled departures" in text
    assert "05:30" in text
