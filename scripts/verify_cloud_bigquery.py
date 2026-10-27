#!/usr/bin/env python3
"""CareBridge AI — Live Cloud BigQuery Integration & View Verification Tool.

Connects to the live Google Cloud BigQuery instance to test and certify that
the agents and BigQuery MCP bridge can read from all 9 configured views:
  1. `a4i_health.v_burden_tracts`
  2. `a4i_health.v_care_sites`
  3. `a4i_health.v_care_sites_state`
  4. `a4i_health.v_disease_weekly`
  5. `a4i_health.v_exposure_tracts`
  6. `a4i_health.v_shortage_areas`
  7. `a4i_health.v_shortage_facilities`
  8. `a4i_health.v_tract_access`
  9. `marta_gtfs.v_tract_saturday_transit_access`

Usage:
    python3 scripts/verify_cloud_bigquery.py [--county-fips 13121] [--project my-gcp-project]
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List, Tuple

# Ensure workspace root is in sys.path
WORKSPACE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if WORKSPACE_DIR not in sys.path:
    sys.path.insert(0, WORKSPACE_DIR)

from carebridge.config import get_settings
from carebridge.data_plane.bq_mcp_client import BigQueryMCPBridge
from carebridge.security.race_blind_guard import (
    assert_no_pii_in_payload,
    assert_race_blind_planner_input,
)


HEALTH_VIEWS = [
    "v_burden_tracts",
    "v_care_sites",
    "v_care_sites_state",
    "v_disease_weekly",
    "v_exposure_tracts",
    "v_shortage_areas",
    "v_shortage_facilities",
    "v_tract_access",
]

MARTA_VIEWS = [
    "v_tract_saturday_transit_access",
]


def check_prerequisites(
    project_override: str | None = None,
    access_token: str | None = None,
) -> Tuple[bool, str, Any]:
    """Validates python packages, GCP environment, and BigQuery client initialization."""
    print("=" * 70)
    print("STEP 1: Checking Environment & Google Cloud Prerequisites")
    print("=" * 70)

    # 1. Check google-cloud-bigquery library
    try:
        from google.cloud import bigquery  # type: ignore
        print("  [OK] `google-cloud-bigquery` package is installed.")
    except ImportError:
        msg = (
            "ERROR: `google-cloud-bigquery` library is not installed in the active Python environment.\n"
            "To install it, run:\n"
            "    pip install google-cloud-bigquery db-dtypes pandas pyarrow\n"
        )
        return False, msg, None

    # 2. Check GCP Project
    settings = get_settings()
    project = project_override or os.environ.get("GOOGLE_CLOUD_PROJECT") or settings.google_cloud_project
    if not project or project in ("your-gcp-project-id", "a4i-fulton-2026"):
        # Attempt to infer project from default credentials
        try:
            temp_client = bigquery.Client()
            if temp_client.project:
                project = temp_client.project
        except Exception:
            pass

    if not project or project == "your-gcp-project-id":
        msg = (
            "ERROR: Google Cloud Project ID is not configured.\n"
            "Set GOOGLE_CLOUD_PROJECT in your environment or pass --project:\n"
            "    export GOOGLE_CLOUD_PROJECT='your-actual-gcp-project-id'\n"
        )
        return False, msg, None

    print(f"  [OK] Google Cloud Project: {project}")

    # 3. Check client authentication
    try:
        location = settings.bigquery_location or "US"
        token = access_token or os.environ.get("GCP_ACCESS_TOKEN")
        if token:
            from google.oauth2.credentials import Credentials  # type: ignore

            creds = Credentials(token=token.strip())
            client = bigquery.Client(project=project, location=location, credentials=creds)
            print(f"  [OK] BigQuery Client initialized via OAuth Access Token (location: {location}).")
        else:
            client = bigquery.Client(project=project, location=location)
            print(f"  [OK] BigQuery Client initialized successfully (location: {location}).")
        return True, project, client
    except Exception as exc:
        msg = (
            f"ERROR: Failed to initialize authenticated BigQuery client: {exc}\n\n"
            "Ensure you have valid Application Default Credentials (ADC) or a Service Account:\n"
            "    gcloud auth application-default login\n"
            "or pass an access token from Cloud Shell (`gcloud auth print-access-token`):\n"
            "    --access-token <TOKEN>\n"
        )
        return False, msg, None


def test_individual_views(client: Any, project: str, county_fips: str) -> Dict[str, Any]:
    """Directly queries all 9 views to verify table/view accessibility and row counts."""
    print("\n" + "=" * 70)
    print("STEP 2: Querying Individual Cloud BigQuery Views")
    print("=" * 70)

    from google.cloud import bigquery  # type: ignore

    results: Dict[str, Any] = {}

    # Query health views
    for view in HEALTH_VIEWS:
        table_ref = f"`{project}.a4i_health.{view}`"
        query = f"SELECT count(*) as cnt FROM {table_ref}"
        try:
            job = client.query(query)
            rows = list(job.result())
            cnt = rows[0]["cnt"] if rows else 0
            print(f"  [PASS] {table_ref:<55} -> {cnt:,} rows")
            results[f"a4i_health.{view}"] = {"status": "PASS", "rows": cnt}
        except Exception as exc:
            print(f"  [FAIL] {table_ref:<55} -> {exc}")
            results[f"a4i_health.{view}"] = {"status": "FAIL", "error": str(exc)}

    # Query transit views
    for view in MARTA_VIEWS:
        table_ref = f"`{project}.marta_gtfs.{view}`"
        query = f"SELECT count(*) as cnt FROM {table_ref}"
        try:
            job = client.query(query)
            rows = list(job.result())
            cnt = rows[0]["cnt"] if rows else 0
            print(f"  [PASS] {table_ref:<55} -> {cnt:,} rows")
            results[f"marta_gtfs.{view}"] = {"status": "PASS", "rows": cnt}
        except Exception as exc:
            print(f"  [WARN/OPTIONAL] {table_ref:<46} -> {exc}")
            results[f"marta_gtfs.{view}"] = {"status": "WARN/OPTIONAL", "error": str(exc)}

    return results


def test_agent_mcp_bridge(client: Any, project: str, county_fips: str) -> bool:
    """Tests the agent BigQueryMCPBridge executing parameterized MCP queries against the views."""
    print("\n" + "=" * 70)
    print("STEP 3: Testing Agent MCP Named Queries via BigQueryMCPBridge")
    print("=" * 70)

    bridge = BigQueryMCPBridge(
        bq_client=client,
        use_mock_data=False,
    )
    bridge.project_id = project

    all_passed = True

    # 1. Tract burden and access
    try:
        tracts = bridge.mcp_query_tract_burden_and_access(county_fips)
        assert_race_blind_planner_input(tracts)
        assert_no_pii_in_payload(tracts)
        print(f"  [PASS] mcp_query_tract_burden_and_access -> {len(tracts)} tracts (Race-blind & PII-clean)")
    except Exception as exc:
        print(f"  [FAIL] mcp_query_tract_burden_and_access -> {exc}")
        all_passed = False

    # 2. Care sites and shortages
    try:
        sites = bridge.mcp_query_care_sites_and_shortages(county_fips)
        assert_race_blind_planner_input(sites)
        assert_no_pii_in_payload(sites)
        print(
            f"  [PASS] mcp_query_care_sites_and_shortages -> care_sites: {sites.get('care_sites_count')}, "
            f"shortage_areas: {sites.get('shortage_areas_count')}, shortage_facilities: {sites.get('shortage_facilities_count')}"
        )
    except Exception as exc:
        print(f"  [FAIL] mcp_query_care_sites_and_shortages -> {exc}")
        all_passed = False

    # 3. Regional disease weekly
    try:
        disease = bridge.mcp_query_regional_disease_weekly(county_fips)
        assert_race_blind_planner_input(disease)
        assert_no_pii_in_payload(disease)
        print(
            f"  [PASS] mcp_query_regional_disease_weekly -> HSA: {disease.get('hsa_name')}, "
            f"week_end: {disease.get('latest_week_end')}"
        )
    except Exception as exc:
        print(f"  [FAIL] mcp_query_regional_disease_weekly -> {exc}")
        all_passed = False

    # 4. Air exposure tail
    try:
        air = bridge.mcp_query_air_exposure_tail(county_fips)
        assert_race_blind_planner_input(air)
        assert_no_pii_in_payload(air)
        print(f"  [PASS] mcp_query_air_exposure_tail -> {len(air)} tract air records")
    except Exception as exc:
        print(f"  [FAIL] mcp_query_air_exposure_tail -> {exc}")
        all_passed = False

    # 5. Full HealthEvidence assembly
    try:
        health_ev = bridge.fetch_health_evidence(county_fips)
        payload = health_ev.model_dump()
        assert_race_blind_planner_input(payload)
        assert_no_pii_in_payload(payload)
        print(f"  [PASS] Full HealthEvidence object assembled -> {len(health_ev.tracts)} tracts validated")
    except Exception as exc:
        print(f"  [FAIL] Full HealthEvidence assembly -> {exc}")
        all_passed = False

    # 6. Saturday transit & venues
    try:
        mobility_ev = bridge.mcp_query_saturday_transit_and_venues(county_fips)
        payload = mobility_ev.model_dump()
        assert_race_blind_planner_input(payload)
        assert_no_pii_in_payload(payload)
        print(
            f"  [PASS] mcp_query_saturday_transit_and_venues -> "
            f"marta_gtfs_available={mobility_ev.marta_gtfs_available}, "
            f"{len(mobility_ev.tract_mobility)} tract mobility records"
        )
    except Exception as exc:
        print(f"  [FAIL] mcp_query_saturday_transit_and_venues -> {exc}")
        all_passed = False

    return all_passed


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Live Cloud BigQuery Views for CareBridge AI Agents")
    parser.add_argument("--county-fips", default="13121", help="5-digit county FIPS (default: 13121 for Fulton)")
    parser.add_argument("--project", default=None, help="GCP project ID override")
    parser.add_argument("--access-token", default=None, help="OAuth2 access token from `gcloud auth print-access-token`")
    args = parser.parse_args()

    ok, project_or_msg, client = check_prerequisites(args.project, args.access_token)
    if not ok:
        print(f"\n{project_or_msg}")
        return 1

    project = project_or_msg
    view_results = test_individual_views(client, project, args.county_fips)
    mcp_ok = test_agent_mcp_bridge(client, project, args.county_fips)

    print("\n" + "=" * 70)
    print("VERIFICATION SUMMARY")
    print("=" * 70)
    all_health_ok = all(v.get("status") == "PASS" for k, v in view_results.items() if k.startswith("a4i_health."))
    if all_health_ok and mcp_ok:
        print("SUCCESS: All BigQuery views and agent MCP queries are verified and operational!")
        return 0
    else:
        print("WARNING: Some BigQuery views or queries encountered errors. Review logs above.")
        return 2


if __name__ == "__main__":
    sys.exit(main())
