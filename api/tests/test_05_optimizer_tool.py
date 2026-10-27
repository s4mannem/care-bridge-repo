"""Unit and End-to-End Certification Tests for Plan 05 — Four-Stop Coverage Optimizer Tool."""

from __future__ import annotations

import json
import unittest
from typing import Dict

from carebridge.contracts.evidence_models import HealthEvidence
from carebridge.contracts.plan_models import DraftPlan
from carebridge.contracts.state_keys import (
    STATE_DRAFT_PLAN,
    STATE_HEALTH_EVIDENCE,
    STATE_MOBILITY_EVIDENCE,
    STATE_NON_DEMOGRAPHIC_FEEDBACK,
    STATE_PLAN_REQUEST,
)
from carebridge.mocks.fulton_fixtures import (
    FULTON_TRACT_HEALTH_RECORDS,
    build_mock_health_evidence,
    build_mock_mobility_evidence,
)
from carebridge.security.race_blind_guard import (
    PolicyViolationError,
    assert_no_pii_in_payload,
    assert_race_blind_planner_input,
)
from carebridge.telemetry.otel import get_tracer, set_current_request_id
from carebridge.tools.optimizer import (
    compute_tract_scores,
    haversine_km,
    optimize_four_clinic_stops,
)


class _DummyToolContext:
    def __init__(self, state: Dict[str, object]) -> None:
        self.state = state


