"""End-to-end and unit certification tests for Plan 07 — Independent Equity & Rigor Auditor Agent."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any, Dict

from carebridge.agents.auditor_agent import (
    AUDITOR_AGENT_INSTRUCTION,
    build_equity_rigor_auditor_agent,
    execute_independent_plan_audit,
)
from carebridge.contracts.audit_models import (
    AuditReport,
    AuditVerdict,
    DefectCategory,
)
from carebridge.contracts.state_keys import (
    STATE_AUDIT_REPORT,
    STATE_DRAFT_PLAN,
    STATE_EVIDENCE_REPORT,
    STATE_NON_DEMOGRAPHIC_FEEDBACK,
    STATE_REVISION_REQUIRED,
)
from carebridge.mocks.fulton_fixtures import (
    build_mock_draft_plan,
    build_mock_evidence_report,
)
from carebridge.security.race_blind_guard import (
    PolicyViolationError,
    assert_no_pii_in_payload,
    assert_race_blind_planner_input,
)
from carebridge.telemetry.otel import get_tracer, set_current_request_id
from carebridge.tools.optimizer import optimize_four_clinic_stops


class TestPlan07EquityRigorAuditorAgent(unittest.TestCase):
    """Certifies Plan 07 — Independent Equity & Rigor Auditor Agent (Protected Access Boundary)."""

    def setUp(self) -> None:
        get_tracer().clear()
        set_current_request_id("req-test-plan07")

    def test_01_rejection_path_revision_0_catchment_overlap_and_grain_defects(self) -> None:
        """Requirement 1: On `revision_audited == 0`, overlapping stops (< 5.0 km) trigger REJECTED_REVISION_REQUIRED."""
        defective_draft_dict = optimize_four_clinic_stops(
            county_fips="13121",
            strategy="balanced_uninsured_safety_net_gap",
            revision_number=0,
            simulate_first_draft_defect=True,
        )
        state: Dict[str, Any] = {
            STATE_DRAFT_PLAN: defective_draft_dict,
            STATE_EVIDENCE_REPORT: build_mock_evidence_report("13121").model_dump(),
        }

        auditor = build_equity_rigor_auditor_agent()
        report_dict = auditor.execute_with_state(state, user_message="Audit Draft 0 siting plan.")
        report = AuditReport.model_validate(report_dict)

        self.assertEqual(report.revision_audited, 0)
        self.assertEqual(report.verdict, AuditVerdict.REJECTED_REVISION_REQUIRED)
        self.assertTrue(state[STATE_REVISION_REQUIRED])
        self.assertGreaterEqual(len(report.non_demographic_defects), 1)
        self.assertTrue(
            any(d.category == DefectCategory.CATCHMENT_OVERLAP for d in report.non_demographic_defects)
        )
        self.assertEqual(len(state[STATE_NON_DEMOGRAPHIC_FEEDBACK]), len(report.non_demographic_defects))

    def test_02_demographic_diode_check_feedback_is_race_blind_while_audit_report_has_demographics(
        self,
    ) -> None:
        """Requirement 2: `non_demographic_feedback` passes `assert_race_blind_planner_input` while `audit_report` has demographics."""
        defective_draft_dict = optimize_four_clinic_stops(
            county_fips="13121",
            strategy="balanced_uninsured_safety_net_gap",
            revision_number=0,
            simulate_first_draft_defect=True,
        )
        state: Dict[str, Any] = {
            STATE_DRAFT_PLAN: defective_draft_dict,
            STATE_EVIDENCE_REPORT: build_mock_evidence_report("13121").model_dump(),
        }

        auditor = build_equity_rigor_auditor_agent()
        auditor.execute_with_state(state, user_message="Audit Draft 0 and verify demographic diode.")

        # 1. Verify non_demographic_feedback passes race-blind & PII checks 100%
        feedback = state[STATE_NON_DEMOGRAPHIC_FEEDBACK]
        self.assertIsInstance(feedback, list)
        self.assertGreaterEqual(len(feedback), 1)
        assert_race_blind_planner_input(feedback)
        assert_no_pii_in_payload(feedback)

        # 2. Verify full AuditReport in session.state['audit_report'] has post-hoc demographic comparison
        audit_report_dict = state[STATE_AUDIT_REPORT]
        demo_impact = audit_report_dict["demographic_impact"]
        self.assertGreater(demo_impact["county_total_pop"], 0)
        self.assertGreater(demo_impact["catchment_total_pop"], 0)
        self.assertGreater(demo_impact["catchment_svi_theme3_mean"], 0.0)
        self.assertIn("black", demo_impact["group_comparisons"])
        self.assertIn("hispanic", demo_impact["group_comparisons"])
        self.assertIn("minority_overall", demo_impact["group_comparisons"])
        self.assertGreaterEqual(demo_impact["group_comparisons"]["minority_overall"]["parity_ratio"], 1.0)

        # Verify that full audit_report_dict WOULD be blocked by assert_race_blind_planner_input if leaked to Planner
        with self.assertRaises(PolicyViolationError):
            assert_race_blind_planner_input(audit_report_dict)

    def test_03_approval_path_valid_four_stop_plan(self) -> None:
        """Requirement 3: Valid 4-stop `DraftPlan` with distinct catchments and proper grain disclosures is APPROVED."""
        from google.adk.runners import InMemoryRunner

        auditor = build_equity_rigor_auditor_agent()
        runner = InMemoryRunner(agent=auditor, app_name="carebridge-test-07")
        session = runner.session_service.create_session_sync(
            app_name="carebridge-test-07",
            user_id="auditor-lead",
            session_id="sess-auditor-07",
            state={
                STATE_DRAFT_PLAN: build_mock_draft_plan("13121").model_dump(),
                STATE_EVIDENCE_REPORT: build_mock_evidence_report("13121").model_dump(),
            },
        )

        events = list(
            runner.run(
                user_id="auditor-lead",
                session_id=session.id,
                new_message="Execute independent equity and rigor audit on the Fulton County siting plan.",
            )
        )
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0].is_final_response())

        report = AuditReport.model_validate(session.state[STATE_AUDIT_REPORT])
        self.assertEqual(report.verdict, AuditVerdict.APPROVED)
        self.assertFalse(session.state[STATE_REVISION_REQUIRED])
        self.assertEqual(report.non_demographic_defects, [])
        self.assertEqual(session.state[STATE_NON_DEMOGRAPHIC_FEEDBACK], [])
        self.assertGreaterEqual(len(report.limitations_attached), 3)

        # Verify OpenTelemetry span `agent.auditor.evaluate`
        auditor_spans = [
            s for s in get_tracer().recorded_spans if s.name == "agent.auditor.evaluate"
        ]
        self.assertEqual(len(auditor_spans), 1)
        self.assertEqual(auditor_spans[0].attributes["verdict"], "approved")
        self.assertEqual(auditor_spans[0].attributes["defects_count"], 0)
        self.assertGreater(auditor_spans[0].attributes["catchment_svi_theme3_mean"], 0.70)

    def test_04_bounded_loop_cap_revision_1_escalates_to_needs_human_review(self) -> None:
        """Requirement 4: If a defect still exists on `revision_number == 1`, verdict is NEEDS_HUMAN_REVIEW and revision_required is False."""
        draft_rev1 = build_mock_draft_plan("13121")
        draft_rev1.revision_number = 1
        # Inject an unsupported tract-level NSSP claim and unverified host flag on Stop #1
        draft_rev1.stops[0].plain_language_rationale = (
            "Neighborhood COVID and RSV ED visits are spiking in this specific tract, and the venue is officially booked."
        )
        draft_rev1.stops[0].spatial_grain_disclosures = [
            "Tract prevalence values are CDC PLACES modeled estimates."
        ]
        draft_rev1.stops[0].host_verified = True

        state: Dict[str, Any] = {
            STATE_DRAFT_PLAN: draft_rev1.model_dump(),
            STATE_EVIDENCE_REPORT: build_mock_evidence_report("13121").model_dump(),
        }

        ctx = SimpleNamespace(agent_name="equity_rigor_auditor", state=state)
        report_dict = execute_independent_plan_audit(tool_context=ctx)
        report = AuditReport.model_validate(report_dict)

        self.assertEqual(report.revision_audited, 1)
        self.assertEqual(report.verdict, AuditVerdict.NEEDS_HUMAN_REVIEW)
        self.assertFalse(state[STATE_REVISION_REQUIRED])
        categories = {d.category for d in report.non_demographic_defects}
        self.assertIn(DefectCategory.UNSUPPORTED_GRAIN_CLAIM, categories)
        self.assertIn(DefectCategory.INFEASIBLE_HOST_OR_TRANSIT, categories)

    def test_05_permission_boundary_blocks_non_auditor_callers(self) -> None:
        """Requirement 5: Calling `execute_independent_plan_audit` with `agent_name='siting_planner_agent'` raises `PolicyViolationError`."""
        for unauthorized_agent in (
            "siting_planner_agent",
            "health_access_agent",
            "transit_community_agent",
            "community_comms_agent",
        ):
            unauthorized_ctx = SimpleNamespace(agent_name=unauthorized_agent, state={})
            with self.assertRaises(PolicyViolationError):
                execute_independent_plan_audit(tool_context=unauthorized_ctx)

        # Verify adversarial posture in prompt
        self.assertIn("SKEPTICAL, ADVERSARIAL, and RIGOROUS", AUDITOR_AGENT_INSTRUCTION)


if __name__ == "__main__":
    unittest.main()
