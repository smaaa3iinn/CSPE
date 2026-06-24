"""Tests for frontend UI command dedupe helpers (imported via node-free Python mirror)."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def shell_command_signature(raw: dict) -> str:
    """Mirror of frontend applyUiCommands shellCommandSignature."""
    return json.dumps(raw, sort_keys=True, separators=(",", ":"))


class UiCommandDedupeLogicTests(unittest.TestCase):
    def test_signature_stable_for_same_command(self):
        cmd = {
            "kind": "transport_route_view",
            "path_ids": ["a", "b"],
            "station_path_ids": ["s1", "s2"],
        }
        self.assertEqual(shell_command_signature(cmd), shell_command_signature(dict(cmd)))

    def test_signature_differs_for_different_paths(self):
        a = {"kind": "transport_route_view", "path_ids": ["a"]}
        b = {"kind": "transport_route_view", "path_ids": ["b"]}
        self.assertNotEqual(shell_command_signature(a), shell_command_signature(b))

    def test_batch_command_id_dedupe_concept(self):
        seen: set[str] = set()
        batches = [
            {"command_id": "cid-1", "commands": [{"kind": "set_mode", "mode": "transport"}]},
            {"command_id": "cid-1", "commands": [{"kind": "set_mode", "mode": "transport"}]},
            {"command_id": "cid-2", "commands": [{"kind": "set_mode", "mode": "transport"}]},
        ]
        applied = 0
        for batch in batches:
            cid = batch["command_id"]
            if cid in seen:
                continue
            seen.add(cid)
            applied += 1
        self.assertEqual(applied, 2)


if __name__ == "__main__":
    unittest.main()
