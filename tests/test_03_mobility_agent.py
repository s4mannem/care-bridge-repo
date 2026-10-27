"""Unit and integration tests for Plan 03 — Transit & Community Evidence Agent (Evidence Agent B)."""

from __future__ import annotations

import unittest
from typing import Any, Dict

from carebridge.agents.mobility_agent import (
    MANDATORY_STOP_PROXIMITY_CAVEAT,
    MOBILITY_AGENT_INSTRUCTION,
    build_transit_community_agent,
    fetch_county_mobility_evidence,
)
from carebridge.contracts.evidence_models import MobilityEvidence
from carebridge.contracts.state_keys import (
    STATE_HEALTH_EVIDENCE,
    STATE_MOBILITY_EVIDENCE,
    STATE_PLAN_REQUEST,
)
from carebridge.mocks.fulton_fixtures import build_mock_mobility_evidence
from carebridge.security.race_blind_guard import (
    PolicyViolationError,
    assert_no_pii_in_payload,
    assert_race_blind_planner_input,
)
from carebridge.telemetry.otel import get_tracer, set_current_request_id
from google.adk.runners import InMemoryRunner  # type: ignore


class NotFound(Exception):
    """Simulated Google Cloud BigQuery NotFound exception when optional GTFS views are absent."""


class _DummyToolContext:
    def __init__(self, state: Dict[str, Any] | None = None) -> None:
        self.agent_name = "transit_community_agent"
        self.state: Dict[str, Any] = state if state is not None else {}


