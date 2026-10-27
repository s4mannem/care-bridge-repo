"""Unit and End-to-End Certification Tests for Plan 02 — Health & Access Evidence Agent (Agent A)."""

from __future__ import annotations

import unittest
from typing import Any, Dict, List

from carebridge.agents.health_agent import (
    HEALTH_AGENT_INSTRUCTION,
    build_health_access_agent,
    fetch_county_health_evidence,
)
from carebridge.contracts.evidence_models import (
    HealthEvidence,
    RegionalDiseaseSignal,
    SpatialGrain,
)
from carebridge.contracts.state_keys import STATE_HEALTH_EVIDENCE, STATE_PLAN_REQUEST
from carebridge.mocks.fulton_fixtures import FULTON_TRACT_HEALTH_RECORDS
from carebridge.security.race_blind_guard import (
    PolicyViolationError,
    assert_no_pii_in_payload,
    assert_race_blind_planner_input,
)
from carebridge.telemetry.otel import get_tracer, set_current_request_id
from google.adk.runners import InMemoryRunner


class _StubMCPBridge:
    """Stub BigQuery MCP Bridge exposing the 4 named queries from Plan 01 / Plan 02."""

    def __init__(self, null_disease_values: bool = False, inject_forbidden_col: bool = False) -> None:
        self.null_disease_values = null_disease_values
        self.inject_forbidden_col = inject_forbidden_col
        self.calls: List[str] = []

    def mcp_query_tract_burden_and_access(self, county_fips: str) -> List[Dict[str, Any]]:
        self.calls.append(f"mcp_query_tract_burden_and_access:{county_fips}")
        rows: List[Dict[str, Any]] = []
        for rec in FULTON_TRACT_HEALTH_RECORDS[:4]:
            d = rec.model_dump()
            # Omit derived pct_checkup_gap so tool normalization is tested end-to-end
            d["pct_checkup_gap"] = None
            if self.inject_forbidden_col:
                d["rpl_theme3"] = 0.91
            rows.append(d)
        return rows

    def mcp_query_care_sites_and_shortages(self, county_fips: str) -> Dict[str, Any]:
        self.calls.append(f"mcp_query_care_sites_and_shortages:{county_fips}")
        return {
            "county_name": "Fulton",
            "care_sites_count": 85,
            "safety_net_sites_count": 41,
            "shortage_areas_count": 0,
            "shortage_facilities_count": 6,
            "max_hpsa_score": 19.0,
        }

    def mcp_query_regional_disease_weekly(self, county_fips: str) -> Dict[str, Any]:
        self.calls.append(f"mcp_query_regional_disease_weekly:{county_fips}")
        if self.null_disease_values:
            return {
                "hsa_name": "Atlanta Regional HSA (Fulton, Ga)",
                "hsa_counties": "Fulton, DeKalb, Clayton, Gwinnett",
                "spatial_grain": SpatialGrain.MULTI_COUNTY_HSA.value,
                "latest_week_end": "2026-10-17",
                "percent_visits_covid": None,
                "percent_visits_influenza": None,
                "percent_visits_rsv": None,
                "data_unavailable": False,
            }
        return {
            "hsa_name": "Atlanta Regional HSA (Fulton, Ga)",
            "hsa_counties": "Fulton, DeKalb, Clayton, Gwinnett",
            "spatial_grain": SpatialGrain.MULTI_COUNTY_HSA.value,
            "latest_week_end": "2026-10-17",
            "percent_visits_covid": 1.8,
            "percent_visits_influenza": 2.4,
            "percent_visits_rsv": 1.3,
            "ed_trends_covid": "Stable",
            "ed_trends_influenza": "Increasing",
            "ed_trends_rsv": "Increasing",
            "data_unavailable": False,
        }

    def mcp_query_air_exposure_tail(self, county_fips: str) -> List[Dict[str, Any]]:
        self.calls.append(f"mcp_query_air_exposure_tail:{county_fips}")
        return [
            {
                "geo_id": rec.geo_id,
                "pm25_days_over_20": rec.pm25_days_over_20,
                "mean_pm25_12km_caveat": rec.mean_pm25_12km_caveat,
            }
            for rec in FULTON_TRACT_HEALTH_RECORDS[:4]
        ]


