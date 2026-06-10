"""Planner routing for map-sync POI/stop exploration."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "work" / "atlas" / "src"))

from atlas_client.router.planner_exploration import (  # noqa: E402
    apply_exploration_routing,
    detect_exploration_intent,
)
from atlas_client.router.planner_shortcuts import try_planner_shortcut  # noqa: E402
from atlas_client.router.planner_validator import validate_step_semantics  # noqa: E402
from atlas_client.router.tool_executor import list_tools  # noqa: E402

ALLOWED = set(list_tools())


class ExplorationIntentTests(unittest.TestCase):
    def test_show_pois_near_station(self):
        intent = detect_exploration_intent("show pois near république")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.tool, "cspe_nearby_pois")
        self.assertIn("république", intent.query.lower())

    def test_find_restaurants_around(self):
        intent = detect_exploration_intent("find restaurants around châtelet")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.tool, "cspe_nearby_pois")
        self.assertEqual(intent.categories, ("restaurant",))

    def test_whats_around(self):
        intent = detect_exploration_intent("what's around république")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.tool, "cspe_explore_area")

    def test_hours_question_not_exploration(self):
        intent = detect_exploration_intent("what are the working hours of république")
        self.assertIsNone(intent)

    def test_redirect_lookup_to_nearby_pois(self):
        decision = apply_exploration_routing(
            {
                "status": "continue",
                "tool_name": "cspe_lookup_place_online",
                "args": {"query": "république", "kind": "poi"},
            },
            "show pois near république",
        )
        self.assertEqual(decision["tool_name"], "cspe_nearby_pois")
        self.assertTrue(decision["args"]["sync_ui"])
        self.assertIn("république", decision["args"]["query"].lower())

    def test_shortcut_show_pois(self):
        shortcut = try_planner_shortcut(
            "show pois near république",
            allowed_tools=ALLOWED,
        )
        self.assertIsNotNone(shortcut)
        self.assertEqual(shortcut["tool_name"], "cspe_nearby_pois")
        self.assertTrue(shortcut["args"]["sync_ui"])

    def test_validator_rejects_lookup_for_exploration(self):
        ok, _, err = validate_step_semantics(
            "cspe_lookup_place_online",
            {"query": "république", "kind": "poi"},
            user_text="show pois near république",
        )
        self.assertFalse(ok)
        self.assertIn("cspe_nearby_pois", err)


if __name__ == "__main__":
    unittest.main()
