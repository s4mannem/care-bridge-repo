"""Integration tests verifying agent connection to Cloud BigQuery instance and views.

Covers:
1. `BigQueryMCPBridge` query generation for all 9 views in `a4i_health` and `marta_gtfs`.
2. Simulated live `.query()` execution ensuring `mcp_tools.yaml` statements are executed.
3. Live Cloud BigQuery execution when `google.cloud.bigquery` and `GOOGLE_CLOUD_PROJECT`
   credentials are present.
"""

from __future__ import annotations

import os
import unittest
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

from carebridge.contracts.evidence_models import HealthEvidence, MobilityEvidence
from carebridge.data_plane.bq_mcp_client import BigQueryMCPBridge, BigQueryNotFoundError
from carebridge.security.race_blind_guard import (
    assert_no_pii_in_payload,
    assert_race_blind_planner_input,
)


class TestCloudBigQueryIntegration(unittest.TestCase):
    """Tests live and simulated BigQuery connection and view reads for agents."""

    def test_01_sql_statements_use_configured_views_with_project_qualification(self) -> None:
        """Verifies BigQueryMCPBridge formats statements using the 9 configured views."""
        bridge = BigQueryMCPBridge(use_mock_data=False)
        bridge.project_id = "test-a4i-project"

        # Check statement for burden and access
        sql_burden = bridge.get_tool_statement("mcp_query_tract_burden_and_access")
        self.assertIn("`test-a4i-project.a4i_health.v_burden_tracts`", sql_burden)
        self.assertIn("`test-a4i-project.a4i_health.v_tract_access`", sql_burden)

        # Check statement for care sites
        sql_sites = bridge.get_tool_statement("mcp_query_care_sites_and_shortages")
        self.assertIn("`test-a4i-project.a4i_health.v_care_sites`", sql_sites)
        self.assertIn("`test-a4i-project.a4i_health.v_shortage_areas`", sql_sites)
        self.assertIn("`test-a4i-project.a4i_health.v_shortage_facilities`", sql_sites)

        # Check statement for disease weekly
        sql_disease = bridge.get_tool_statement("mcp_query_regional_disease_weekly")
        self.assertIn("`test-a4i-project.a4i_health.v_disease_weekly`", sql_disease)

        # Check statement for air exposure
        sql_air = bridge.get_tool_statement("mcp_query_air_exposure_tail")
        self.assertIn("`test-a4i-project.a4i_health.v_exposure_tracts`", sql_air)

        # Check statement for Saturday transit
        sql_transit = bridge.get_tool_statement("mcp_query_saturday_transit_and_venues")
        self.assertIn("`test-a4i-project.marta_gtfs.v_tract_saturday_transit_access`", sql_transit)

    def test_02_simulated_cloud_bq_query_execution_and_schema_parsing(self) -> None:
        """Simulates a live BigQuery Client with .query() to ensure row parsing works end-to-end."""
        executed_queries: List[str] = []

        class _MockBQJob:
            def __init__(self, rows: List[Dict[str, Any]]):
                self._rows = rows
                self.total_bytes_billed = 1048576

            def result(self) -> List[Dict[str, Any]]:
                return self._rows

        class _MockCloudBQClient:
            def query(self, sql: str, job_config: Any = None) -> _MockBQJob:
                executed_queries.append(sql)
                if "v_care_sites" in sql:
                    return _MockBQJob([
                        {
                            "county_fips": "13121",
                            "county_name": "Fulton",
                            "care_sites_count": 69,
                            "safety_net_sites_count": 55,
                            "shortage_areas_count": 0,
                            "shortage_facilities_count": 6,
                            "max_hpsa_score": 24.0,
                        }
                    ])
                elif "v_disease_weekly" in sql:
                    return _MockBQJob([
                        {
                            "hsa_name": "Fulton (Atlanta), GA - DeKalb, GA",
                            "hsa_counties": "Clayton, DeKalb, Fulton, Gwinnett",
                            "spatial_grain": "multi_county_health_service_area",
                            "latest_week_end": "2026-10-17 00:00:00",
                            "percent_visits_covid": None,
                            "percent_visits_influenza": None,
                            "percent_visits_rsv": None,
                            "ed_trends_covid": "Data Unavailable",
                            "ed_trends_influenza": "Data Unavailable",
                            "ed_trends_rsv": "Data Unavailable",
                        }
                    ])
                elif "v_burden_tracts" in sql:
                    return _MockBQJob([
                        {
                            "geo_id": "13121010214",
                            "total_pop": 2450,
                            "latitude": 33.725,
                            "longitude": -84.412,
                            "pct_uninsured_18_64": 28.5,
                            "pct_uninsured_all_ages": 21.0,
                            "uninsured_age_structure_gap": 7.5,
                            "pct_asthma": 14.2,
                            "pct_copd": 9.1,
                            "pct_diabetes": 16.8,
                            "pct_bphigh": 42.0,
                            "pct_checkup": 68.5,
                            "pct_checkup_gap": 31.5,
                            "pct_uninsured_18_64_ci_width": None,
                            "pct_no_vehicle": 43.0,
                            "pct_age_65_plus": 12.0,
                            "pct_mobility_difficulty": 18.5,
                            "pct_lack_transport": 22.1,
                            "km_to_any_care": 0.8,
                            "km_to_safety_net": 8.1,
                            "extra_km_if_uninsured": 7.3,
                            "cross_border_state_care_km": None,
                        }
                    ])
                elif "v_exposure_tracts" in sql:
                    return _MockBQJob([
                        {
                            "geo_id": "13121010214",
                            "pm25_days_over_20": 4,
                            "mean_pm25_12km_caveat": 9.4,
                        }
                    ])
                elif "v_tract_saturday_transit_access" in sql:
                    return _MockBQJob([
                        {
                            "geo_id": "13121010214",
                            "saturday_active_stops_count": 8,
                            "saturday_mean_headway_min": 24.5,
                            "usda_low_income_low_access": True,
                            "candidate_venues": [],
                        }
                    ])
                return _MockBQJob([])

        bridge = BigQueryMCPBridge(bq_client=_MockCloudBQClient(), use_mock_data=False)
        bridge.project_id = "a4i-fulton-cloud"

        # 1. Execute named queries
        tracts = bridge.mcp_query_tract_burden_and_access("13121")
        sites = bridge.mcp_query_care_sites_and_shortages("13121")
        disease = bridge.mcp_query_regional_disease_weekly("13121")
        mobility = bridge.mcp_query_saturday_transit_and_venues("13121")

        # 2. Verify exact view names in executed SQL
        self.assertTrue(any("v_burden_tracts" in q for q in executed_queries))
        self.assertTrue(any("v_care_sites" in q for q in executed_queries))
        self.assertTrue(any("v_disease_weekly" in q for q in executed_queries))
        self.assertTrue(any("v_tract_saturday_transit_access" in q for q in executed_queries))

        # 3. Verify returned data
        self.assertEqual(len(tracts), 1)
        self.assertEqual(tracts[0]["geo_id"], "13121010214")
        self.assertEqual(sites["care_sites_count"], 69)
        self.assertEqual(disease["spatial_grain"], "multi_county_health_service_area")
        self.assertTrue(mobility.marta_gtfs_available)

    def test_03_live_cloud_bigquery_when_credentials_present(self) -> None:
        """Executes against live GCP BigQuery if google-cloud-bigquery & credentials exist."""
        project = os.environ.get("GOOGLE_CLOUD_PROJECT") or "qwiklabs-gcp-04-e4394201f6b9"
        try:
            from google.cloud import bigquery  # type: ignore
        except ImportError:
            self.skipTest(
                "Skipping live BigQuery test: `google-cloud-bigquery` not installed. "
                "Run `pip install google-cloud-bigquery` and `scripts/verify_cloud_bigquery.py` to test live."
            )

        if not project or project in ("your-gcp-project-id", "a4i-fulton-2026"):
            self.skipTest(
                "Skipping live BigQuery test: GOOGLE_CLOUD_PROJECT environment variable not set to a live project. "
                "Run `export GOOGLE_CLOUD_PROJECT=<project>` and `scripts/verify_cloud_bigquery.py`."
            )

        try:
            client = bigquery.Client(project=project)
        except Exception as exc:
            self.skipTest(f"Skipping live BigQuery test: credentials unavailable: {exc}")

        # Live query against the views via BigQueryMCPBridge and Agent tools
        bridge = BigQueryMCPBridge(bq_client=client, use_mock_data=False)
        bridge.project_id = project

        tracts = bridge.mcp_query_tract_burden_and_access("13121")
        self.assertEqual(len(tracts), 326)
        assert_race_blind_planner_input(tracts)
        assert_no_pii_in_payload(tracts)

        sites = bridge.mcp_query_care_sites_and_shortages("13121")
        self.assertEqual(sites["care_sites_count"], 69)
        self.assertEqual(sites["shortage_areas_count"], 0)
        self.assertEqual(sites["shortage_facilities_count"], 6)
        assert_race_blind_planner_input(sites)
        assert_no_pii_in_payload(sites)

        disease = bridge.mcp_query_regional_disease_weekly("13121")
        self.assertEqual(disease["spatial_grain"], "multi_county_health_service_area")
        assert_race_blind_planner_input(disease)

        air = bridge.mcp_query_air_exposure_tail("13121")
        self.assertEqual(len(air), 327)
        assert_race_blind_planner_input(air)

        health_ev = bridge.fetch_health_evidence("13121")
        self.assertIsInstance(health_ev, HealthEvidence)
        self.assertEqual(len(health_ev.tracts), 326)

        mobility_ev = bridge.mcp_query_saturday_transit_and_venues("13121")
        self.assertIsInstance(mobility_ev, MobilityEvidence)
        self.assertTrue(mobility_ev.marta_gtfs_available)
        self.assertEqual(len(mobility_ev.tract_mobility), 204)
        assert_race_blind_planner_input(mobility_ev.model_dump())
        assert_no_pii_in_payload(mobility_ev.model_dump())


if __name__ == "__main__":
    unittest.main()
