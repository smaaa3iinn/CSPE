"""Response language detection for Atlas (English/French)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "work" / "atlas" / "src"))

from atlas_client.core.response_language import (  # noqa: E402
    detect_response_language,
    format_user_message_for_model,
    task_instruction,
)


class ResponseLanguageTests(unittest.TestCase):
    def test_french_exploration_query(self):
        self.assertEqual(
            detect_response_language("montre-moi les POIs autour de République"),
            "fr",
        )

    def test_english_route_query(self):
        self.assertEqual(
            detect_response_language("find a metro route from Nation to Orly"),
            "en",
        )

    def test_french_what_can_i_find(self):
        self.assertEqual(
            detect_response_language("what can I find around Nation?"),
            "en",
        )
        self.assertEqual(
            detect_response_language("qu'est-ce que je peux trouver autour de Nation ?"),
            "fr",
        )

    def test_user_message_prefix(self):
        msg = format_user_message_for_model("trajet de Châtelet à Nation")
        self.assertIn("[Reply in French]", msg)
        self.assertIn("Châtelet", msg)

    def test_task_instruction_french(self):
        self.assertIn("French", task_instruction("fr"))


if __name__ == "__main__":
    unittest.main()