class TestPlan05OptimizerTool(unittest.TestCase):
    """Certifies Plan 05 — Four-Stop Coverage Optimizer Tool."""

    def setUp(self) -> None:
        get_tracer().clear()
        set_current_request_id("req-test-plan05")

    def test_01_determinism_byte_identical_outputs(self) -> None:
        """Requirement 1: Running optimize_four_clinic_stops twice returns byte-identical DraftPlan outputs."""
        run1 = optimize_four_clinic_stops(
            county_fips="13121",
            strategy="balanced_uninsured_safety_net_gap",
        )
        run2 = optimize_four_clinic_stops(
            county_fips="13121",
            strategy="balanced_uninsured_safety_net_gap",
        )
        self.assertEqual(
            json.dumps(run1, sort_keys=True),
            json.dumps(run2, sort_keys=True),
        )
        plan = DraftPlan.model_validate(run1)
        self.assertEqual(plan.status, "ok")
        self.assertEqual(len(plan.stops), 4)
        self.assertEqual(len(plan.runner_up_tracts), 4)

    def test_02_distinct_catchments_and_provisional_hosts(self) -> None:
        """Requirement 2: All 4 selected stops have pairwise Haversine distances >= 5.0 km and distinct primary tracts."""
        raw = optimize_four_clinic_stops(
            county_fips="13121",
            strategy="balanced_uninsured_safety_net_gap",
        )
        plan = DraftPlan.model_validate(raw)

        primary_ids = [s.primary_tract_geoid for s in plan.stops]
        self.assertEqual(len(set(primary_ids)), 4)

        for i in range(len(plan.stops)):
            self.assertFalse(plan.stops[i].host_verified)
            self.assertIn("PROVISIONAL", plan.stops[i].provisional_warning)
            self.assertGreater(plan.stops[i].score_breakdown.checkup_preventive_gap_norm, 0.0)
            for j in range(i + 1, len(plan.stops)):
                dist_km = haversine_km(
                    plan.stops[i].latitude,
                    plan.stops[i].longitude,
                    plan.stops[j].latitude,
                    plan.stops[j].longitude,
                )
                self.assertGreaterEqual(
                    dist_km,
                    5.0,
                    f"Stops {i+1} and {j+1} are only {dist_km:.2f} km apart (< 5.0 km).",
                )

        # Verify Question 7 runner-up tracts (#5-#8)
        ranks = [r.need_rank for r in plan.runner_up_tracts]
        self.assertEqual(ranks, [5, 6, 7, 8])
        for r in plan.runner_up_tracts:
            self.assertNotIn(r.tract_geoid, primary_ids)
            self.assertTrue(len(r.technical_deferral_rationale) > 20)

    def test_03_revision_remediation_resolves_catchment_overlap(self) -> None:
        """Requirement 3: simulate_first_draft_defect=True creates overlap in Draft 0; revision_number=1 resolves it."""
        draft0_raw = optimize_four_clinic_stops(
            county_fips="13121",
            strategy="balanced_uninsured_safety_net_gap",
            revision_number=0,
            simulate_first_draft_defect=True,
        )
        draft0 = DraftPlan.model_validate(draft0_raw)
        dist_draft0 = haversine_km(
            draft0.stops[0].latitude,
            draft0.stops[0].longitude,
            draft0.stops[1].latitude,
            draft0.stops[1].longitude,
        )
        self.assertLess(
            dist_draft0,
            5.0,
            f"Expected Draft 0 Stops 1 & 2 to be < 5.0 km apart when defect simulated, got {dist_draft0:.2f} km.",
        )

        # Now run Revision 1 with non_demographic_feedback from Auditor
        ctx = _DummyToolContext(
            state={
                STATE_PLAN_REQUEST: {
                    "county_fips": "13121",
                    "strategy": "balanced_uninsured_safety_net_gap",
                    "simulate_first_draft_defect": True,
                },
                STATE_HEALTH_EVIDENCE: build_mock_health_evidence("13121").model_dump(),
                STATE_MOBILITY_EVIDENCE: build_mock_mobility_evidence("13121").model_dump(),
                STATE_NON_DEMOGRAPHIC_FEEDBACK: [
                    "CATCHMENT_OVERLAP: Stops 1 and 2 sit within < 5.0 km; enforce >= 5.0 km separation."
                ],
                "current_revision_number": 1,
            }
        )
        draft1_raw = optimize_four_clinic_stops(tool_context=ctx)
        draft1 = DraftPlan.model_validate(draft1_raw)
        self.assertEqual(draft1.revision_number, 1)
        self.assertIn(STATE_DRAFT_PLAN, ctx.state)

        for i in range(len(draft1.stops)):
            for j in range(i + 1, len(draft1.stops)):
                d_km = haversine_km(
                    draft1.stops[i].latitude,
                    draft1.stops[i].longitude,
                    draft1.stops[j].latitude,
                    draft1.stops[j].longitude,
                )
                self.assertGreaterEqual(d_km, 5.0)

    def test_04_insufficient_candidates_graceful_status(self) -> None:
        """Requirement 4: Fewer than 4 valid tracts returns status='insufficient_candidates' cleanly."""
        tiny_he = HealthEvidence(
            county_fips="13121",
            county_name="Fulton",
            tracts=list(FULTON_TRACT_HEALTH_RECORDS[:2]),
            care_sites_count=85,
            safety_net_sites_count=41,
            shortage_areas_count=0,
            shortage_facilities_count=6,
            max_hpsa_score=19.0,
            regional_disease=build_mock_health_evidence("13121").regional_disease,
        )
        raw = optimize_four_clinic_stops(
            county_fips="13121",
            health_evidence=tiny_he,
        )
        plan = DraftPlan.model_validate(raw)
        self.assertEqual(plan.status, "insufficient_candidates")
        self.assertEqual(len(plan.stops), 0)

    def test_05_sensitivity_summary_and_race_blind_guard(self) -> None:
        """Requirement 5: top_4_stability_jaccard is in [0.0, 1.0] and race-blind guard blocks demographic keys."""
        raw = optimize_four_clinic_stops(
            county_fips="13121",
            strategy="chronic_respiratory_focus",
        )
        plan = DraftPlan.model_validate(raw)
        self.assertIsNotNone(plan.sensitivity)
        assert plan.sensitivity is not None
        self.assertGreaterEqual(plan.sensitivity.top_4_stability_jaccard, 0.0)
        self.assertLessEqual(plan.sensitivity.top_4_stability_jaccard, 1.0)
        self.assertGreaterEqual(len(plan.sensitivity.borderline_tracts), 1)

        assert_race_blind_planner_input(raw)
        assert_no_pii_in_payload(raw)

        # Verify OpenTelemetry span `tool.optimizer.run`
        spans = [s for s in get_tracer().recorded_spans if s.name == "tool.optimizer.run"]
        self.assertGreaterEqual(len(spans), 1)
        self.assertEqual(spans[-1].attributes["strategy"], "chronic_respiratory_focus")
        self.assertEqual(len(spans[-1].attributes["selected_tracts"]), 4)

        # Verify passing a contaminated tract dict raises PolicyViolationError
        bad_tract = FULTON_TRACT_HEALTH_RECORDS[0].model_dump()
        bad_tract["rpl_theme3"] = 0.94
        with self.assertRaises(PolicyViolationError):
            compute_tract_scores(tracts=[bad_tract])  # type: ignore[list-item]


if __name__ == "__main__":
    unittest.main()
