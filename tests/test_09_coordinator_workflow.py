"""End-to-end unit and integration tests for Plan 09 — Coordinator Agent & ADK Workflow."""

from __future__ import annotations

import asyncio
import unittest
from typing import Any, Dict

from carebridge.agents.coordinator import (
    AuditLoopExitGate,
    BaseAgent,
    LoopAgent,
    ParallelAgent,
    SequentialAgent,
    build_carebridge_coordinator_workflow,
    execute_carebridge_plan,
)
from carebridge.contracts.api_models import PlanRequest
from carebridge.contracts.audit_models import AuditVerdict
from carebridge.contracts.state_keys import (
    PLANNER_VISIBLE_STATE_KEYS,
    SANITIZED_LOOPBACK_STATE_KEYS,
    STATE_AUDIT_REPORT,
    STATE_DRAFT_PLAN,
    STATE_EVIDENCE_REPORT,
    STATE_FINAL_PLAN,
    STATE_HEALTH_EVIDENCE,
    STATE_MOBILITY_EVIDENCE,
    STATE_NON_DEMOGRAPHIC_FEEDBACK,
    STATE_OUTREACH_MESSAGES,
    STATE_PLAN_REQUEST,
    STATE_REVISION_HISTORY,
)
from carebridge.security.race_blind_guard import (
    PolicyViolationError,
    assert_no_pii_in_payload,
    assert_race_blind_planner_input,
)
from carebridge.tools.optimizer.scoring import haversine_km


