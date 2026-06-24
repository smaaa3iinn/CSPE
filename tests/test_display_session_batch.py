"""Tests for display session UI command batch metadata."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.product_shell.display_session import enrich_ui_command_batch  # noqa: E402


class DisplaySessionBatchTests(unittest.TestCase):
    def test_enrich_adds_target_and_source(self):
        batch = enrich_ui_command_batch(
            {"command_id": "abc", "commands": [{"kind": "transport_route_view", "path_ids": ["a"]}]},
            source="atlas_chat",
            target="active_display",
        )
        assert batch is not None
        self.assertEqual(batch["command_id"], "abc")
        self.assertEqual(batch["target"], "active_display")
        self.assertEqual(batch["source"], "atlas_chat")
        self.assertIn("created_at", batch)

    def test_enrich_none_when_empty(self):
        self.assertIsNone(enrich_ui_command_batch(None))
        self.assertIsNone(enrich_ui_command_batch({"command_id": "x", "commands": []}))


if __name__ == "__main__":
    unittest.main()