class TestPlan03TransitCommunityAgent(unittest.TestCase):
    """Verifies Plan 03 Transit & Community Evidence Agent tools, graceful degradation, guardrails & telemetry."""

    def test_01_fetch_mobility_evidence_enabled_fulton_13121(self) -> None:
        """When optional datasets are enabled, returns valid MobilityEvidence with MARTA stops and venues."""
        ctx = _DummyToolContext(state={STATE_PLAN_REQUEST: {"county_fips": "13121"}})
        raw = fetch_county_mobility_evidence(
            county_fips="13121",
            include_optional_datasets=True,
            tool_context=ctx,
        )
        evidence = MobilityEvidence.model_validate(raw)

        self.assertEqual(evidence.county_fips, "13121")
        self.assertTrue(evidence.marta_gtfs_available)
        self.assertTrue(evidence.usda_food_access_available)
        self.assertTrue(evidence.imls_venues_available)
        self.assertIn(len(evidence.tract_mobility), (12, 204))

        total_venues = sum(len(tm.candidate_venues) for tm in evidence.tract_mobility)
        self.assertIn(total_venues, (6, 38))

        # Verify parallel state isolation: writes strictly to mobility_evidence, never touching health_evidence
        self.assertIn(STATE_MOBILITY_EVIDENCE, ctx.state)
        self.assertNotIn(STATE_HEALTH_EVIDENCE, ctx.state)
        assert_race_blind_planner_input(ctx.state[STATE_MOBILITY_EVIDENCE])
        assert_no_pii_in_payload(ctx.state[STATE_MOBILITY_EVIDENCE])

    def test_02_graceful_degradation_when_optional_disabled_or_not_found(self) -> None:
        """Degrades gracefully without raising when include_optional_datasets=False or BigQuery raises NotFound."""
        # Case A: include_optional_datasets=False parameter
        ctx_disabled = _DummyToolContext()
        raw_disabled = fetch_county_mobility_evidence(
            county_fips="13121",
            include_optional_datasets=False,
            tool_context=ctx_disabled,
        )
        ev_disabled = MobilityEvidence.model_validate(raw_disabled)
        self.assertFalse(ev_disabled.marta_gtfs_available)
        self.assertFalse(ev_disabled.usda_food_access_available)
        self.assertFalse(ev_disabled.imls_venues_available)
        self.assertEqual(ev_disabled.tract_mobility, [])
        self.assertIn(MANDATORY_STOP_PROXIMITY_CAVEAT, ev_disabled.caveats)

        # Case B: include_optional_datasets=False in session.state["plan_request"]
        ctx_state_disabled = _DummyToolContext(
            state={
                STATE_PLAN_REQUEST: {
                    "county_fips": "13121",
                    "include_optional_datasets": False,
                }
            }
        )
        raw_state_disabled = fetch_county_mobility_evidence(tool_context=ctx_state_disabled)
        ev_state_disabled = MobilityEvidence.model_validate(raw_state_disabled)
        self.assertFalse(ev_state_disabled.marta_gtfs_available)
        self.assertFalse(ev_state_disabled.usda_food_access_available)
        self.assertFalse(ev_state_disabled.imls_venues_available)

        # Case C: BigQuery MCP client raises NotFound on missing optional view
        class _MissingViewMCPClient:
            def mcp_query_saturday_transit_and_venues(self, county_fips: str) -> Any:
                raise NotFound(
                    f"404 Not found: Table a4i-fulton-2026:marta_gtfs.v_tract_saturday_transit_access for {county_fips}"
                )

        ctx_not_found = _DummyToolContext()
        raw_not_found = fetch_county_mobility_evidence(
            county_fips="13121",
            include_optional_datasets=True,
            tool_context=ctx_not_found,
            mcp_client=_MissingViewMCPClient(),
        )
        ev_not_found = MobilityEvidence.model_validate(raw_not_found)
        self.assertFalse(ev_not_found.marta_gtfs_available)
        self.assertFalse(ev_not_found.usda_food_access_available)
        self.assertFalse(ev_not_found.imls_venues_available)
        self.assertIn(MANDATORY_STOP_PROXIMITY_CAVEAT, ev_not_found.caveats)
        self.assertTrue(
            any("NotFound" in c for c in ev_not_found.caveats),
            "Expected NotFound degradation note in caveats",
        )

    def test_03_anti_hallucination_venue_guard_forces_host_permission_false(self) -> None:
        """Every CandidateHostVenue has host_permission_verified is False regardless of source data."""
        tampered = build_mock_mobility_evidence(county_fips="13121", include_optional=True).model_dump()
        for tm in tampered["tract_mobility"]:
            for venue in tm["candidate_venues"]:
                venue["host_permission_verified"] = True

        class _UnverifiedOverrideMCPClient:
            def mcp_query_saturday_transit_and_venues(self, county_fips: str) -> Dict[str, Any]:
                return tampered

        result = fetch_county_mobility_evidence(
            county_fips="13121",
            include_optional_datasets=True,
            mcp_client=_UnverifiedOverrideMCPClient(),
        )
        evidence = MobilityEvidence.model_validate(result)
        checked_count = 0
        for tm in evidence.tract_mobility:
            for venue in tm.candidate_venues:
                self.assertIs(venue.host_permission_verified, False)
                checked_count += 1
        self.assertEqual(checked_count, 6)

    def test_04_mandatory_stop_proximity_caveat_always_present(self) -> None:
        """Caveat 'A nearby Saturday bus stop measures stop presence, not door-to-door clinic journey time.' is always present."""
        # Even if upstream MCP client returns empty caveats list
        stripped = build_mock_mobility_evidence(county_fips="13121", include_optional=True).model_dump()
        stripped["caveats"] = []

        class _NoCaveatMCPClient:
            def mcp_query_saturday_transit_and_venues(self, county_fips: str) -> Dict[str, Any]:
                return stripped

        res_enabled = fetch_county_mobility_evidence(
            county_fips="13121",
            include_optional_datasets=True,
            mcp_client=_NoCaveatMCPClient(),
        )
        self.assertIn(MANDATORY_STOP_PROXIMITY_CAVEAT, res_enabled["caveats"])

        res_disabled = fetch_county_mobility_evidence(
            county_fips="13121",
            include_optional_datasets=False,
        )
        self.assertIn(MANDATORY_STOP_PROXIMITY_CAVEAT, res_disabled["caveats"])

    def test_05_security_boundaries_and_otel_telemetry(self) -> None:
        """Rejects invalid county_fips, blocks race/PII leaks without swallowing PolicyViolationError, and records OTel spans."""
        with self.assertRaises(ValueError):
            fetch_county_mobility_evidence(county_fips="13121' OR '1'='1")

        class _LeakyDemographicMCPClient:
            def mcp_query_saturday_transit_and_venues(self, county_fips: str) -> Dict[str, Any]:
                bad = build_mock_mobility_evidence(county_fips=county_fips).model_dump()
                bad["rpl_theme3"] = 0.92
                return bad

        with self.assertRaises(PolicyViolationError):
            fetch_county_mobility_evidence(
                county_fips="13121",
                mcp_client=_LeakyDemographicMCPClient(),
            )

        tracer = get_tracer()
        tracer.clear()
        rid = set_current_request_id("req-test-plan03")

        fetch_county_mobility_evidence(county_fips="13121", include_optional_datasets=True)
        spans = [s for s in tracer.recorded_spans if s.name == "agent.transit_community.fetch_mobility"]
        self.assertEqual(len(spans), 1)
        span = spans[0]
        self.assertEqual(span.request_id, rid)
        self.assertIs(span.attributes["marta_gtfs_available"], True)
        self.assertIs(span.attributes["imls_venues_available"], True)
        self.assertIs(span.attributes["usda_food_access_available"], True)
        self.assertIn(span.attributes["candidate_venues_count"], (6, 38))

    def test_06_adk_llm_agent_and_in_memory_runner_execution(self) -> None:
        """build_transit_community_agent() executes cleanly via InMemoryRunner and populates session.state['mobility_evidence']."""
        agent = build_transit_community_agent()
        self.assertEqual(agent.name, "transit_community_agent")
        self.assertEqual(agent.output_key, STATE_MOBILITY_EVIDENCE)
        self.assertEqual(agent.output_schema, MobilityEvidence)
        self.assertIn("{plan_request?}", MOBILITY_AGENT_INSTRUCTION)

        runner = InMemoryRunner(agent=agent, app_name="carebridge-test")
        session = runner.session_service.create_session_sync(
            app_name="carebridge-test",
            user_id="outreach-lead",
            session_id="sess-plan03-e2e",
            state={
                STATE_PLAN_REQUEST: {
                    "county_fips": "13121",
                    "include_optional_datasets": True,
                }
            },
        )
        events = list(
            runner.run(
                user_id="outreach-lead",
                session_id=session.id,
                new_message="Fetch Saturday MARTA transit and community host venues for Fulton County.",
            )
        )
        self.assertGreaterEqual(len(events), 1)
        self.assertIn(STATE_MOBILITY_EVIDENCE, session.state)
        self.assertNotIn(STATE_HEALTH_EVIDENCE, session.state)

        validated = MobilityEvidence.model_validate(session.state[STATE_MOBILITY_EVIDENCE])
        self.assertTrue(validated.marta_gtfs_available)
        self.assertIn(MANDATORY_STOP_PROXIMITY_CAVEAT, validated.caveats)
        for tm in validated.tract_mobility:
            for venue in tm.candidate_venues:
                self.assertFalse(venue.host_permission_verified)
        assert_race_blind_planner_input(session.state[STATE_MOBILITY_EVIDENCE])


if __name__ == "__main__":
    unittest.main(verbosity=2)
