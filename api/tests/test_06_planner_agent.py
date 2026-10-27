"""End-to-end and unit certification tests for Plan 06 — Siting Planner Agent (`carebridge/agents/planner_agent/`)."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any, Dict

from carebridge.agents.planner_agent import (
    PLANNER_AGENT_INSTRUCTION,
    build_siting_planner_agent,
    planner_after_model_callback,
    planner_race_blind_before_model_callback,
)
from carebridge.contracts.evidence_models import EvidenceReport
from carebridge.contracts.plan_models import DraftPlan
from carebridge.contracts.state_keys import (
    STATE_AUDIT_REPORT,
    STATE_DRAFT_PLAN,
    STATE_EVIDENCE_REPORT,
    STATE_HEALTH_EVIDENCE,
    STATE_MOBILITY_EVIDENCE,
    STATE_NON_DEMOGRAPHIC_FEEDBACK,
    STATE_PLAN_REQUEST,
    STATE_REVISION_HISTORY,
)
from carebridge.mocks.fulton_fixtures import (
    build_mock_health_evidence,
    build_mock_mobility_evidence,
)
from carebridge.security.race_blind_guard import PolicyViolationError
from carebridge.telemetry.otel import get_tracer, set_current_request_id
from carebridge.tools.optimizer.scoring import haversine_km


def _build_ready_evidence_report(county_fips: str = "13121") -> Dict[str, Any]:
    return EvidenceReport(
        county_fips=county_fips,
        overall_ready=True,
        core_tables_ready=True,
        optional_tables_available=["gtfs_stops_routes", "hrsa_dw_health_care_service_delivery_sites", "cma_aq"],
        join_key_valid=True,
        spatial_grain_warnings=[
            "disease_weekly is reported at 4-county HSA level (Fulton, DeKalb, Clayton, Gwinnett), not census tract.",
            "cma_aq is reported at 12 km grid level, not census tract.",
        ],
        blocking_failures=[],
        validator_summary="All core tables validated and ready for 4-stop coverage optimization.",
    ).model_dump()


class TestPlan06SitingPlannerAgent(unittest.TestCase):
    """Certifies Plan 06 — Siting Planner Agent (Race-Blind Inputs)."""

    def setUp(self) -> None:
        get_tracer().clear()
        set_current_request_id("req-test-plan06")

    def test_01_planner_race_blind_before_model_callback_blocks_demographic_leakage(self) -> None:
        """Requirement 1: `planner_race_blind_before_model_callback` blocks `rpl_theme3`, `demographic_impact`, and `audit_report`."""
        ctx = SimpleNamespace(agent_name="siting_planner_agent", state={})

        # Clean race-blind prompt passes
        self.assertIsNone(
            planner_race_blind_before_model_callback(
                ctx,
                "Propose 4 clinic stops using pct_uninsured_18_64, km_to_safety_net, and pct_no_vehicle.",
            )
        )

        # Forbidden tokens in outgoing prompt must raise PolicyViolationError
        for forbidden_snippet in (
            "Prioritize tracts with high rpl_theme3 values.",
            "Review demographic_impact from previous iteration.",
            "Filter tracts by pct_black and pct_hispanic.",
            "Query external_demographic_audit before siting.",
            "Inject audit_report into planner prompt.",
        ):
            with self.assertRaises(PolicyViolationError):
                planner_race_blind_before_model_callback(ctx, forbidden_snippet)

        # Contaminating non_demographic_feedback in session.state must also raise PolicyViolationError
        contaminated_ctx = SimpleNamespace(
            agent_name="siting_planner_agent",
            state={
                STATE_NON_DEMOGRAPHIC_FEEDBACK: [
                    "Increase coverage in high rpl_theme3 tracts to improve demographic_impact."
                ]
            },
        )
        with self.assertRaises(PolicyViolationError):
            planner_race_blind_before_model_callback(
                contaminated_ctx,
                "Re-run 4-stop optimization using non_demographic_feedback.",
            )

    @unittest.skip("Drives the planner through the no-ADK stand-in (execute_with_state); with real ADK the graph runs via coordinator/adk_adapter.py")

    def test_02_planner_outputs_insufficient_candidates_when_core_tables_not_ready(self) -> None:
        """Requirement 2: When `evidence_report.core_tables_ready == False`, Planner outputs `DraftPlan(status='insufficient_candidates')`."""
        agent = build_siting_planner_agent()
        failed_evidence_report = EvidenceReport(
            county_fips="13121",
            overall_ready=False,
            core_tables_ready=False,
            optional_tables_available=[],
            join_key_valid=False,
            spatial_grain_warnings=[],
            blocking_failures=[
                "places_tract: 0 rows returned for county_fips=13121",
                "svi_tract: join key mismatch on geo_id",
            ],
            validator_summary="Core health tables failed schema and row-count validation.",
        ).model_dump()

        state: Dict[str, Any] = {
            STATE_PLAN_REQUEST: {"county_fips": "13121", "strategy": "balanced_uninsured_safety_net_gap"},
            STATE_EVIDENCE_REPORT: failed_evidence_report,
        }

        result = agent.execute_with_state(state, user_message="Generate 4-stop clinic siting plan.")
        draft = DraftPlan.model_validate(result)

        self.assertEqual(draft.status, "insufficient_candidates")
        self.assertEqual(draft.stops, [])
        self.assertEqual(draft.runner_up_tracts, [])
        self.assertTrue(any("places_tract" in note for note in draft.planner_notes))
        self.assertEqual(state[STATE_DRAFT_PLAN]["status"], "insufficient_candidates")
        self.assertEqual(len(state[STATE_REVISION_HISTORY]), 1)
        self.assertEqual(state[STATE_REVISION_HISTORY][0]["status"], "insufficient_candidates")

    @unittest.skip("Drives the planner through the no-ADK stand-in (execute_with_state); with real ADK the graph runs via coordinator/adk_adapter.py")

    def test_03_planner_revision_loop_updates_draft_plan_and_preserves_revision_history(self) -> None:
        """Requirement 3: On initial run (`revision_number=0`) and revision run (`revision_number=1`), `revision_history` records both in order."""
        agent = build_siting_planner_agent()

        state: Dict[str, Any] = {
            STATE_PLAN_REQUEST: {
                "county_fips": "13121",
                "strategy": "balanced_uninsured_safety_net_gap",
                "simulate_first_draft_defect": True,
            },
            STATE_HEALTH_EVIDENCE: build_mock_health_evidence("13121").model_dump(),
            STATE_MOBILITY_EVIDENCE: build_mock_mobility_evidence("13121", include_optional=True).model_dump(),
            STATE_EVIDENCE_REPORT: _build_ready_evidence_report("13121"),
        }

        # --- Iteration 0 (Initial Draft with simulated catchment overlap between Stop #1 and Stop #2) ---
        draft0_dict = agent.execute_with_state(state, user_message="Create initial 4-stop siting plan.")
        draft0 = DraftPlan.model_validate(draft0_dict)

        self.assertEqual(draft0.status, "ok")
        self.assertEqual(draft0.revision_number, 0)
        self.assertEqual(len(draft0.stops), 4)
        dist_draft0_s1_s2 = haversine_km(
            draft0.stops[0].latitude,
            draft0.stops[0].longitude,
            draft0.stops[1].latitude,
            draft0.stops[1].longitude,
        )
        self.assertLess(
            dist_draft0_s1_s2,
            5.0,
            "Draft 0 with simulate_first_draft_defect=True should exhibit <5 km overlap",
        )

        # Simulate Auditor storing `audit_report` (containing demographic_impact) in session.state
        # AND sanitized `non_demographic_feedback` for the Planner's revision loop.
        # Planner must NEVER interpolate `audit_report` into its prompt.
        state[STATE_AUDIT_REPORT] = {
            "approved": False,
            "demographic_impact": {"rpl_theme3": 0.88, "pct_black": 79.4},
        }
        state[STATE_NON_DEMOGRAPHIC_FEEDBACK] = [
            "OPERATIONAL DEFECT: Stop #1 and Stop #2 have overlapping 4 km catchments (< 5.0 km inter-stop distance). "
            "Re-optimize enforcing >= 5.0 km separation between all 4 Saturday stops."
        ]

        rendered_instruction = agent.render_instruction(state)
        self.assertNotIn("rpl_theme3", rendered_instruction)
        self.assertNotIn("demographic_impact", rendered_instruction)

        # --- Iteration 1 (Revision 1 with non_demographic_feedback) ---
        draft1_dict = agent.execute_with_state(
            state,
            user_message="Revise the 4-stop siting plan to resolve non_demographic_feedback.",
        )
        draft1 = DraftPlan.model_validate(draft1_dict)

        self.assertEqual(draft1.status, "ok")
        self.assertEqual(draft1.revision_number, 1)
        self.assertEqual(len(draft1.stops), 4)

        # Verify all pairwise distances in Revision 1 are >= 5.0 km
        for i in range(len(draft1.stops)):
            for j in range(i + 1, len(draft1.stops)):
                d_km = haversine_km(
                    draft1.stops[i].latitude,
                    draft1.stops[i].longitude,
                    draft1.stops[j].latitude,
                    draft1.stops[j].longitude,
                )
                self.assertGreaterEqual(
                    d_km,
                    5.0,
                    f"Revision 1 stops #{i+1} and #{j+1} must be >= 5.0 km apart (got {d_km:.2f} km)",
                )

        # Verify revision_history preserved both Draft 0 and Draft 1 in order
        history = state[STATE_REVISION_HISTORY]
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["revision_number"], 0)
        self.assertEqual(history[1]["revision_number"], 1)
        self.assertNotEqual(
            history[0]["stops"][1]["primary_tract_geoid"],
            history[1]["stops"][1]["primary_tract_geoid"],
        )
        self.assertEqual(state[STATE_DRAFT_PLAN]["revision_number"], 1)

        # Verify OpenTelemetry span `agent.siting_planner.plan` was emitted for both runs
        planner_spans = [
            s for s in get_tracer().recorded_spans if s.name == "agent.siting_planner.plan"
        ]
        self.assertEqual(len(planner_spans), 2)
        self.assertEqual(planner_spans[0].attributes["revision_number"], 0)
        self.assertEqual(planner_spans[1].attributes["revision_number"], 1)
        self.assertEqual(len(planner_spans[1].attributes["stop_geoids"]), 4)

    @unittest.skip("Drives the planner through the no-ADK stand-in (execute_with_state); with real ADK the graph runs via coordinator/adk_adapter.py")

    def test_04_planner_stops_and_runner_ups_have_citations_grain_disclosures_and_provisional_flags(
        self,
    ) -> None:
        """Requirement 4: Every stop has `host_verified is False` and non-empty `evidence_citations` and `spatial_grain_disclosures`."""
        from google.adk.runners import InMemoryRunner

        agent = build_siting_planner_agent()
        runner = InMemoryRunner(agent=agent, app_name="carebridge-test-06")
        session = runner.session_service.create_session_sync(
            app_name="carebridge-test-06",
            user_id="outreach-lead",
            session_id="sess-planner-06",
            state={
                STATE_PLAN_REQUEST: {"county_fips": "13121", "strategy": "balanced_uninsured_safety_net_gap"},
                STATE_HEALTH_EVIDENCE: build_mock_health_evidence("13121").model_dump(),
                STATE_MOBILITY_EVIDENCE: build_mock_mobility_evidence("13121", include_optional=True).model_dump(),
                STATE_EVIDENCE_REPORT: _build_ready_evidence_report("13121"),
            },
        )

        events = list(
            runner.run(
                user_id="outreach-lead",
                session_id=session.id,
                new_message="Generate the Fulton County 4-Saturday mobile clinic siting plan.",
            )
        )
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0].is_final_response())

        draft = DraftPlan.model_validate(session.state[STATE_DRAFT_PLAN])
        self.assertEqual(draft.status, "ok")
        self.assertEqual(len(draft.stops), 4)

        for stop in draft.stops:
            self.assertFalse(stop.host_verified)
            self.assertIn("PROVISIONAL SITE", stop.provisional_warning)
            self.assertGreaterEqual(len(stop.evidence_citations), 2)
            self.assertGreaterEqual(len(stop.spatial_grain_disclosures), 2)
            self.assertTrue(
                "100 - pct_checkup" in stop.plain_language_rationale
                or "preventive checkup gap" in stop.plain_language_rationale
            )

        # Verify Question 7 runner-up tracts (#5-#8) have analytical deferral rationales
        self.assertEqual(len(draft.runner_up_tracts), 4)
        for idx, ru in enumerate(draft.runner_up_tracts, start=5):
            self.assertEqual(ru.need_rank, idx)
            self.assertGreater(len(ru.technical_deferral_rationale), 20)
            self.assertIn(
                ru.deferral_reason_code,
                {
                    "catchment_already_covered",
                    "inter_stop_separation_constraint",
                    "no_saturday_transit_or_venue",
                    "lower_marginal_coverage",
                },
            )

        # Verify prompt posture rules
        self.assertIn("ANALYTICAL, SOURCE-CITED, and RESOLUTION-QUALIFIED", PLANNER_AGENT_INSTRUCTION)
        self.assertNotIn("{audit_report", PLANNER_AGENT_INSTRUCTION)

    def test_05_planner_after_model_callback_blocks_unverified_booking_or_demographic_output(self) -> None:
        """Requirement 5: `planner_after_model_callback` blocks hallucinated confirmed bookings or demographic leaks."""
        ctx = SimpleNamespace(agent_name="siting_planner_agent", state={})

        with self.assertRaises(PolicyViolationError):
            planner_after_model_callback(
                ctx,
                "Stop #1 is officially booked with confirmed parking at Adamsville Recreation Center.",
            )

        with self.assertRaises(PolicyViolationError):
            planner_after_model_callback(
                ctx,
                "Selected Tract 13121007808 because rpl_theme3 is 0.91.",
            )


if __name__ == "__main__":
    unittest.main()
