"""Structured intent routing: central router, domain routers, tool adapter."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "work" / "atlas" / "src"))

from atlas_client.router.central_intent_router import route_intent  # noqa: E402
from atlas_client.router.domain_routers import route_transport, route_poi, route_visual_3d, route_web  # noqa: E402
from atlas_client.router.intent_fallback import try_deterministic_intent  # noqa: E402
from atlas_client.router.intent_schema import IntentEntities, StructuredIntent  # noqa: E402
from atlas_client.router.tool_executor import list_tools  # noqa: E402
from atlas_client.router.tool_plan_adapter import routing_decision_to_planner_plan  # noqa: E402

ALLOWED = set(list_tools())

STATION_CTX = {
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

REPUBLIQUE_POI_CTX = {
    "router": {
        "last_tool": "cspe_nearby_pois",
        "last_tool_args": {"query": "République"},
    },
    "world": {
        "transport": {
            "last_exploration": {
                "query": "République",
                "center": {"station_name": "République", "label": "République"},
            }
        }
    },
}


def _route(user_text: str, *, agent_context=None):
    intent = try_deterministic_intent(user_text, agent_context=agent_context)
    if intent is None:
        intent = StructuredIntent(
            domain="general_chat",
            intent="general_chat",
            raw_user_text=user_text,
            normalized_query=user_text,
        )
    decision = route_intent(intent, agent_context=agent_context)
    plan = routing_decision_to_planner_plan(decision, allowed_tools=ALLOWED)
    return decision, plan


class IntentRoutingTests(unittest.TestCase):
    def test_route_republique_to_nation(self):
        decision, plan = _route("route from République to Nation")
        self.assertEqual(decision.normalized_intent.domain, "transport")
        self.assertEqual(decision.normalized_intent.intent, "route")
        self.assertEqual(plan.steps[0].tool, "cspe_compute_route")
        self.assertIn("local_graph", decision.execution_plan.data_sources)
        self.assertNotIn("idfm", decision.execution_plan.data_sources)
        self.assertNotIn("serpapi", decision.execution_plan.data_sources)

    def test_republique_accessible(self):
        decision, plan = _route("is République accessible?")
        self.assertEqual(decision.normalized_intent.intent, "station_accessibility")
        self.assertFalse(decision.normalized_intent.ui_action)
        self.assertEqual(plan.steps[0].tool, "cspe_lookup_place_online")
        self.assertEqual(plan.steps[0].arguments.get("topic"), "accessibility")
        self.assertIn("idfm", decision.execution_plan.data_sources)
        self.assertFalse(decision.execution_plan.ui_triggered)

    def test_departures_line_11(self):
        decision, plan = _route("next departures for République line 11")
        self.assertIn(
            decision.normalized_intent.intent,
            ("station_departures", "station_hours"),
        )
        self.assertEqual(plan.steps[0].tool, "cspe_lookup_place_online")
        self.assertTrue(plan.steps[0].arguments.get("includes_today") or decision.normalized_intent.intent == "station_departures")

    def test_working_hours_republique(self):
        decision, plan = _route("working hours of République")
        self.assertEqual(decision.normalized_intent.intent, "station_hours")
        self.assertEqual(decision.normalized_intent.domain, "transport")
        self.assertEqual(plan.steps[0].arguments.get("topic"), "hours")
        self.assertEqual(plan.steps[0].arguments.get("kind"), "station")
        self.assertFalse(decision.normalized_intent.ui_action)

    def test_info_place_d_italie(self):
        decision, plan = _route("give me information about Place d'Italie")
        self.assertEqual(decision.normalized_intent.intent, "station_info")
        self.assertEqual(plan.steps[0].tool, "cspe_lookup_place_online")
        self.assertEqual(plan.steps[0].arguments.get("topic"), "about")

    def test_show_pois_republique(self):
        decision, plan = _route("show me POIs around République")
        self.assertEqual(decision.normalized_intent.domain, "poi")
        self.assertEqual(decision.normalized_intent.intent, "poi_search")
        self.assertTrue(decision.normalized_intent.ui_action)
        self.assertEqual(plan.steps[0].tool, "cspe_nearby_pois")
        self.assertTrue(plan.steps[0].arguments.get("sync_ui"))
        self.assertIn("poi_index", decision.execution_plan.data_sources)

    def test_restaurants_near_republique_text_only(self):
        decision, plan = _route("restaurants near République")
        self.assertEqual(decision.normalized_intent.domain, "poi")
        self.assertEqual(plan.steps[0].tool, "cspe_nearby_pois")
        self.assertFalse(decision.normalized_intent.ui_action)
        self.assertFalse(plan.steps[0].arguments.get("sync_ui"))

    def test_open_3d_graph(self):
        decision, plan = _route("open 3D graph")
        self.assertEqual(decision.normalized_intent.domain, "visual_3d")
        self.assertEqual(plan.steps[0].tool, "cspe_open_graph3d")
        self.assertTrue(decision.execution_plan.ui_triggered)

    def test_highlight_line_11(self):
        decision, plan = _route("highlight line 11")
        self.assertEqual(decision.normalized_intent.domain, "map_ui")
        self.assertEqual(plan.steps[0].tool, "cspe_transport_action")

    def test_web_hotels(self):
        decision, plan = _route("search the web for nearby hotels")
        self.assertEqual(decision.normalized_intent.domain, "web")
        self.assertEqual(plan.steps[0].tool, "web_search")
        self.assertIn("serpapi", decision.execution_plan.data_sources)

    def test_ambiguous_republique_hours(self):
        decision, plan = _route("République hours")
        self.assertEqual(decision.normalized_intent.intent, "station_hours")
        self.assertEqual(decision.normalized_intent.domain, "transport")
        self.assertFalse(decision.normalized_intent.ui_action)

    def test_transport_router_local_graph_only_for_route(self):
        intent = StructuredIntent(
            domain="transport",
            intent="route",
            entities=IntentEntities(origin="A", destination="B", mode="metro"),
            ui_action=True,
            response_type="text_and_ui",
        )
        plan = route_transport(intent)
        self.assertEqual(plan.steps[0].tool, "cspe_compute_route")
        self.assertEqual(plan.steps[0].data_sources, ["local_graph"])

    def test_poi_router_not_idfm(self):
        intent = StructuredIntent(
            domain="poi",
            intent="poi_search",
            entities=IntentEntities(station="République", poi_category="restaurant"),
            ui_action=False,
            response_type="text",
        )
        plan = route_poi(intent)
        self.assertIn("poi_index", plan.data_sources)
        self.assertNotIn("idfm", plan.data_sources)

    def test_no_tool_names_in_intent_schema(self):
        """Structured intent uses domain/intent only — adapter produces tools."""
        intent = try_deterministic_intent("route from République to Nation")
        self.assertIsNotNone(intent)
        d = intent.to_dict()
        self.assertNotIn("cspe_", str(d))
        self.assertNotIn("tool", d)

    def test_intent_router_flag_default_off(self):
        prev = os.environ.get("ATLAS_INTENT_ROUTER")
        try:
            os.environ.pop("ATLAS_INTENT_ROUTER", None)
            from atlas_client.core.planner_config import intent_router_enabled

            self.assertFalse(intent_router_enabled())
            os.environ["ATLAS_INTENT_ROUTER"] = "1"
            self.assertTrue(intent_router_enabled())
        finally:
            if prev is not None:
                os.environ["ATLAS_INTENT_ROUTER"] = prev
            else:
                os.environ.pop("ATLAS_INTENT_ROUTER", None)

    def test_chatelet_next_departures(self):
        decision, plan = _route("give me chatelet next departures")
        self.assertEqual(decision.normalized_intent.intent, "station_departures")
        self.assertEqual(plan.steps[0].tool, "cspe_lookup_place_online")
        self.assertEqual(plan.steps[0].arguments.get("query"), "chatelet")
        self.assertTrue(plan.steps[0].arguments.get("includes_today"))
        self.assertIn("idfm", decision.execution_plan.data_sources)

    def test_filter_by_restaurants(self):
        decision, plan = _route("filter by restaurants")
        self.assertEqual(decision.normalized_intent.intent, "poi_filter")
        self.assertEqual(plan.steps[0].tool, "cspe_filter_visible_results")
        self.assertTrue(plan.steps[0].arguments.get("sync_ui"))

    def test_poi_hours_after_exploration_uses_lookup_online(self):
        decision, plan = _route(
            "look up starbucks opening hours",
            agent_context=REPUBLIQUE_POI_CTX,
        )
        self.assertEqual(decision.normalized_intent.intent, "poi_info")
        self.assertEqual(plan.steps[0].tool, "cspe_lookup_place_online")
        self.assertEqual(plan.steps[0].arguments.get("query"), "starbucks")
        self.assertEqual(plan.steps[0].arguments.get("topic"), "hours")
        self.assertEqual(plan.steps[0].arguments.get("kind"), "poi")
        self.assertEqual(plan.steps[0].arguments.get("near_query"), "République")

    def test_openai_misroute_poi_search_hours_overridden(self):
        misroute = StructuredIntent(
            domain="poi",
            intent="poi_search",
            entities=IntentEntities(place="Starbucks", poi_category="cafe", mode="metro"),
            ui_action=False,
            response_type="text",
            raw_user_text="look up starbucks opening hours",
            normalized_query="Starbucks",
        )
        decision = route_intent(misroute, agent_context=REPUBLIQUE_POI_CTX)
        plan = routing_decision_to_planner_plan(decision, allowed_tools=ALLOWED)
        self.assertEqual(decision.normalized_intent.intent, "poi_info")
        self.assertEqual(plan.steps[0].tool, "cspe_lookup_place_online")
        self.assertEqual(plan.steps[0].arguments.get("near_query"), "République")

    def test_now_around_place_d_italie(self):
        decision, plan = _route("now around place d'italie")
        self.assertIn(decision.normalized_intent.intent, ("explore_area", "poi_search", "nearby_stops"))
        self.assertNotEqual(plan.steps[0].tool, "memory_search")

    def test_stops_query_normalized(self):
        decision, plan = _route("now show me stops around place d'italie")
        self.assertEqual(decision.normalized_intent.intent, "nearby_stops")
        self.assertEqual(plan.steps[0].arguments.get("query"), "place d'italie")

    def test_station_prefix_maison_blanche_nearby(self):
        decision, plan = _route("now around station maison blanche")
        self.assertEqual(decision.normalized_intent.intent, "nearby_stops")
        self.assertEqual(plan.steps[0].tool, "cspe_nearby_stops")
        self.assertEqual(plan.steps[0].arguments.get("query"), "maison blanche")

    def test_gare_du_nord_route_endpoint_recovery(self):
        decision, plan = _route("find a metro route from Gare du Nord to Châtelet")
        self.assertEqual(plan.steps[0].tool, "cspe_compute_route")
        self.assertEqual(plan.steps[0].arguments.get("from_query"), "Gare du Nord")
        self.assertEqual(plan.steps[0].arguments.get("to_query"), "Châtelet")

    def test_what_can_i_find_around_nation_syncs_ui(self):
        decision, plan = _route("what can I find around Nation?")
        self.assertIn(decision.normalized_intent.intent, ("poi_search", "explore_area"))
        self.assertTrue(decision.normalized_intent.ui_action)
        self.assertIn(plan.steps[0].tool, ("cspe_nearby_pois", "cspe_explore_area"))
        self.assertTrue(plan.steps[0].arguments.get("sync_ui"))


if __name__ == "__main__":
    unittest.main()
