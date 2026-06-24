"""Tests for shell turn capture and inline UI commands in /api/chat."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.product_shell.routers import shell as shell_router  # noqa: E402
from backend.product_shell.services import agent_tools  # noqa: E402


class ShellTurnCaptureTests(unittest.TestCase):
    def tearDown(self):
        shell_router.end_turn_capture()

    def test_begin_end_capture_collects_enqueued_commands(self):
        cid = shell_router.begin_turn_capture("test-cid-1")
        self.assertEqual(cid, "test-cid-1")
        route_cmds = agent_tools.shell_commands_for_route(
            {
                "from_query": "République",
                "to_query": "Orly",
                "mode": "metro",
                "use_lcc": True,
                "routing_scope": "station",
                "route": {
                    "ok": True,
                    "path": ["stop:a", "stop:b"],
                    "station_path": ["station:a", "station:b"],
                    "path_legs": [{"kind": "ride", "summary": "A to B"}],
                    "result": {"time_s": 1800, "transfers": 1},
                },
            }
        )
        n = shell_router.enqueue_commands(route_cmds)
        self.assertEqual(n, len(route_cmds))
        batch = shell_router.end_turn_capture()
        self.assertIsNotNone(batch)
        assert batch is not None
        self.assertEqual(batch["command_id"], "test-cid-1")
        self.assertEqual(len(batch["commands"]), len(route_cmds))
        kinds = {c["kind"] for c in batch["commands"]}
        self.assertIn("transport_route_view", kinds)
        self.assertIn("atlas_transport_action", kinds)
        route_view = next(c for c in batch["commands"] if c["kind"] == "transport_route_view")
        self.assertEqual(route_view.get("graph_mode"), "metro")
        self.assertEqual(route_view.get("use_lcc"), True)

    def test_shell_commands_for_route_includes_graph_mode_on_route_view(self):
        cmds = agent_tools.shell_commands_for_route(
            {
                "from_query": "A",
                "to_query": "B",
                "mode": "all_mb",
                "use_lcc": False,
                "routing_scope": "station",
                "route": {
                    "ok": True,
                    "path": ["stop:a", "stop:b"],
                    "station_path": ["station:a", "station:b"],
                    "result": {"time_s": 900, "transfers": 1},
                },
            }
        )
        route_view = next(c for c in cmds if c["kind"] == "transport_route_view")
        self.assertEqual(route_view.get("graph_mode"), "all_mb")
        self.assertFalse(route_view.get("use_lcc"))

    def test_end_capture_empty_when_no_commands(self):
        shell_router.begin_turn_capture("empty-cid")
        batch = shell_router.end_turn_capture()
        self.assertIsNone(batch)

    def test_enqueue_outside_capture_not_in_batch(self):
        shell_router.enqueue_commands([{"kind": "set_mode", "mode": "transport"}])
        shell_router.begin_turn_capture("inner")
        shell_router.enqueue_commands([{"kind": "transport_graph_mode", "graph_mode": "metro"}])
        batch = shell_router.end_turn_capture()
        self.assertIsNotNone(batch)
        assert batch is not None
        self.assertEqual(len(batch["commands"]), 1)
        self.assertEqual(batch["commands"][0]["kind"], "transport_graph_mode")


def _chat_test_client():
    """Minimal app — avoids product_shell.main startup warmup hang in tests."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend.product_shell.routers import chat as chat_module

    app = FastAPI()
    app.include_router(chat_module.router, prefix="/api")
    return TestClient(app)


class ChatInlineUiCommandsTests(unittest.TestCase):
    def setUp(self):
        with shell_router._lock:
            shell_router._queue.clear()

    @patch("backend.product_shell.routers.chat.send_text_and_wait")
    def test_post_chat_returns_inline_ui_commands(self, mock_wait):
        route_cmds = agent_tools.shell_commands_for_route(
            {
                "from_query": "République",
                "to_query": "Orly",
                "mode": "metro",
                "routing_scope": "station",
                "route": {
                    "ok": True,
                    "path": ["stop:x"],
                    "station_path": ["station:x", "station:y"],
                    "path_legs": [],
                    "result": {"time_s": 900, "transfers": 0},
                },
            }
        )

        def _side_effect(_msg: str):
            shell_router.enqueue_commands(route_cmds)
            return {"assistant": "Route ready.", "correlation_id": "abc123"}, None

        mock_wait.side_effect = _side_effect

        client = _chat_test_client()
        resp = client.post("/api/chat", json={"message": "route from République to Orly"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("ui_sync"), "inline")
        ui_cmds = data.get("ui_commands")
        self.assertIsNotNone(ui_cmds)
        self.assertEqual(ui_cmds["command_id"], "abc123")
        self.assertEqual(ui_cmds.get("target"), "active_display")
        self.assertEqual(ui_cmds.get("source"), "atlas_chat")
        self.assertGreaterEqual(len(ui_cmds["commands"]), 2)
        kinds = {c["kind"] for c in ui_cmds["commands"]}
        self.assertIn("transport_route_view", kinds)

    @patch("backend.product_shell.routers.chat.send_text_and_wait")
    def test_post_chat_no_ui_commands_when_none_enqueued(self, mock_wait):
        mock_wait.return_value = ({"assistant": "Hello."}, None)
        client = _chat_test_client()
        resp = client.post("/api/chat", json={"message": "hello"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIsNone(data.get("ui_commands"))
        self.assertEqual(data.get("ui_sync"), "none")


if __name__ == "__main__":
    unittest.main()
