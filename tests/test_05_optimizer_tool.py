"""Unit tests for Plan 05 — Four-Stop Coverage Optimizer Tool."""

from __future__ import annotations

import unittest
from carebridge.contracts.api_models import PlanRequest
from carebridge.contracts.evidence_models import EvidenceReport
from carebridge.contracts.plan_models import DraftPlan
from carebridge.mocks.fulton_fixtures import (
    build_mock_evidence_report,
    build_mock_health_evidence,
    build_mock_mobility_evidence,
)
from carebridge.security.race_blind_guard import PolicyViolationError
from carebridge.tools.optimizer.coverage import select_four_distinct_stops
from carebridge.tools.optimizer.scoring import compute_tract_scores, haversine_km
from carebridge.tools.optimizer.sensitivity import run_weight_sensitivity
from carebridge.tools.optimizer.tool import optimize_four_clinic_stops


class TestPlan05OptimizerTool(unittest.TestCase):
    """Verifies deterministic scoring, 4-stop selection, sensitivity, and race-blindness."""

    def setUp(self) -> None:
        self.health_evidence = build_mock_health_evidence()
        self.mobility_evidence = build_mock_mobility_evidence()
        self.plan_request = PlanRequest()
        self.evidence_report = build_mock_evidence_report()

    def test_01_determinism_returns_identical_outputs(self) -> None:
        """Calling optimize_four_clinic_stops twice returns byte-identical results."""
        out1 = optimize_four_clinic_stops(
            health_evidence=self.health_evidence,
            mobility_evidence=self.mobility_evidence,
            plan_request=self.plan_request,
            evidence_report=self.evidence_report,
        )
        out2 = optimize_four_clinic_stops(
            health_evidence=self.health_evidence,
            mobility_evidence=self.mobility_evidence,
            plan_request=self.plan_request,
            evidence_report=self.evidence_report,
        )
        self.assertEqual(out1, out2)
        plan1 = DraftPlan.model_validate(out1)
        self.assertEqual(plan1.status, "ok")
        self.assertEqual(len(plan1.stops), 4)

    def test_02_distinct_catchments_and_separation(self) -> None:
        """All 4 selected stops have distinct primary tracts and pairwise distances >= 5.0 km."""
        out = optimize_four_clinic_stops(
            health_evidence=self.health_evidence,
            mobility_evidence=self.mobility_evidence,
            plan_request=self.plan_request,
            evidence_report=self.evidence_report,
        )
        plan = DraftPlan.model_validate(out)
        primary_geoids = [s.primary_tract_geoid for s in plan.stops]
        self.assertEqual(len(set(primary_geoids)), 4)

        stops = plan.stops
        for i in range(len(stops)):
            for j in range(i + 1, len(stops)):
                dist = haversine_km(
                    stops[i].latitude, stops[i].longitude,
                    stops[j].latitude, stops[j].longitude,
                )
                self.assertGreaterEqual(dist, 5.0)

    def test_03_runner_up_deferral_explanations_populated(self) -> None:
        """Ranks #5-#8 runner-up tracts have valid deferral reason codes and cited rationales."""
        out = optimize_four_clinic_stops(
            health_evidence=self.health_evidence,
            mobility_evidence=self.mobility_evidence,
            plan_request=self.plan_request,
            evidence_report=self.evidence_report,
        )
        plan = DraftPlan.model_validate(out)
        self.assertGreaterEqual(len(plan.runner_up_tracts), 1)
        for runner_up in plan.runner_up_tracts:
            self.assertIn(
                runner_up.deferral_reason_code,
                [
                    "catchment_already_covered",
                    "inter_stop_separation_constraint",
                    "no_saturday_transit_or_venue",
                    "lower_marginal_coverage",
                ],
            )
            self.assertTrue(len(runner_up.technical_deferral_rationale) > 20)

    def test_04_revision_remediation_resolves_catchment_overlap(self) -> None:
        """Simulated overlap defect in draft 0 is resolved in revision 1."""
        req_with_defect = PlanRequest(simulate_first_draft_defect=True)
        draft0_raw = optimize_four_clinic_stops(
            health_evidence=self.health_evidence,
            mobility_evidence=self.mobility_evidence,
            plan_request=req_with_defect,
            evidence_report=self.evidence_report,
            revision_number=0,
        )
        draft0 = DraftPlan.model_validate(draft0_raw)
        dist_0_1 = haversine_km(
            draft0.stops[0].latitude, draft0.stops[0].longitude,
            draft0.stops[1].latitude, draft0.stops[1].longitude,
        )
        self.assertLess(dist_0_1, 5.0)

        # Revision 1 with feedback
        draft1_raw = optimize_four_clinic_stops(
            health_evidence=self.health_evidence,
            mobility_evidence=self.mobility_evidence,
            plan_request=PlanRequest(simulate_first_draft_defect=False),
            evidence_report=self.evidence_report,
            non_demographic_feedback=["Catchment overlap defect: stop 1 and stop 2 within 5 km separation"],
            revision_number=1,
        )
        draft1 = DraftPlan.model_validate(draft1_raw)
        dist1_0_1 = haversine_km(
            draft1.stops[0].latitude, draft1.stops[0].longitude,
            draft1.stops[1].latitude, draft1.stops[1].longitude,
        )
        self.assertGreaterEqual(dist1_0_1, 5.0)
        self.assertEqual(draft1.revision_number, 1)

    def test_05_insufficient_candidates_handled_gracefully(self) -> None:
        """EvidenceReport core_tables_ready=False returns status='insufficient_candidates'."""
        bad_report = EvidenceReport(
            county_fips="13121",
            core_tables_ready=False,
            blocking_failures=["BigQuery table missing"],
        )
        out = optimize_four_clinic_stops(
            health_evidence=self.health_evidence,
            evidence_report=bad_report,
        )
        plan = DraftPlan.model_validate(out)
        self.assertEqual(plan.status, "insufficient_candidates")
        self.assertEqual(len(plan.stops), 0)

    def test_06_sensitivity_analysis_summary(self) -> None:
        """Sensitivity summary produces valid Jaccard index between 0.0 and 1.0."""
        sens = run_weight_sensitivity(
            tracts=self.health_evidence.tracts,
            mobility_map={m.geo_id: m for m in self.mobility_evidence.tract_mobility},
        )
        self.assertGreaterEqual(sens.top_4_stability_jaccard, 0.0)
        self.assertLessEqual(sens.top_4_stability_jaccard, 1.0)

    def test_07_race_blind_guard_blocks_demographic_data(self) -> None:
        """Passing demographic features to optimizer raises PolicyViolationError."""
        with self.assertRaises(PolicyViolationError):
            compute_tract_scores(
                tracts=self.health_evidence.tracts,
                custom_weights={"rpl_theme3": 0.5},
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
