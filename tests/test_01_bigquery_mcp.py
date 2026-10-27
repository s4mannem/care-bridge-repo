"""Verification & unit tests for Plan 01 — BigQuery Data Plane, SQL Views & MCP Toolset Boundary."""

from __future__ import annotations

from pathlib import Path
import unittest

from carebridge.contracts.evidence_models import HealthEvidence, MobilityEvidence
from carebridge.data_plane import (
    MAX_BQ_BYTES_BILLED,
    MCP_TOOLS_YAML_PATH,
    BigQueryMCPBridge,
    BigQueryNotFoundError,
    get_auditor_demographic_mcp_tools,
    get_evidence_toolset,
    get_health_evidence_mcp_tools,
    get_mobility_evidence_mcp_tools,
    validate_county_fips,
)
from carebridge.security.race_blind_guard import (
    PolicyViolationError,
    assert_no_pii_in_payload,
    assert_race_blind_planner_input,
)
from carebridge.telemetry.otel import get_tracer


class TestPlan01BigQueryMCP(unittest.TestCase):
    """Tests all 4 Plan 01 requirements plus SQL views, billing caps, and OTel spans."""

    def setUp(self) -> None:
        get_tracer().clear()
        self.bridge = BigQueryMCPBridge(use_mock_data=False)

    def test_01_named_queries_reject_non_5_digit_county_fips_and_sqli(self) -> None:
        """Requirement 1: Named queries reject non-5-digit county_fips (e.g., SQL injection raises ValueError)."""
        malicious_inputs = [
            "13121' OR '1'='1",
            "13121; DROP TABLE burden_tracts;--",
            "1312",
            "131210",
            "abcde",
            "",
        ]
        for bad_fips in malicious_inputs:
            with self.assertRaises(ValueError):
                validate_county_fips(bad_fips)
            with self.assertRaises(ValueError):
                self.bridge.mcp_query_tract_burden_and_access(bad_fips)
            with self.assertRaises(ValueError):
                self.bridge.mcp_query_care_sites_and_shortages(bad_fips)
            with self.assertRaises(ValueError):
                self.bridge.mcp_query_regional_disease_weekly(bad_fips)
            with self.assertRaises(ValueError):
                self.bridge.mcp_query_saturday_transit_and_venues(bad_fips)
            with self.assertRaises(ValueError):
                self.bridge.mcp_query_posthoc_demographic_audit(bad_fips)

    def test_02_evidence_toolsets_physically_exclude_demographic_audit(self) -> None:
        """Requirement 2: get_health_evidence_mcp_tools() and get_mobility_evidence_mcp_tools() never include mcp_query_posthoc_demographic_audit."""
        health_tools = get_health_evidence_mcp_tools(self.bridge)
        mobility_tools = get_mobility_evidence_mcp_tools(self.bridge)
        combined_evidence_tools = get_evidence_toolset(self.bridge)
        auditor_tools = get_auditor_demographic_mcp_tools(self.bridge)

        health_names = {t.__name__ for t in health_tools}
        mobility_names = {t.__name__ for t in mobility_tools}
        evidence_names = {t.__name__ for t in combined_evidence_tools}
        auditor_names = {t.__name__ for t in auditor_tools}

        self.assertNotIn("mcp_query_posthoc_demographic_audit", health_names)
        self.assertNotIn("query_demographic_audit_tracts", health_names)
        self.assertNotIn("mcp_query_posthoc_demographic_audit", mobility_names)
        self.assertNotIn("query_demographic_audit_tracts", mobility_names)
        self.assertNotIn("mcp_query_posthoc_demographic_audit", evidence_names)

        self.assertIn("mcp_query_posthoc_demographic_audit", auditor_names)
        self.assertTrue(evidence_names.isdisjoint(auditor_names))

        # Caller boundary enforcement: Planner / Evidence agents cannot call demographic audit
        with self.assertRaises(PolicyViolationError):
            self.bridge.mcp_query_posthoc_demographic_audit(
                "13121", caller_agent="siting_planner_agent"
            )
        with self.assertRaises(PolicyViolationError):
            self.bridge.mcp_query_posthoc_demographic_audit(
                "13121", caller_agent="health_access_agent"
            )

        # Auditor is permitted
        demo_rows = self.bridge.mcp_query_posthoc_demographic_audit(
            "13121", caller_agent="equity_rigor_auditor"
        )
        self.assertGreaterEqual(len(demo_rows), 12)
        self.assertIn("13121010214", demo_rows)
        self.assertIn("pct_minority", demo_rows["13121010214"])

    def test_03_graceful_degradation_when_marta_or_enrichment_views_missing(self) -> None:
        """Requirement 3: NotFound exception returns MobilityEvidence(marta_gtfs_available=False) with caveat rather than crashing."""

        class _NotFoundBQClient:
            def mcp_query_saturday_transit_and_venues(self, county_fips: str) -> None:
                raise BigQueryNotFoundError(
                    f"404 Not found: Table a4i-fulton-2026:marta_gtfs.v_tract_saturday_transit_access for {county_fips}"
                )

        degraded_bridge = BigQueryMCPBridge(bq_client=_NotFoundBQClient(), use_mock_data=False)
        evidence = degraded_bridge.mcp_query_saturday_transit_and_venues("13121")

        self.assertIsInstance(evidence, MobilityEvidence)
        self.assertFalse(evidence.marta_gtfs_available)
        self.assertFalse(evidence.usda_food_access_available)
        self.assertFalse(evidence.imls_venues_available)
        self.assertEqual(len(evidence.tract_mobility), 0)
        self.assertTrue(
            any("NotFound" in c or "missing" in c or "unavailable" in c for c in evidence.caveats)
        )

        # Also verify explicit include_optional_datasets=False flag
        disabled_evidence = self.bridge.mcp_query_saturday_transit_and_venues(
            "13121", include_optional_datasets=False
        )
        self.assertFalse(disabled_evidence.marta_gtfs_available)
        self.assertFalse(disabled_evidence.usda_food_access_available)
        self.assertFalse(disabled_evidence.imls_venues_available)

    def test_04_all_evidence_query_outputs_pass_race_blind_and_pii_guards(self) -> None:
        """Requirement 4: All outputs from evidence queries pass assert_race_blind_planner_input() and assert_no_pii_in_payload()."""
        tracts = self.bridge.mcp_query_tract_burden_and_access("13121")
        sites = self.bridge.mcp_query_care_sites_and_shortages("13121")
        disease = self.bridge.mcp_query_regional_disease_weekly("13121")
        air = self.bridge.mcp_query_air_exposure_tail("13121")
        mobility = self.bridge.mcp_query_saturday_transit_and_venues("13121")
        venues = self.bridge.query_candidate_venues("13121")
        food = self.bridge.query_food_access_enrichment("13121")
        health_ev = self.bridge.fetch_health_evidence("13121")

        self.assertIsInstance(health_ev, HealthEvidence)
        self.assertIsInstance(mobility, MobilityEvidence)
        self.assertGreaterEqual(len(tracts), 12)
        self.assertGreaterEqual(len(venues), 6)
        self.assertGreaterEqual(len(food), 12)

        for payload in (
            tracts,
            sites,
            disease,
            air,
            mobility.model_dump(),
            venues,
            food,
            health_ev.model_dump(),
        ):
            assert_race_blind_planner_input(payload)
            assert_no_pii_in_payload(payload)

        # Verify all candidate venues have host_permission_verified == False
        for v in venues:
            self.assertFalse(v["host_permission_verified"])

    def test_05_sql_files_yaml_config_and_otel_telemetry(self) -> None:
        """Verifies SQL setup scripts, mcp_tools.yaml, 100 MB billing cap, and OTel spans."""
        sql_dir = Path(__file__).resolve().parent.parent / "carebridge" / "data_plane" / "sql"
        sql_01 = (sql_dir / "01_marta_gtfs_views.sql").read_text(encoding="utf-8")
        sql_02 = (sql_dir / "02_optional_enrichments.sql").read_text(encoding="utf-8")
        sql_03 = (sql_dir / "03_demographic_audit_table.sql").read_text(encoding="utf-8")
        yaml_text = MCP_TOOLS_YAML_PATH.read_text(encoding="utf-8")

        self.assertIn("v_tract_saturday_transit_access", sql_01)
        self.assertIn("WHERE saturday = 1", sql_01)
        self.assertIn("GTFS_SATURDAY_STOP_PROXIMITY_NOT_JOURNEY_TIME", sql_01)
        self.assertIn("candidate_venues", sql_02)
        self.assertIn("FALSE AS host_permission_verified", sql_02)
        self.assertIn("external_demographic_audit.tract_demographics_audit", sql_03)
        self.assertIn("audit_only_toolset", yaml_text)
        self.assertIn("evidence_toolset", yaml_text)

        job_cfg = self.bridge.get_query_job_config("13121")
        self.assertEqual(job_cfg["maximum_bytes_billed"], MAX_BQ_BYTES_BILLED)

        get_tracer().clear()
        self.bridge.mcp_query_tract_burden_and_access("13121")
        spans = get_tracer().recorded_spans
        self.assertEqual(len(spans), 1)
        self.assertEqual(spans[0].name, "bq.mcp.mcp_query_tract_burden_and_access")
        self.assertEqual(spans[0].attributes["county_fips"], "13121")
        self.assertGreaterEqual(spans[0].attributes["rows_returned"], 12)


if __name__ == "__main__":
    unittest.main()
