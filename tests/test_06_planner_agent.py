"""Unit tests for Plan 06 — Siting Planner Agent (Race-Blind Inputs)."""

from __future__ import annotations

import unittest
from carebridge.agents.planner_agent import (
    PLANNER_AGENT_INSTRUCTION,
    build_siting_planner_agent,
    planner_after_model_callback,
    planner_race_blind_before_model_callback,
)
from carebridge.contracts.api_models import PlanRequest
from carebridge.contracts.evidence_models import EvidenceReport
from carebridge.contracts.plan_models import DraftPlan
from carebridge.contracts.state_keys import (
    STATE_AUDIT_REPORT,
    STATE_DRAFT_PLAN,
    STATE_REVISION_HISTORY,
)
from carebridge.mocks.fulton_fixtures import (
    build_mock_draft_plan,
    build_mock_evidence_report,
    build_mock_health_evidence,
    build_mock_mobility_evidence,
)
from carebridge.security.race_blind_guard import PolicyViolationError
from carebridge.tools.optimizer.tool import optimize_four_clinic_stops


class _MockSession:
    def __init__(self, state: dict | None = None) -> None:
        self.state = state if state is not None else {}


class _MockCallbackContext:
    def __init__(self, agent_name: str = "siting_planner_agent", session: _MockSession | None = None) -> None:
        self.agent_name = agent_name
        self.session = session if session is not None else _MockSession()


class TestPlan06PlannerAgent(unittest.TestCase):
    """Verifies Planner Agent construction, race-blind boundaries, callbacks, and rationales."""

    def setUp(self) -> None:
        self.health_evidence = build_mock_health_evidence()
        self.mobility_evidence = build_mock_mobility_evidence()
        self.plan_request = PlanRequest()
        self.evidence_report = build_mock_evidence_report()

    def test_01_build_agent_instantiation(self) -> None:
        """build_siting_planner_agent instantiates an LlmAgent with expected attributes."""
        agent = build_siting_planner_agent()
        self.assertEqual(agent.name, "siting_planner_agent")
        self.assertIn("draft_plan", agent.output_key)
        self.assertIsNotNone(agent.instruction)
        self.assertEqual(agent.instruction, PLANNER_AGENT_INSTRUCTION)
        self.assertEqual(len(agent.tools), 1)

    def test_02_race_blind_callback_blocks_demographic_keys(self) -> None:
        """planner_race_blind_before_model_callback blocks demographic tokens."""
        ctx = _MockCallbackContext()

        # Clean prompt is accepted
        clean_prompt = "Plan 4 clinic stops for county 13121 using health and mobility evidence"
        res = planner_race_blind_before_model_callback(ctx, clean_prompt)
        self.assertIsNone(res)

        # Forbidden demographic keys raise PolicyViolationError
        for bad_token in ["rpl_theme3", "pct_black", "pct_minority", "demographic_impact"]:
            with self.assertRaises(PolicyViolationError):
                planner_race_blind_before_model_callback(ctx, f"Optimize based on {bad_token}")

    def test_03_race_blind_callback_blocks_audit_report_in_session(self) -> None:
        """Planner before_model_callback raises PolicyViolationError if audit_report is in state."""
        ctx = _MockCallbackContext(session=_MockSession({STATE_AUDIT_REPORT: {"verdict": "rejected"}}))
        with self.assertRaises(PolicyViolationError):
            planner_race_blind_before_model_callback(ctx, "Clean prompt text")

    def test_04_after_model_callback_enforces_safety_and_tracks_history(self) -> None:
        """planner_after_model_callback forces host_verified=False and records revision history."""
        draft0 = build_mock_draft_plan()
        draft0.revision_number = 0
        # Intentionally tamper host_verified to True to verify enforcement
        draft0.stops[0].host_verified = True

        session = _MockSession({STATE_DRAFT_PLAN: draft0})
        ctx = _MockCallbackContext(session=session)

        planner_after_model_callback(ctx, "LLM finished")

        # host_verified must be coerced to False
        self.assertFalse(draft0.stops[0].host_verified)

        # Revision history must contain draft 0
        history = session.state[STATE_REVISION_HISTORY]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].revision_number, 0)

        # Simulate revision 1 run
        draft1 = build_mock_draft_plan()
        draft1.revision_number = 1
        session.state[STATE_DRAFT_PLAN] = draft1

        planner_after_model_callback(ctx, "LLM revised")
        self.assertEqual(len(session.state[STATE_REVISION_HISTORY]), 2)
        self.assertEqual(session.state[STATE_REVISION_HISTORY][1].revision_number, 1)

    def test_05_core_tables_not_ready_yields_insufficient_candidates(self) -> None:
        """When evidence_report.core_tables_ready is False, status is insufficient_candidates."""
        failing_report = EvidenceReport(
            county_fips="13121",
            core_tables_ready=False,
            blocking_failures=["places_tract_health table missing"],
        )
        plan_dict = optimize_four_clinic_stops(
            health_evidence=self.health_evidence,
            evidence_report=failing_report,
        )
        plan = DraftPlan.model_validate(plan_dict)
        self.assertEqual(plan.status, "insufficient_candidates")
        self.assertEqual(len(plan.stops), 0)
        self.assertTrue(any("core_tables_ready=False" in note for note in plan.planner_notes))

    def test_06_stops_have_citations_grain_disclosures_and_unverified_host(self) -> None:
        """All stops generated by the optimizer tool have valid disclosures and warnings."""
        plan_dict = optimize_four_clinic_stops(
            health_evidence=self.health_evidence,
            mobility_evidence=self.mobility_evidence,
            plan_request=self.plan_request,
            evidence_report=self.evidence_report,
        )
        plan = DraftPlan.model_validate(plan_dict)
        self.assertEqual(plan.status, "ok")
        self.assertEqual(len(plan.stops), 4)

        for stop in plan.stops:
            self.assertFalse(stop.host_verified)
            self.assertIn("PROVISIONAL SITE", stop.provisional_warning)
            self.assertGreaterEqual(len(stop.evidence_citations), 1)
            self.assertGreaterEqual(len(stop.spatial_grain_disclosures), 1)
            self.assertGreater(len(stop.plain_language_rationale), 30)


if __name__ == "__main__":
    unittest.main(verbosity=2)
