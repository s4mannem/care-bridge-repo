"""Unit and end-to-end verification tests for Plan 04 — Evidence Validator Agent."""

from __future__ import annotations

import unittest
from typing import Any, Dict

from carebridge.agents.validator_agent import (
    MANDATORY_EVIDENCE_CAVEATS,
    VALIDATOR_AGENT_INSTRUCTION,
    build_evidence_validator_agent,
    evaluate_evidence_quality,
    validate_collected_evidence_tool,
)
from carebridge.contracts.evidence_models import EvidenceReport, SpatialGrain
from carebridge.contracts.state_keys import (
    STATE_EVIDENCE_REPORT,
    STATE_HEALTH_EVIDENCE,
    STATE_MOBILITY_EVIDENCE,
)
from carebridge.mocks.fulton_fixtures import (
    build_mock_health_evidence,
    build_mock_mobility_evidence,
)
from carebridge.security.race_blind_guard import (
    assert_no_pii_in_payload,
    assert_race_blind_planner_input,
)
from carebridge.telemetry.otel import get_tracer, set_current_request_id


class _MockToolContext:
    def __init__(self, state: Dict[str, Any], agent_name: str = "evidence_validator_agent") -> None:
        self.state = state
        self.agent_name = agent_name


class TestPlan04EvidenceValidatorAgent(unittest.TestCase):
    """Verifies Plan 04 deterministic check()/note() rules, 4-resolution caveats, telemetry, and ADK agent."""

    def setUp(self) -> None:
        get_tracer().clear()
        set_current_request_id("req-test-plan04")

    def test_01_valid_fulton_fixtures_pass_all_core_checks(self) -> None:
        """Valid Fulton County (13121) fixtures pass with core_tables_ready=True and blocking_failures == []."""
        health = build_mock_health_evidence("13121")
        mobility = build_mock_mobility_evidence("13121", include_optional=True)

        report = evaluate_evidence_quality(health, mobility)
        self.assertIsInstance(report, EvidenceReport)
        self.assertEqual(report.county_fips, "13121")
        self.assertTrue(report.core_tables_ready)
        self.assertEqual(report.blocking_failures, [])
        self.assertEqual(report.validated_tract_count, len(health.tracts))

        # HPSA shortage_areas == 0 in Fulton is a key finding (WARN note, not a FAIL)
        checks_by_name = {c.check_name: c for c in report.checks}
        self.assertIn("hpsa_shortage_area_vs_facility_nuance", checks_by_name)
        self.assertEqual(checks_by_name["hpsa_shortage_area_vs_facility_nuance"].verdict, "WARN")
        self.assertFalse(checks_by_name["hpsa_shortage_area_vs_facility_nuance"].is_pipeline_check)

        # Optional datasets are all available
        self.assertEqual(
            report.optional_datasets_status,
            {
                "marta_gtfs": "available",
                "usda_food_access": "available",
                "imls_candidate_venues": "available",
            },
        )

        # Ensure report passes race-blind and PII guards
        assert_race_blind_planner_input(report.model_dump())
        assert_no_pii_in_payload(report.model_dump())

    def test_02_invalid_geoid_length_or_wrong_county_prefix_blocks_planning(self) -> None:
        """A 10-char geo_id or wrong county prefix (13089 DeKalb in 13121 Fulton) triggers FAIL and core_tables_ready=False."""
        # Case A: 10-character geo_id
        health_short = build_mock_health_evidence("13121").model_copy(deep=True)
        health_short.tracts[0].geo_id = "1312101021"  # 10 chars instead of 11
        mobility = build_mock_mobility_evidence("13121", include_optional=True).model_copy(deep=True)

        report_short = evaluate_evidence_quality(health_short, mobility)
        self.assertFalse(report_short.core_tables_ready)
        self.assertGreater(len(report_short.blocking_failures), 0)
        geoid_check_short = {c.check_name: c for c in report_short.checks}[
            "tract_geoid_11char_and_county_prefix"
        ]
        self.assertEqual(geoid_check_short.verdict, "FAIL")
        self.assertTrue(geoid_check_short.is_pipeline_check)
        assert_race_blind_planner_input(report_short.model_dump())
        assert_no_pii_in_payload(report_short.model_dump())

        # Case B: Wrong county prefix (13089 DeKalb inside 13121 Fulton pull)
        health_dekalb = build_mock_health_evidence("13121").model_copy(deep=True)
        health_dekalb.tracts[1].geo_id = "13089020100"
        report_dekalb = evaluate_evidence_quality(health_dekalb, mobility)
        self.assertFalse(report_dekalb.core_tables_ready)
        self.assertGreater(len(report_dekalb.blocking_failures), 0)
        geoid_check_dekalb = {c.check_name: c for c in report_dekalb.checks}[
            "tract_geoid_11char_and_county_prefix"
        ]
        self.assertEqual(geoid_check_dekalb.verdict, "FAIL")
        self.assertIn("13089020100", geoid_check_dekalb.detail)
        assert_race_blind_planner_input(report_dekalb.model_dump())
        assert_no_pii_in_payload(report_dekalb.model_dump())

    def test_03_missing_optional_datasets_warn_without_blocking(self) -> None:
        """Missing optional datasets (marta_gtfs_available=False) produce a WARN note() and keep core_tables_ready=True."""
        health = build_mock_health_evidence("13121")
        mobility_degraded = build_mock_mobility_evidence("13121", include_optional=False)

        report = evaluate_evidence_quality(health, mobility_degraded)
        self.assertTrue(report.core_tables_ready)
        self.assertEqual(report.blocking_failures, [])

        checks_by_name = {c.check_name: c for c in report.checks}
        self.assertIn("optional_datasets_availability", checks_by_name)
        opt_check = checks_by_name["optional_datasets_availability"]
        self.assertEqual(opt_check.verdict, "WARN")
        self.assertFalse(opt_check.is_pipeline_check)

        self.assertEqual(report.optional_datasets_status["marta_gtfs"], "unavailable")
        self.assertEqual(report.optional_datasets_status["usda_food_access"], "unavailable")
        self.assertEqual(report.optional_datasets_status["imls_candidate_venues"], "unavailable")
        self.assertTrue(
            any("OPTIONAL DATASET" in caveat for caveat in report.caveats),
            "Expected optional dataset degradation caveat in EvidenceReport.caveats",
        )

    def test_04_mandatory_4_resolution_and_distance_caveats_always_present(self) -> None:
        """Tract != HSA and Distance != journey time caveats are always present in EvidenceReport.caveats."""
        health = build_mock_health_evidence("13121")
        for include_opt in (True, False):
            mobility = build_mock_mobility_evidence("13121", include_optional=include_opt)
            report = evaluate_evidence_quality(health, mobility)
            for mandatory_caveat in MANDATORY_EVIDENCE_CAVEATS:
                self.assertIn(mandatory_caveat, report.caveats)
            self.assertTrue(
                any("TRACT != 12KM GRID != FACILITY POINT != 4-COUNTY HSA" in c for c in report.caveats)
            )
            self.assertTrue(any("DISTANCE != JOURNEY TIME" in c for c in report.caveats))

    def test_05_pipeline_integrity_and_poisoning_defenses(self) -> None:
        """Empty tracts, duplicate GEOIDs, bad coordinates, un-inverted checkup, HSA grain violation, and leaked race/PII block planning."""
        mobility = build_mock_mobility_evidence("13121", include_optional=True).model_copy(deep=True)

        # 5a. Empty burden_tracts
        health_empty = build_mock_health_evidence("13121").model_copy(deep=True)
        health_empty.tracts = []
        rep_empty = evaluate_evidence_quality(health_empty, mobility)
        self.assertFalse(rep_empty.core_tables_ready)
        self.assertEqual(rep_empty.validated_tract_count, 0)

        # 5b. Duplicate tract IDs
        health_dupe = build_mock_health_evidence("13121").model_copy(deep=True)
        health_dupe.tracts.append(health_dupe.tracts[0].model_copy(deep=True))
        rep_dupe = evaluate_evidence_quality(health_dupe, mobility)
        self.assertFalse(rep_dupe.core_tables_ready)
        self.assertTrue(any("unique_tract_geoids" in f for f in rep_dupe.blocking_failures))

        # 5c. Out-of-bounds coordinates
        health_coord = build_mock_health_evidence("13121").model_copy(deep=True)
        health_coord.tracts[0].latitude = 85.0  # outside [17, 72]
        rep_coord = evaluate_evidence_quality(health_coord, mobility)
        self.assertFalse(rep_coord.core_tables_ready)
        self.assertTrue(any("north_america_coordinates_bounds" in f for f in rep_coord.blocking_failures))

        # 5d. Routine checkup inversion violated
        health_chk = build_mock_health_evidence("13121").model_copy(deep=True)
        health_chk.tracts[0].pct_checkup = 68.5
        health_chk.tracts[0].pct_checkup_gap = 68.5  # un-inverted!
        rep_chk = evaluate_evidence_quality(health_chk, mobility)
        self.assertFalse(rep_chk.core_tables_ready)
        self.assertTrue(any("pct_checkup_inversion_verified" in f for f in rep_chk.blocking_failures))

        # 5e. Regional disease grain violation (Tract instead of MULTI_COUNTY_HSA)
        health_grain = build_mock_health_evidence("13121").model_copy(deep=True)
        health_grain.regional_disease.spatial_grain = SpatialGrain.TRACT
        rep_grain = evaluate_evidence_quality(health_grain, mobility)
        self.assertFalse(rep_grain.core_tables_ready)
        self.assertTrue(any("regional_disease_hsa_grain_verified" in f for f in rep_grain.blocking_failures))

        # 5f. Impossible prevalence (> 100%) escalates note() to FAIL
        health_imposs = build_mock_health_evidence("13121").model_copy(deep=True)
        health_imposs.tracts[0].pct_uninsured_18_64 = 142.0
        rep_imposs = evaluate_evidence_quality(health_imposs, mobility)
        self.assertFalse(rep_imposs.core_tables_ready)
        self.assertTrue(any("prevalence_bounds_0_to_100" in f for f in rep_imposs.blocking_failures))

        # 5g. Leaked demographic or PII column in payload blocks planning while keeping report sanitized
        leaked_health_dict = build_mock_health_evidence("13121").model_dump()
        leaked_health_dict["tracts"][0]["rpl_theme3"] = 0.94
        rep_leaked = evaluate_evidence_quality(leaked_health_dict, mobility)
        self.assertFalse(rep_leaked.core_tables_ready)
        self.assertTrue(any("race_blind_and_pii_exclusion" in f for f in rep_leaked.blocking_failures))
        # The report itself must remain sanitized for downstream inspection
        assert_race_blind_planner_input(rep_leaked.model_dump())
        assert_no_pii_in_payload(rep_leaked.model_dump())

    def test_06_agent_builder_tool_state_and_telemetry_e2e(self) -> None:
        """End-to-end verification of build_evidence_validator_agent(), InMemoryRunner, tool state write, OWASP callbacks, and OTel spans."""
        from google.adk.runners import InMemoryRunner  # type: ignore

        agent = build_evidence_validator_agent()
        self.assertEqual(agent.name, "evidence_validator_agent")
        self.assertEqual(agent.output_key, STATE_EVIDENCE_REPORT)
        self.assertEqual(agent.output_schema, EvidenceReport)
        self.assertEqual(agent.instruction, VALIDATOR_AGENT_INSTRUCTION)
        self.assertIn("{health_evidence?}", agent.instruction)
        self.assertIn("{mobility_evidence?}", agent.instruction)
        self.assertEqual(len(agent.tools), 1)

        runner = InMemoryRunner(agent=agent, app_name="carebridge-test")
        session = runner.session_service.create_session_sync(
            app_name="carebridge-test",
            user_id="outreach-lead",
            session_id="sess-plan04-e2e",
            state={
                STATE_HEALTH_EVIDENCE: build_mock_health_evidence("13121").model_dump(),
                STATE_MOBILITY_EVIDENCE: build_mock_mobility_evidence("13121", include_optional=True).model_dump(),
            },
        )
        events = list(
            runner.run(
                user_id="outreach-lead",
                session_id=session.id,
                new_message="Validate collected health and mobility evidence for Fulton County.",
            )
        )
        self.assertGreaterEqual(len(events), 1)

        # Verify session.state["evidence_report"] was written and validates as EvidenceReport
        self.assertIn(STATE_EVIDENCE_REPORT, session.state)
        validated_report = EvidenceReport.model_validate(session.state[STATE_EVIDENCE_REPORT])
        self.assertTrue(validated_report.core_tables_ready)
        self.assertEqual(validated_report.validated_tract_count, 12)

        # Verify OpenTelemetry span attributes required by Plan 04 Section 4
        spans = [s for s in get_tracer().recorded_spans if s.name == "agent.evidence_validator.validate"]
        self.assertGreaterEqual(len(spans), 1)
        latest_span = spans[-1]
        self.assertTrue(latest_span.attributes["core_tables_ready"])
        self.assertEqual(latest_span.attributes["validated_tract_count"], 12)
        self.assertEqual(latest_span.attributes["fail_count"], 0)
        self.assertGreater(latest_span.attributes["pass_count"], 0)
        self.assertGreaterEqual(latest_span.attributes["warn_count"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
