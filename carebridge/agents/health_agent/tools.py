"""MCP-backed evidence gathering tool for the CareBridge AI Health & Access Evidence Agent (Agent A)."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from carebridge.config import get_settings
from carebridge.contracts.evidence_models import (
    HealthEvidence,
    RegionalDiseaseSignal,
    SpatialGrain,
    TractHealthRecord,
)
from carebridge.contracts.state_keys import STATE_HEALTH_EVIDENCE, STATE_PLAN_REQUEST
from carebridge.mocks.fulton_fixtures import build_mock_health_evidence
from carebridge.security.race_blind_guard import (
    assert_no_pii_in_payload,
    assert_race_blind_planner_input,
)
from carebridge.telemetry.otel import record_structured_log, trace_span

_COUNTY_FIPS_RE = re.compile(r"^\d{5}$")

_DEFAULT_HSA_GRAIN_WARNING = (
    "NSSP ED visits are reported at the 4-county Health Service Area (HSA: Fulton, DeKalb, "
    "Clayton, Gwinnett) level, NEVER at the census tract or neighborhood level."
)

_FULTON_SHORTAGE_GAP_FLAG = (
    "shortage_areas_count=0 active in Fulton County (all 99 rows are Proposed For Withdrawal) "
    "despite 135 tracts having extra_km_if_uninsured > 0."
)


def _resolve_county_fips(county_fips: Optional[str], tool_context: Optional[Any]) -> str:
    """Extracts and validates 5-digit county_fips from arguments or tool_context.state."""
    resolved = county_fips
    if (not resolved or resolved == "13121") and tool_context is not None:
        state = getattr(tool_context, "state", None)
        if isinstance(state, dict):
            plan_req = state.get(STATE_PLAN_REQUEST)
            if isinstance(plan_req, dict) and plan_req.get("county_fips"):
                resolved = str(plan_req["county_fips"])
            elif hasattr(plan_req, "county_fips") and getattr(plan_req, "county_fips"):
                resolved = str(getattr(plan_req, "county_fips"))
    resolved = (resolved or "13121").strip()
    if not _COUNTY_FIPS_RE.match(resolved):
        raise ValueError(f"Invalid county_fips '{resolved}': must be a 5-digit FIPS code.")
    return resolved


def _normalize_tract_record(tract: TractHealthRecord) -> TractHealthRecord:
    """Enforces derived metrics: pct_checkup_gap = 100 - pct_checkup, uninsured gap, and distance gap."""
    updates: Dict[str, Any] = {}
    if tract.pct_checkup is not None and tract.pct_checkup_gap is None:
        updates["pct_checkup_gap"] = round(100.0 - float(tract.pct_checkup), 2)
    elif tract.pct_checkup is not None and tract.pct_checkup_gap is not None:
        expected_gap = round(100.0 - float(tract.pct_checkup), 2)
        if abs(float(tract.pct_checkup_gap) - expected_gap) > 0.05:
            updates["pct_checkup_gap"] = expected_gap

    if (
        tract.pct_uninsured_18_64 is not None
        and tract.pct_uninsured_all_ages is not None
        and tract.uninsured_age_structure_gap is None
    ):
        updates["uninsured_age_structure_gap"] = round(
            float(tract.pct_uninsured_18_64) - float(tract.pct_uninsured_all_ages), 2
        )

    if (
        tract.km_to_safety_net is not None
        and tract.km_to_any_care is not None
        and tract.extra_km_if_uninsured is None
    ):
        updates["extra_km_if_uninsured"] = round(
            float(tract.km_to_safety_net) - float(tract.km_to_any_care), 2
        )

    if updates:
        return tract.model_copy(update=updates)
    return tract


def _normalize_health_evidence(evidence: HealthEvidence) -> HealthEvidence:
    """Applies strict scientific grain, checkup inversion, and shortage nuance rules to HealthEvidence."""
    normalized_tracts = [_normalize_tract_record(t) for t in evidence.tracts]

    reg = evidence.regional_disease
    reg_updates: Dict[str, Any] = {}
    if reg.spatial_grain != SpatialGrain.MULTI_COUNTY_HSA:
        reg_updates["spatial_grain"] = SpatialGrain.MULTI_COUNTY_HSA
    if not reg.grain_warning:
        reg_updates["grain_warning"] = _DEFAULT_HSA_GRAIN_WARNING
    if (
        reg.percent_visits_covid is None
        and reg.percent_visits_influenza is None
        and reg.percent_visits_rsv is None
        and not reg.data_unavailable
    ):
        reg_updates["data_unavailable"] = True
    normalized_reg = reg.model_copy(update=reg_updates) if reg_updates else reg

    missingness_flags = list(evidence.missingness_flags)
    if (
        evidence.county_fips == "13121"
        and evidence.shortage_areas_count == 0
        and not any("shortage_areas_count=0" in f for f in missingness_flags)
    ):
        missingness_flags.append(_FULTON_SHORTAGE_GAP_FLAG)

    if normalized_reg.data_unavailable and not any(
        "data_unavailable=True" in f for f in missingness_flags
    ):
        missingness_flags.append(
            "NSSP regional_disease values are NULL -> data_unavailable=True ('we cannot tell', never 'no increase')."
        )

    updated = evidence.model_copy(
        update={
            "tracts": normalized_tracts,
            "regional_disease": normalized_reg,
            "missingness_flags": missingness_flags,
        }
    )
    return HealthEvidence.model_validate(updated.model_dump())


def _fetch_from_mcp_client_or_fallback(
    county_fips: str,
    mcp_client: Optional[Any] = None,
) -> HealthEvidence:
    """Queries BigQuery MCP named tools if configured/injected, with fallback to Fulton fixtures."""
    settings = get_settings()
    client = mcp_client
    if client is None and not settings.use_mock_data:
        try:
            from carebridge.data_plane import bq_mcp_client as bq_mod  # type: ignore

            if hasattr(bq_mod, "get_bigquery_mcp_bridge"):
                client = bq_mod.get_bigquery_mcp_bridge()
            elif hasattr(bq_mod, "BigQueryMCPBridge"):
                client = bq_mod.BigQueryMCPBridge()
            else:
                client = bq_mod
        except ImportError:
            client = None

    if client is not None:
        # Check if the client exposes a unified helper or the 4 named MCP queries from Plan 01/02
        if hasattr(client, "fetch_health_evidence"):
            raw = client.fetch_health_evidence(county_fips=county_fips)
            return HealthEvidence.model_validate(raw)

        has_named_queries = all(
            hasattr(client, fn)
            for fn in (
                "mcp_query_tract_burden_and_access",
                "mcp_query_care_sites_and_shortages",
                "mcp_query_regional_disease_weekly",
                "mcp_query_air_exposure_tail",
            )
        )
        if has_named_queries:
            tracts_rows = client.mcp_query_tract_burden_and_access(county_fips)
            sites_summary = client.mcp_query_care_sites_and_shortages(county_fips)
            disease_row = client.mcp_query_regional_disease_weekly(county_fips)
            air_rows = client.mcp_query_air_exposure_tail(county_fips)

            air_by_geoid: Dict[str, Dict[str, Any]] = {
                str(r["geo_id"]): r for r in (air_rows or []) if isinstance(r, dict) and "geo_id" in r
            }
            merged_tracts: List[TractHealthRecord] = []
            for row in tracts_rows or []:
                row_dict = dict(row) if isinstance(row, dict) else row.model_dump()
                assert_race_blind_planner_input(row_dict)
                assert_no_pii_in_payload(row_dict)
                air_info = air_by_geoid.get(str(row_dict.get("geo_id")), {})
                if "pm25_days_over_20" in air_info and row_dict.get("pm25_days_over_20") is None:
                    row_dict["pm25_days_over_20"] = air_info["pm25_days_over_20"]
                if "mean_pm25_12km_caveat" in air_info and row_dict.get("mean_pm25_12km_caveat") is None:
                    row_dict["mean_pm25_12km_caveat"] = air_info["mean_pm25_12km_caveat"]
                merged_tracts.append(TractHealthRecord.model_validate(row_dict))

            regional_disease = (
                disease_row
                if isinstance(disease_row, RegionalDiseaseSignal)
                else RegionalDiseaseSignal.model_validate(disease_row)
            )
            sites_dict = sites_summary if isinstance(sites_summary, dict) else {}
            return HealthEvidence(
                county_fips=county_fips,
                county_name=str(sites_dict.get("county_name", "Fulton")),
                tracts=merged_tracts,
                care_sites_count=int(sites_dict.get("care_sites_count", 85)),
                safety_net_sites_count=int(sites_dict.get("safety_net_sites_count", 41)),
                shortage_areas_count=int(sites_dict.get("shortage_areas_count", 0)),
                shortage_facilities_count=int(sites_dict.get("shortage_facilities_count", 6)),
                max_hpsa_score=sites_dict.get("max_hpsa_score", 19.0),
                regional_disease=regional_disease,
                source_lineage=list(
                    sites_dict.get(
                        "source_lineage",
                        [
                            "a4i_health.v_burden_tracts (CDC PLACES 2025 + CDC/ATSDR SVI 2022, race-blind columns only)",
                            "a4i_health.v_tract_access (straight-line upper-bound distances to federal sites)",
                            "a4i_health.v_care_sites & v_care_sites_state (HRSA Health Centers + CMS POS, TOT_OPER_HR_PER_WEEK)",
                            "a4i_health.v_shortage_areas (0 active in Fulton; 99 Proposed For Withdrawal) & v_shortage_facilities (6)",
                            "a4i_health.v_exposure_tracts (EPA 12km grid tail days > 20 ug/m3)",
                            "a4i_health.v_disease_weekly (CDC NSSP 4-county HSA respiratory ED trends)",
                        ],
                    )
                ),
                missingness_flags=list(sites_dict.get("missingness_flags", [])),
            )

    return build_mock_health_evidence(county_fips=county_fips)


def fetch_county_health_evidence(
    county_fips: str = "13121",
    tool_context: Optional[Any] = None,
    mcp_client: Optional[Any] = None,
) -> Dict[str, Any]:
    """Fetches, validates, and stores race-blind `HealthEvidence` for `county_fips`.

    Args:
        county_fips: 5-digit county FIPS code (default: `"13121"` for Fulton County, GA).
        tool_context: Optional ADK `ToolContext` whose `.state["health_evidence"]` will be populated.
        mcp_client: Optional BigQuery MCP bridge override for testing named MCP query dispatch.

    Returns:
        JSON-serializable dict matching `HealthEvidence` schema.
    """
    resolved_fips = _resolve_county_fips(county_fips, tool_context)

    with trace_span("agent.health_access.fetch_evidence", county_fips=resolved_fips) as span:
        raw_evidence = _fetch_from_mcp_client_or_fallback(
            county_fips=resolved_fips,
            mcp_client=mcp_client,
        )
        validated_evidence = _normalize_health_evidence(raw_evidence)
        payload = validated_evidence.model_dump()

        # Enforce strict race-blind & PII-free boundary before returning or persisting to session.state
        assert_race_blind_planner_input(payload)
        assert_no_pii_in_payload(payload)

        span.set_attribute("tracts_loaded", len(validated_evidence.tracts))
        span.set_attribute("shortage_areas_count", validated_evidence.shortage_areas_count)
        span.set_attribute("shortage_facilities_count", validated_evidence.shortage_facilities_count)
        span.set_attribute("hsa_data_unavailable", validated_evidence.regional_disease.data_unavailable)

        record_structured_log(
            component="health_access_agent",
            event_type="fetch_county_health_evidence",
            county_fips=resolved_fips,
            tracts_loaded=len(validated_evidence.tracts),
            shortage_areas_count=validated_evidence.shortage_areas_count,
            shortage_facilities_count=validated_evidence.shortage_facilities_count,
            hsa_data_unavailable=validated_evidence.regional_disease.data_unavailable,
        )

        if tool_context is not None:
            state = getattr(tool_context, "state", None)
            if isinstance(state, dict):
                state[STATE_HEALTH_EVIDENCE] = payload

        return payload