class Test09CoordinatorWorkflow(unittest.TestCase):
    """Certifies Plan 09: 4-stage ADK Coordinator workflow, bounded revision loop, and `agent/agent.py`."""

    def test_01_standard_path_single_iteration_approval(self) -> None:
        """Standard Path (`simulate_first_draft_defect=False`): approves on Iteration 0 with 4 stops & outreach."""
        session_state: Dict[str, Any] = {}
        request = PlanRequest(
            county_fips="13121",
            county_name="Fulton",
            strategy="balanced_uninsured_safety_net_gap",
            simulate_first_draft_defect=False,
        )
        response = asyncio.run(
            execute_carebridge_plan(request, session_state_out=session_state)
        )

        self.assertEqual(response.status, "provisional_approved")
        self.assertFalse(response.needs_human_review)
        self.assertEqual(response.county_fips, "13121")
        self.assertEqual(len(response.revision_history), 1)
        self.assertEqual(response.revision_history[0].revision_number, 0)

        self.assertIsNotNone(response.final_plan)
        assert response.final_plan is not None
        self.assertEqual(response.final_plan.status, "ok")
        self.assertEqual(len(response.final_plan.stops), 4)
        self.assertGreaterEqual(len(response.final_plan.runner_up_tracts), 1)
        for stop in response.final_plan.stops:
            self.assertFalse(stop.host_verified)

        self.assertIsNotNone(response.audit_report)
        assert response.audit_report is not None
        self.assertEqual(response.audit_report.verdict, AuditVerdict.APPROVED)
        self.assertEqual(response.audit_report.revision_audited, 0)
        self.assertEqual(len(response.audit_report.non_demographic_defects), 0)

        self.assertIsNotNone(response.outreach)
        assert response.outreach is not None
        self.assertEqual(len(response.outreach.stop_notices), 4)
        self.assertEqual(
            len(response.outreach.unpicked_neighborhood_explanations),
            len(response.final_plan.runner_up_tracts),
        )

        self.assertTrue(response.data_availability.get("burden_tracts"))
        self.assertTrue(response.data_availability.get("marta_gtfs"))
        self.assertGreaterEqual(len(response.provenance), 6)
        self.assertGreaterEqual(len(response.limitations), 4)
        self.assertEqual(
            response.telemetry_summary.get("audit_verdicts"),
            {"approved": 1},
        )

    def test_02_adversarial_revision_path_resolves_catchment_overlap(self) -> None:
        """Adversarial Path (`simulate_first_draft_defect=True`): Draft 0 rejected -> Draft 1 remedies overlap."""
        session_state: Dict[str, Any] = {}
        request = PlanRequest(
            county_fips="13121",
            county_name="Fulton",
            strategy="balanced_uninsured_safety_net_gap",
            simulate_first_draft_defect=True,
        )
        response = asyncio.run(
            execute_carebridge_plan(request, session_state_out=session_state)
        )

        # Must have executed 2 loop iterations (Draft 0 + Draft 1)
        self.assertEqual(len(response.revision_history), 2)
        draft_0 = response.revision_history[0]
        draft_1 = response.revision_history[1]
        self.assertEqual(draft_0.revision_number, 0)
        self.assertEqual(draft_1.revision_number, 1)

        # Verify Draft 0 had overlapping catchments (< 5.0 km between Stop #1 and Stop #2)
        d0_s1, d0_s2 = draft_0.stops[0], draft_0.stops[1]
        dist_draft_0 = haversine_km(
            d0_s1.latitude, d0_s1.longitude, d0_s2.latitude, d0_s2.longitude
        )
        self.assertLess(dist_draft_0, 5.0)

        # Verify non_demographic_feedback captured CATCHMENT_OVERLAP
        feedback = session_state.get(STATE_NON_DEMOGRAPHIC_FEEDBACK, [])
        self.assertTrue(feedback)
        self.assertIn("CATCHMENT_OVERLAP", " ".join(str(x) for x in feedback).upper())

        # Verify Draft 1 resolved the overlap across all pairs of stops (>= 5.0 km)
        for i in range(len(draft_1.stops)):
            for j in range(i + 1, len(draft_1.stops)):
                si, sj = draft_1.stops[i], draft_1.stops[j]
                dist_ij = haversine_km(si.latitude, si.longitude, sj.latitude, sj.longitude)
                self.assertGreaterEqual(dist_ij, 5.0)

        # Verify Auditor approved Draft 1 and promoted it to final_plan
        self.assertEqual(response.status, "provisional_approved")
        self.assertFalse(response.needs_human_review)
        assert response.audit_report is not None
        self.assertEqual(response.audit_report.verdict, AuditVerdict.APPROVED)
        self.assertEqual(response.audit_report.revision_audited, 1)
        self.assertEqual(
            response.telemetry_summary.get("audit_verdicts"),
            {"rejected_revision_required": 1, "approved": 1},
        )

    def test_03_scoped_state_race_blind_isolation_and_posthoc_demographic_parity(self) -> None:
        """Scoped State Verification: Planner-visible keys are 100% race-blind while Auditor holds demographic parity."""
        session_state: Dict[str, Any] = {}
        request = PlanRequest(
            county_fips="13121",
            county_name="Fulton",
            simulate_first_draft_defect=True,
        )
        response = asyncio.run(
            execute_carebridge_plan(request, session_state_out=session_state)
        )

        planner_checked_keys = (
            *PLANNER_VISIBLE_STATE_KEYS,
            *SANITIZED_LOOPBACK_STATE_KEYS,
            STATE_DRAFT_PLAN,
            STATE_FINAL_PLAN,
        )
        for key in planner_checked_keys:
            self.assertIn(key, session_state, f"Expected state key '{key}' to be populated")
            assert_race_blind_planner_input(session_state[key])
            assert_no_pii_in_payload(session_state[key])

        # Meanwhile, audit_report.demographic_impact holds post-hoc Fulton County parity comparison
        assert response.audit_report is not None
        demo_impact = response.audit_report.demographic_impact
        self.assertIsNotNone(demo_impact)
        assert demo_impact is not None
        self.assertGreater(demo_impact.county_total_pop, 0)
        self.assertGreater(demo_impact.catchment_total_pop, 0)
        self.assertIn("black", demo_impact.group_comparisons)
        self.assertIn("hispanic", demo_impact.group_comparisons)
        self.assertIn("minority_overall", demo_impact.group_comparisons)
        self.assertGreater(demo_impact.catchment_svi_theme3_mean, 0.0)

        # Confirm that passing audit_report into assert_race_blind_planner_input would be blocked
        with self.assertRaises(PolicyViolationError):
            assert_race_blind_planner_input(response.audit_report.model_dump())

    def test_04_agent_entrypoint_export_and_adk_in_memory_runner(self) -> None:
        """`from agent.agent import root_agent` exposes the 4-stage workflow and executes via `InMemoryRunner`."""
        from agent.agent import root_agent
        from google.adk.runners import InMemoryRunner  # type: ignore

        self.assertIsInstance(root_agent, SequentialAgent)
        self.assertEqual(root_agent.name, "carebridge_coordinator")
        stage_names = [ag.name for ag in root_agent.sub_agents]
        self.assertEqual(
            stage_names,
            [
                "evidence_collection_parallel",
                "evidence_validator_agent",
                "plan_audit_loop",
                "community_communications_agent",
            ],
        )

        parallel_stage = root_agent.sub_agents[0]
        self.assertIsInstance(parallel_stage, ParallelAgent)
        self.assertEqual(
            [ag.name for ag in parallel_stage.sub_agents],
            ["health_access_agent", "transit_community_agent"],
        )

        loop_stage = root_agent.sub_agents[2]
        self.assertIsInstance(loop_stage, LoopAgent)
        self.assertEqual(loop_stage.max_iterations, 2)
        self.assertEqual(
            [ag.name for ag in loop_stage.sub_agents],
            ["siting_planner_agent", "equity_rigor_auditor", "audit_loop_exit_gate"],
        )

        # Execute root_agent via ADK InMemoryRunner
        runner = InMemoryRunner(agent=root_agent, app_name="carebridge")
        session = runner.session_service.create_session_sync(
            app_name="carebridge",
            user_id="adk-web-tester",
            session_id="sess-adk-web-09",
            state={
                STATE_PLAN_REQUEST: PlanRequest(county_fips="13121").model_dump(),
                STATE_REVISION_HISTORY: [],
            },
        )
        events = list(
            runner.run(
                user_id="adk-web-tester",
                session_id=session.id,
                new_message="Site 4 Saturday mobile health clinics in Fulton County.",
            )
        )
        self.assertGreaterEqual(len(events), 1)
        self.assertIn(STATE_HEALTH_EVIDENCE, session.state)
        self.assertIn(STATE_MOBILITY_EVIDENCE, session.state)
        self.assertIn(STATE_EVIDENCE_REPORT, session.state)
        self.assertIn(STATE_FINAL_PLAN, session.state)
        self.assertIn(STATE_AUDIT_REPORT, session.state)
        self.assertIn(STATE_OUTREACH_MESSAGES, session.state)

    def test_05_parallel_collision_guard_and_exit_gate_edge_cases(self) -> None:
        """Verifies `ParallelAgent` shared-key collision guard and `AuditLoopExitGate` human-review escalation."""

        class _CollidingWriter(BaseAgent):
            def execute_with_state(self, state: Dict[str, Any], user_message: str = "") -> Any:
                state["shared_collision_key"] = self.name
                return {"written": self.name}

        colliding_parallel = ParallelAgent(
            name="colliding_parallel",
            sub_agents=[
                _CollidingWriter(name="writer_a"),
                _CollidingWriter(name="writer_b"),
            ],
        )
        with self.assertRaises(PolicyViolationError):
            colliding_parallel.execute_with_state({})

        gate = AuditLoopExitGate()
        blocked_state: Dict[str, Any] = {
            STATE_EVIDENCE_REPORT: {
                "county_fips": "13121",
                "core_tables_ready": False,
                "blocking_failures": ["Missing burden_tracts"],
                "checks": [],
                "validated_tract_count": 0,
                "prohibited_claims_blocked": [],
                "optional_datasets_status": {},
                "caveats": [],
            },
            STATE_DRAFT_PLAN: {
                "county_fips": "13121",
                "strategy_used": "balanced_uninsured_safety_net_gap",
                "status": "insufficient_candidates",
                "revision_number": 0,
                "stops": [],
                "runner_up_tracts": [],
                "sensitivity": None,
                "planner_notes": ["Blocked due to missing core tables."],
            },
        }
        ev = gate.evaluate_state(blocked_state)
        self.assertTrue(ev.actions.escalate)
        self.assertTrue(blocked_state["needs_human_review"])


if __name__ == "__main__":
    unittest.main()
