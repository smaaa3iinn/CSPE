"""Agent stop/station resolution must match manual UI disambiguation rules."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.product_shell.services import agent_store, agent_tools  # noqa: E402


class AgentStopDisambiguationTests(unittest.TestCase):
    def setUp(self):
        agent_store.patch_world_state({"transport": {"graph_mode": "all_mb", "use_lcc": False}})

    def test_single_station_still_exact(self):
        row = agent_tools.resolve_stop_query("Chatelet", mode="all_mb", use_lcc=False)
        self.assertEqual(row.get("status"), "exact")
        self.assertTrue(row.get("match"))

    def test_republique_is_ambiguous(self):
        row = agent_tools.resolve_stop_query("Republique", mode="all_mb", use_lcc=False)
        self.assertEqual(row.get("status"), "ambiguous")
        station_ids = {
            (m.get("station_id") or "").strip()
            for m in row.get("matches") or []
            if m.get("station_id")
        }
        self.assertGreaterEqual(len(station_ids), 2)

    def test_homonym_station_is_ambiguous(self):
        row = agent_tools.resolve_stop_query("Saint-Fargeau", mode="all_mb", use_lcc=False)
        self.assertEqual(row.get("status"), "ambiguous")

    def test_opaque_station_id_passthrough(self):
        row = agent_tools.resolve_stop_query(
            "st:IDFM:21902",
            mode="all_mb",
            use_lcc=False,
        )
        self.assertEqual(row.get("status"), "exact")
        self.assertEqual((row.get("match") or {}).get("station_id"), "st:IDFM:21902")

    def test_auto_pick_restores_legacy_behavior(self):
        row = agent_tools.resolve_stop_query(
            "Republique",
            mode="all_mb",
            use_lcc=False,
            auto_pick=True,
        )
        self.assertEqual(row.get("status"), "exact")
        self.assertEqual((row.get("match") or {}).get("station_id"), "st:IDFM:21902")

    def test_compute_route_needs_user_choice_for_ambiguous_origin(self):
        payload = agent_tools.compute_route_from_queries(
            "Republique",
            "Nation",
            mode="all_mb",
            use_lcc=False,
            routing_scope="station",
        )
        self.assertTrue(payload.get("needs_user_choice"))
        self.assertFalse(payload.get("ok"))
        details = (payload.get("error") or {}).get("details") or []
        self.assertTrue(any(d.get("endpoint") == "from" for d in details))
        from_detail = next(d for d in details if d.get("endpoint") == "from")
        self.assertTrue(from_detail.get("candidate_labels"))
        labels = from_detail.get("candidate_labels") or []
        self.assertTrue(str(labels[0]).strip().startswith("1."))


if __name__ == "__main__":
    unittest.main()
