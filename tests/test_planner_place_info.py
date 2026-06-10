"""Planner routing for station (IDFM) vs POI (web) place info."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "work" / "atlas" / "src"))

from atlas_client.router.planner_place_info import (  # noqa: E402
    apply_place_info_routing,
    detect_place_info_intent,
)
from atlas_client.router.planner_shortcuts import try_planner_shortcut  # noqa: E402
from atlas_client.router.planner_validator import validate_step_semantics  # noqa: E402
from atlas_client.router.tool_executor import list_tools  # noqa: E402

ALLOWED = set(list_tools())

STATION_CTX = {
    "world": {
        "transport": {
            "last_place_lookup": {
                "query": "Place d'Italie",
                "place_kind": "station",
                "topic": "accessibility",
                "label": "Place d'Italie",
            }
        }
    }
}


class PlaceInfoIntentTests(unittest.TestCase):
    def test_info_about_station_ignores_api_mention(self):
        intent = detect_place_info_intent(
            "give me info about place d'italie use idfm api",
        )
        self.assertIsNotNone(intent)
        self.assertEqual(intent.topic, "about")
        self.assertEqual(intent.kind, "station")
        self.assertIn("italie", intent.query.lower())

    def test_follow_up_accessibly_inherits_station(self):
        intent = detect_place_info_intent(
            "now same way see if it's accessibly",
            agent_context=STATION_CTX,
        )
        self.assertIsNotNone(intent)
        self.assertEqual(intent.topic, "accessibility")
        self.assertEqual(intent.kind, "station")
        self.assertEqual(intent.query, "Place d'Italie")

    def test_topic_only_hours_inherits_station(self):
        intent = detect_place_info_intent(
            "what are the working hours",
            agent_context=STATION_CTX,
        )
        self.assertIsNotNone(intent)
        self.assertEqual(intent.topic, "hours")
        self.assertEqual(intent.query, "Place d'Italie")
        self.assertEqual(intent.kind, "station")

    def test_redirect_show_station_to_lookup(self):
        decision = apply_place_info_routing(
            {
                "status": "continue",
                "tool_name": "cspe_show_station_or_line_info",
                "args": {"query": "Place d'Italie"},
            },
            "give me info about place d'italie",
        )
        self.assertEqual(decision["tool_name"], "cspe_lookup_place_online")
        self.assertEqual(decision["args"]["topic"], "about")
        self.assertEqual(decision["args"]["kind"], "station")

    def test_fixup_wrong_lookup_topic(self):
        decision = apply_place_info_routing(
            {
                "status": "continue",
                "tool_name": "cspe_lookup_place_online",
                "args": {"query": "Place d'Italie", "topic": "about", "kind": "auto"},
            },
            "now same way see if it's accessibly",
            agent_context=STATION_CTX,
        )
        self.assertEqual(decision["args"]["topic"], "accessibility")
        self.assertEqual(decision["args"]["kind"], "station")

    def test_shortcut_station_accessibility(self):
        shortcut = try_planner_shortcut(
            "is Place d'Italie accessible",
            allowed_tools=ALLOWED,
        )
        self.assertIsNotNone(shortcut)
        self.assertEqual(shortcut["tool_name"], "cspe_lookup_place_online")
        self.assertEqual(shortcut["args"]["topic"], "accessibility")
        self.assertEqual(shortcut["args"]["kind"], "station")

    def test_validator_rejects_show_station_for_info(self):
        ok, _, err = validate_step_semantics(
            "cspe_show_station_or_line_info",
            {"query": "Place d'Italie"},
            user_text="give me info about place d'italie",
        )
        self.assertFalse(ok)
        self.assertIn("cspe_lookup_place_online", err)

    def test_hours_of_named_station(self):
        intent = detect_place_info_intent("what are working hours of république?")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.topic, "hours")
        self.assertEqual(intent.query.lower(), "république")
        self.assertEqual(intent.kind, "station")

    def test_accessibility_named_station(self):
        intent = detect_place_info_intent("is république accessible?")
        self.assertIsNotNone(intent)
        self.assertEqual(intent.topic, "accessibility")
        self.assertEqual(intent.kind, "station")
        self.assertIn("république", intent.query.lower())

    def test_hours_of_restaurant_near_station_stays_poi(self):
        intent = detect_place_info_intent(
            "what are the hours of the restaurant near république?"
        )
        self.assertIsNotNone(intent)
        self.assertEqual(intent.topic, "hours")
        self.assertEqual(intent.kind, "poi")


if __name__ == "__main__":
    unittest.main()