class TestPlan02HealthAccessEvidenceAgent(unittest.TestCase):
    """Certifies Plan 02 — Health & Access Evidence Agent (Agent A · MCP)."""

    def setUp(self) -> None:
        get_tracer().clear()
        set_current_request_id("req-test-plan02")

    def test_01_fetch_county_health_evidence_valid_fulton_schema_and_checkup_inversion(self) -> None:
        """Requirement 1: Returns valid HealthEvidence for Fulton (13121) with inverted pct_checkup_gap."""
        raw_payload = fetch_county_health_evidence(county_fips="13121")
        evidence = HealthEvidence.model_validate(raw_payload)

        self.assertEqual(evidence.county_fips, "13121")
        self.assertEqual(evidence.county_name, "Fulton")
        self.assertGreaterEqual(len(evidence.tracts), 12)

        for tract in evidence.tracts:
            self.assertEqual(len(tract.geo_id), 11)
            self.assertTrue(tract.geo_id.startswith("13121"))
            self.assertIsNotNone(tract.pct_checkup)
            self.assertIsNotNone(tract.pct_checkup_gap)
            self.assertAlmostEqual(
                float(tract.pct_checkup_gap),
                round(100.0 - float(tract.pct_checkup), 2),
                places=2,
            )
            self.assertIsNotNone(tract.pct_uninsured_18_64)
            self.assertIsNotNone(tract.pct_uninsured_all_ages)
            self.assertAlmostEqual(
                float(tract.uninsured_age_structure_gap),
                round(float(tract.pct_uninsured_18_64) - float(tract.pct_uninsured_all_ages), 2),
                places=2,
            )
            self.assertIsNotNone(tract.km_to_any_care)
            self.assertIsNotNone(tract.km_to_safety_net)
            self.assertAlmostEqual(
                float(tract.extra_km_if_uninsured),
                round(float(tract.km_to_safety_net) - float(tract.km_to_any_care), 2),
                places=2,
            )

    def test_02_fulton_shortage_areas_vs_facilities_nuance_preserved(self) -> None:
        """Requirement 2: Preserves shortage_areas_count=0 vs shortage_facilities_count=6 with explicit flag."""
        raw_payload = fetch_county_health_evidence(county_fips="13121")
        evidence = HealthEvidence.model_validate(raw_payload)

        self.assertEqual(evidence.shortage_areas_count, 0)
        self.assertEqual(evidence.shortage_facilities_count, 6)
        self.assertIn(evidence.care_sites_count, (69, 85))
        self.assertIn(evidence.safety_net_sites_count, (41, 55))
        self.assertTrue(
            any("shortage_areas" in src for src in evidence.source_lineage),
            "Expected shortage_areas vs shortage_facilities lineage entry.",
        )
        self.assertTrue(
            any("shortage_areas_count=0" in flag and "Proposed For Withdrawal" in flag for flag in evidence.missingness_flags),
            "Expected explicit missingness flag noting 0 active shortage_areas (Proposed For Withdrawal).",
        )

    def test_03_regional_disease_hsa_grain_and_null_handling(self) -> None:
        """Requirement 3: Enforces SpatialGrain.MULTI_COUNTY_HSA, grain_warning, and NULL -> data_unavailable."""
        raw_payload = fetch_county_health_evidence(county_fips="13121")
        evidence = HealthEvidence.model_validate(raw_payload)

        self.assertEqual(evidence.regional_disease.spatial_grain, SpatialGrain.MULTI_COUNTY_HSA)
        self.assertIn("Health Service Area", evidence.regional_disease.grain_warning)
        self.assertIn("NEVER at the census tract", evidence.regional_disease.grain_warning)
        self.assertIsInstance(evidence.regional_disease.data_unavailable, bool)

        # Verify NULL NSSP values automatically set data_unavailable=True ("we cannot tell", never "no increase")
        stub_null_hsa = _StubMCPBridge(null_disease_values=True)
        null_payload = fetch_county_health_evidence(county_fips="13121", mcp_client=stub_null_hsa)
        null_evidence = HealthEvidence.model_validate(null_payload)

        self.assertEqual(len(stub_null_hsa.calls), 4)
        self.assertTrue(null_evidence.regional_disease.data_unavailable)
        self.assertTrue(
            any("data_unavailable=True" in flag for flag in null_evidence.missingness_flags)
        )

    def test_04_in_memory_runner_populates_session_state_and_passes_race_blind_guard(self) -> None:
        """Requirement 4: Running build_health_access_agent() via InMemoryRunner populates session.state['health_evidence']."""
        agent = build_health_access_agent()
        self.assertEqual(agent.name, "health_access_agent")
        self.assertEqual(agent.output_key, STATE_HEALTH_EVIDENCE)
        self.assertIn("{plan_request?}", HEALTH_AGENT_INSTRUCTION)

        runner = InMemoryRunner(agent=agent, app_name="carebridge")
        session = runner.session_service.create_session_sync(
            app_name="carebridge",
            user_id="outreach-lead",
            session_id="sess-health-02",
            state={
                STATE_PLAN_REQUEST: {
                    "county_fips": "13121",
                    "county_name": "Fulton County, GA",
                    "strategy": "balanced",
                }
            },
        )

        events = list(
            runner.run(
                user_id="outreach-lead",
                session_id=session.id,
                new_message="Gather Fulton County health and access evidence.",
            )
        )
        self.assertGreaterEqual(len(events), 1)
        self.assertIn(STATE_HEALTH_EVIDENCE, session.state)

        stored_evidence = session.state[STATE_HEALTH_EVIDENCE]
        assert_race_blind_planner_input(stored_evidence)
        assert_no_pii_in_payload(stored_evidence)

        validated = HealthEvidence.model_validate(stored_evidence)
        self.assertEqual(validated.county_fips, "13121")
        self.assertEqual(validated.shortage_areas_count, 0)
        self.assertEqual(validated.shortage_facilities_count, 6)
        self.assertEqual(validated.regional_disease.spatial_grain, SpatialGrain.MULTI_COUNTY_HSA)

        # Verify OpenTelemetry span `agent.health_access.fetch_evidence` was emitted
        spans = [s for s in get_tracer().recorded_spans if s.name == "agent.health_access.fetch_evidence"]
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0].attributes["county_fips"], "13121")
        self.assertEqual(spans[0].attributes["shortage_areas_count"], 0)
        self.assertEqual(spans[0].attributes["shortage_facilities_count"], 6)
        self.assertIsInstance(spans[0].attributes["hsa_data_unavailable"], bool)

    def test_05_security_blocks_sql_injection_and_demographic_leakage(self) -> None:
        """Verifies OWASP SQL injection rejection and race-blind boundary enforcement on MCP rows."""
        with self.assertRaises(ValueError):
            fetch_county_health_evidence(county_fips="13121' OR '1'='1")

        stub_leaking = _StubMCPBridge(inject_forbidden_col=True)
        with self.assertRaises(PolicyViolationError):
            fetch_county_health_evidence(county_fips="13121", mcp_client=stub_leaking)

    def test_06_stale_disease_data_triggers_freshness_warning(self) -> None:
        """Verifies that regional disease weekly data older than 90 days triggers a freshness warning flag."""
        class _HistoricalDiseaseMCPBridge(_StubMCPBridge):
            def mcp_query_regional_disease_weekly(self, county_fips: str) -> Dict[str, Any]:
                base = super().mcp_query_regional_disease_weekly(county_fips)
                base["latest_week_end"] = "2024-09-28"
                return base

        payload = fetch_county_health_evidence(county_fips="13121", mcp_client=_HistoricalDiseaseMCPBridge())
        evidence = HealthEvidence.model_validate(payload)
        self.assertTrue(
            any("respiratory_trend_freshness" in flag for flag in evidence.missingness_flags),
            f"Expected respiratory_trend_freshness warning in missingness_flags: {evidence.missingness_flags}",
        )



if __name__ == "__main__":
    unittest.main()
