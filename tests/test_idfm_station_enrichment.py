"""Tests for IDFM station enrichment (local graph stations only)."""

from __future__ import annotations

from backend.product_shell.services.agent_tools import lookup_place_for_chat
from backend.product_shell.services.idfm_client import local_id_to_stop_point_id


def test_local_stop_id_mapping():
    assert local_id_to_stop_point_id("IDFM:22006") == "stop_point:IDFM:22006"
    assert local_id_to_stop_point_id("st:IDFM:22006") == "stop_point:IDFM:22006"


def test_place_d_italie_station_lookup_uses_idfm(monkeypatch):
    import backend.product_shell.services.idfm_station_enrichment as enrich

    def _fake_enrich(local, *, topic, includes_today):
        return {
            "ok": True,
            "enrichment_source": "idfm",
            "idfm_summary": "Station: Place d'Italie\nLines: 5, 6, 7",
            "idfm_data": {"stop_area_id": "stop_area:IDFM:71033"},
            "web_search_query": None,
        }

    monkeypatch.setattr(enrich, "enrich_local_station", _fake_enrich)
    result = lookup_place_for_chat(
        "Place d'Italie",
        kind="station",
        topic="about",
        mode="metro",
        use_lcc=False,
    )
    assert result["ok"] is True
    assert result["place_kind"] == "station"
    assert result["enrichment_source"] == "idfm"
    assert result["web_search_query"] is None
    assert "Place d'Italie" in (result.get("idfm_summary") or "")
