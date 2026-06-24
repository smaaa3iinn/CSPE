"""Route computation must honor active UI graph mode without escalating to ``all``."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.product_shell.services import agent_store, agent_tools  # noqa: E402


class AgentRouteModeTests(unittest.TestCase):
    def setUp(self):
        agent_store.patch_world_state({"transport": {"graph_mode": "all_mb", "use_lcc": False}})

    def test_resolve_stop_query_stays_on_requested_mode(self):
        row = agent_tools.resolve_stop_query("Chatelet", mode="all_mb", use_lcc=False)
        self.assertEqual(row.get("mode"), "all_mb")

    def test_compute_route_does_not_escalate_to_all(self):
        payload = agent_tools.compute_route_from_queries(
            "Boulainvilliers",
            "Chateau de Vincennes",
            mode="all_mb",
            use_lcc=False,
            routing_scope="station",
        )
        self.assertEqual(payload.get("mode"), "all_mb")
        route = payload.get("route") or {}
        if route.get("ok"):
            legs = route.get("path_legs") or []
            modes = {str(leg.get("mode") or "") for leg in legs}
            self.assertNotIn("bus", modes)


if __name__ == "__main__":
    unittest.main()
