"""Unit tests for transport area exploration (backend deterministic layer)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.product_shell import transport_exploration as tex  # noqa: E402
from backend.product_shell.services import agent_store  # noqa: E402


class TransportExplorationValidationTests(unittest.TestCase):
    def test_clamp_radius(self):
        self.assertEqual(tex.clamp_radius(None), 500)
        self.assertEqual(tex.clamp_radius(None, default=tex.DEFAULT_STOP_RADIUS_M), 1000)
        self.assertEqual(tex.clamp_radius(10000), 3000)
        self.assertEqual(tex.clamp_radius(10), 50)

    def test_default_exploration_radius(self):
        self.assertEqual(tex.default_exploration_radius_m(include_stops=True, include_pois=False), 1000)
        self.assertEqual(tex.default_exploration_radius_m(include_stops=False, include_pois=True), 500)
        self.assertEqual(tex.default_exploration_radius_m(include_stops=True, include_pois=True), 1000)

    def test_normalize_poi_categories(self):
        self.assertEqual(tex.normalize_poi_categories(None), ["all"])
        self.assertEqual(tex.normalize_poi_categories(["restaurant", "bogus", "cafe"]), ["restaurant", "cafe"])

    def test_is_deictic_query(self):
        self.assertTrue(tex.is_deictic_query("this station"))
        self.assertTrue(tex.is_deictic_query("around here"))
        self.assertFalse(tex.is_deictic_query("Republique"))

    def test_query_from_context_selected_station(self):
        ctx = {"world": {"transport": {"selected_station": {"station_name": "Chatelet"}}}}
        self.assertEqual(tex.query_from_agent_context(ctx), "Chatelet")

    def test_resolve_needs_context_without_selection(self):
        out = tex.resolve_exploration_center("this station", agent_context={"world": {"transport": {}}})
        self.assertEqual(out.get("status"), "needs_context")

    def test_filter_without_snapshot(self):
        agent_store.patch_world_state({"transport": {"last_exploration": None}})
        out = tex.filter_visible_results(radius_m=300)
        self.assertFalse(out.get("ok"))
        self.assertEqual(out.get("error"), "nothing_to_filter")


class TransportExplorationIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._bundle_ok = True
        try:
            from backend.product_shell import transport_engine as te

            te.get_bundle()
        except Exception:
            cls._bundle_ok = False

    def setUp(self):
        if not self._bundle_ok:
            self.skipTest("graph bundle unavailable")

    def test_nearby_stops_republique(self):
        out = tex.nearby_stops("Republique", radius_m=800, limit=10, mode="metro")
        self.assertTrue(out.get("ok"), out)
        self.assertTrue(out.get("center_resolved"))
        self.assertGreater(out.get("count", 0), 0)
        first = (out.get("nearby_stops") or [None])[0]
        self.assertIn("distance_m", first)
        self.assertIn("coordinates", first)

    def test_explore_area_republique(self):
        out = tex.explore_area(
            "Republique",
            radius_m=500,
            include_stops=True,
            include_pois=True,
            transport_modes=["all"],
            limit_stops=5,
            limit_pois=5,
        )
        self.assertTrue(out.get("ok"), out)
        self.assertGreaterEqual(out.get("counts", {}).get("stops", 0), 1)

    def test_filter_after_explore(self):
        tex.explore_area("Chatelet", radius_m=600, limit_stops=20, limit_pois=10)
        filtered = tex.filter_visible_results(radius_m=300, modes=["metro"])
        self.assertTrue(filtered.get("ok"), filtered)


if __name__ == "__main__":
    unittest.main()
