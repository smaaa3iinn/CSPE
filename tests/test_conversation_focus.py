"""Tests for multi-turn conversation focus resolution."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "work" / "atlas" / "src"))

from atlas_client.router.conversation_focus import resolve_conversation_focus  # noqa: E402


class ConversationFocusTests(unittest.TestCase):
    def test_last_place_lookup_from_world(self):
        ctx = {
            "world": {
                "transport": {
                    "last_place_lookup": {
                        "query": "Place d'Italie",
                        "place_kind": "station",
                        "topic": "about",
                        "label": "Place d'Italie",
                    }
                }
            }
        }
        focus = resolve_conversation_focus(ctx)
        self.assertIsNotNone(focus)
        self.assertEqual(focus["query"], "Place d'Italie")

    def test_router_last_tool_lookup(self):
        ctx = {
            "router": {
                "last_tool": "cspe_lookup_place_online",
                "last_tool_args": {
                    "query": "Chatelet",
                    "kind": "station",
                    "topic": "accessibility",
                },
            }
        }
        focus = resolve_conversation_focus(ctx)
        self.assertIsNotNone(focus)
        self.assertEqual(focus["query"], "Chatelet")
        self.assertEqual(focus["place_kind"], "station")

    def test_exploration_center_fallback(self):
        ctx = {
            "world": {
                "transport": {
                    "last_exploration": {
                        "query": "Republique",
                        "center": {"station_name": "Republique"},
                    }
                }
            }
        }
        focus = resolve_conversation_focus(ctx)
        self.assertIsNotNone(focus)
        self.assertEqual(focus["query"], "Republique")


if __name__ == "__main__":
    unittest.main()
