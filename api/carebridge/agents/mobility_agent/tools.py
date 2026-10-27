"""MCP-backed mobility & community venue tool for the CareBridge AI Transit & Community Agent (Agent B)."""

from __future__ import annotations

import inspect
import re
from typing import Any, Dict, List, Optional

from carebridge.config import get_settings
from carebridge.contracts.evidence_models import (
    CandidateHostVenue,
    MobilityEvidence,
    TractMobilityRecord,
)
from carebridge.contracts.state_keys import STATE_MOBILITY_EVIDENCE, STATE_PLAN_REQUEST
from carebridge.mocks.fulton_fixtures import build_mock_mobility_evidence
from carebridge.security.race_blind_guard import (
    PolicyViolationError,
    assert_no_pii_in_payload,
    assert_race_blind_planner_input,
)
from carebridge.telemetry.otel import record_structured_log, trace_span

_COUNTY_FIPS_RE = re.compile(r"^\d{5}$")

MANDATORY_STOP_PROXIMITY_CAVEAT = (
    "A nearby Saturday bus stop measures stop presence, not door-to-door clinic journey time."
)
OPTIONAL_UNAVAILABLE_CAVEAT = (
    "Optional MARTA GTFS, USDA Food Access, and IMLS library venue views disabled or unavailable; using tract centroids."
)
CC_BY_NC_TRANSIT_CAVEAT = (
    "Access Across America transit travel-time matrices excluded due to CC BY-NC license boundary."
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


def _resolve_include_optional(
    include_optional_datasets: bool,
    tool_context: Optional[Any],
) -> bool:
    """Determines whether optional datasets should be queried based on args and session.state."""
    if not include_optional_datasets:
        return False
    if tool_context is not None:
        state = getattr(tool_context, "state", None)
        if isinstance(state, dict):
            plan_req = state.get(STATE_PLAN_REQUEST)
            if isinstance(plan_req, dict) and "include_optional_datasets" in plan_req:
                return bool(plan_req["include_optional_datasets"])
            if hasattr(plan_req, "include_optional_datasets"):
                return bool(getattr(plan_req, "include_optional_datasets"))
    return True


def _sanitize_venue(venue: CandidateHostVenue) -> CandidateHostVenue:
    """Enforces anti-hallucination rule: host_permission_verified is ALWAYS False."""
    if venue.host_permission_verified is not False:
        return venue.model_copy(update={"host_permission_verified": False})
    return venue


def _normalize_mobility_evidence(evidence: MobilityEvidence) -> MobilityEvidence:
    """Enforces host_permission_verified=False and mandatory stop-proximity caveats."""
    sanitized_tracts: List[TractMobilityRecord] = []
    for tm in evidence.tract_mobility:
        venues = [_sanitize_venue(v) for v in tm.candidate_venues]
        sanitized_tracts.append(tm.model_copy(update={"candidate_venues": venues}))

    caveats = list(evidence.caveats or [])
    if MANDATORY_STOP_PROXIMITY_CAVEAT not in caveats:
        caveats.append(MANDATORY_STOP_PROXIMITY_CAVEAT)

    any_available = (
        evidence.marta_gtfs_available
        or evidence.usda_food_access_available
        or evidence.imls_venues_available
    )
    if not any_available:
        if not any("disabled or unavailable" in c or "unavailable" in c.lower() for c in caveats):
            caveats.insert(0, OPTIONAL_UNAVAILABLE_CAVEAT)
    else:
        if CC_BY_NC_TRANSIT_CAVEAT not in caveats:
            caveats.append(CC_BY_NC_TRANSIT_CAVEAT)

    updated = evidence.model_copy(
        update={
            "tract_mobility": sanitized_tracts,
            "caveats": caveats,
        }
    )
    return MobilityEvidence.model_validate(updated.model_dump())


def _coerce_raw_mcp_result(county_fips: str, raw: Any) -> MobilityEvidence:
    """Coerces a raw MCP client return value (MobilityEvidence, dict, or row list) into MobilityEvidence."""
    if isinstance(raw, MobilityEvidence):
        return raw
    if isinstance(raw, dict):
        assert_race_blind_planner_input(raw)
        assert_no_pii_in_payload(raw)
        if "county_fips" not in raw:
            raw = {"county_fips": county_fips, **raw}
        return MobilityEvidence.model_validate(raw)
    if isinstance(raw, list):
        assert_race_blind_planner_input(raw)
        assert_no_pii_in_payload(raw)
        records: List[TractMobilityRecord] = []
        has_venues = False
        has_usda = False
        for item in raw:
            item_dict = dict(item) if isinstance(item, dict) else item.model_dump()
            rec = TractMobilityRecord.model_validate(item_dict)
            if rec.candidate_venues:
                has_venues = True
            if rec.usda_low_income_low_access is not None:
                has_usda = True
            records.append(rec)
        return MobilityEvidence(
            county_fips=county_fips,
            marta_gtfs_available=len(records) > 0,
            usda_food_access_available=has_usda,
            imls_venues_available=has_venues,
            tract_mobility=records,
            caveats=[
                MANDATORY_STOP_PROXIMITY_CAVEAT,
                CC_BY_NC_TRANSIT_CAVEAT,
            ],
        )
    raise ValueError(f"Unsupported MCP mobility return type: {type(raw).__name__}")


def _fetch_from_mcp_or_fallback(
    county_fips: str,
    include_optional_datasets: bool,
    mcp_client: Optional[Any] = None,
) -> MobilityEvidence:
    """Queries BigQuery MCP mobility views with graceful degradation on NotFound or disabled flags."""
    if not include_optional_datasets:
        return build_mock_mobility_evidence(county_fips=county_fips, include_optional=False)

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
        try:
            if callable(client) and not hasattr(client, "mcp_query_saturday_transit_and_venues"):
                raw = client(county_fips)
                return _coerce_raw_mcp_result(county_fips, raw)

            if hasattr(client, "mcp_query_saturday_transit_and_venues"):
                fn = getattr(client, "mcp_query_saturday_transit_and_venues")
                sig = inspect.signature(fn)
                if "include_optional_datasets" in sig.parameters:
                    raw = fn(
                        county_fips=county_fips,
                        include_optional_datasets=include_optional_datasets,
                    )
                else:
                    raw = fn(county_fips)
                return _coerce_raw_mcp_result(county_fips, raw)

            if hasattr(client, "fetch_mobility_evidence"):
                fn = getattr(client, "fetch_mobility_evidence")
                sig = inspect.signature(fn)
                if "include_optional_datasets" in sig.parameters:
                    raw = fn(
                        county_fips=county_fips,
                        include_optional_datasets=include_optional_datasets,
                    )
                else:
                    raw = fn(county_fips)
                return _coerce_raw_mcp_result(county_fips, raw)
        except PolicyViolationError:
            # Never swallow security or race-blind policy violations!
            raise
        except Exception as exc:
            # Graceful degradation when BigQuery raises NotFound or optional views are absent
            record_structured_log(
                component="transit_community_agent",
                event_type="optional_dataset_degraded",
                severity="WARNING",
                county_fips=county_fips,
                error_type=type(exc).__name__,
                error_detail=str(exc),
            )
            degraded = build_mock_mobility_evidence(county_fips=county_fips, include_optional=False)
            degraded_caveats = list(degraded.caveats)
            degraded_note = (
                f"Gracefully degraded optional mobility datasets after {type(exc).__name__}: {exc}"
            )
            if degraded_note not in degraded_caveats:
                degraded_caveats.insert(0, degraded_note)
            return degraded.model_copy(update={"caveats": degraded_caveats})

    return build_mock_mobility_evidence(county_fips=county_fips, include_optional=True)


def fetch_county_mobility_evidence(
    county_fips: str = "13121",
    include_optional_datasets: bool = True,
    tool_context: Optional[Any] = None,
    mcp_client: Optional[Any] = None,
) -> Dict[str, Any]:
    """Queries MARTA Saturday GTFS views, optional USDA food access, and IMLS candidate host venues.

    Gracefully degrades when `include_optional_datasets=False` or when BigQuery raises `NotFound`
    on optional views, setting availability flags to `False` and attaching explicit caveats.
    Always enforces `host_permission_verified=False` on every `CandidateHostVenue`.

    Args:
        county_fips: 5-digit county FIPS code (default: `"13121"` for Fulton County, GA).
        include_optional_datasets: Whether optional MARTA/USDA/IMLS enrichments are enabled.
        tool_context: Optional ADK `ToolContext` whose `.state["mobility_evidence"]` is populated.
        mcp_client: Optional BigQuery MCP bridge or callable override for testing.

    Returns:
        Validated dictionary matching the `MobilityEvidence` Pydantic schema.
    """
    resolved_fips = _resolve_county_fips(county_fips, tool_context)
    resolved_optional = _resolve_include_optional(include_optional_datasets, tool_context)

    with trace_span(
        "agent.transit_community.fetch_mobility",
        county_fips=resolved_fips,
        include_optional_datasets=resolved_optional,
    ) as span:
        raw_evidence = _fetch_from_mcp_or_fallback(
            county_fips=resolved_fips,
            include_optional_datasets=resolved_optional,
            mcp_client=mcp_client,
        )
        validated_evidence = _normalize_mobility_evidence(raw_evidence)
        payload = validated_evidence.model_dump()

        # Enforce strict race-blind & PII-free boundary before returning or persisting to session.state
        assert_race_blind_planner_input(payload)
        assert_no_pii_in_payload(payload)

        candidate_venues_count = sum(
            len(tm.candidate_venues) for tm in validated_evidence.tract_mobility
        )
        span.set_attribute("marta_gtfs_available", validated_evidence.marta_gtfs_available)
        span.set_attribute("imls_venues_available", validated_evidence.imls_venues_available)
        span.set_attribute(
            "usda_food_access_available", validated_evidence.usda_food_access_available
        )
        span.set_attribute("candidate_venues_count", candidate_venues_count)

        record_structured_log(
            component="transit_community_agent",
            event_type="fetch_county_mobility_evidence",
            county_fips=resolved_fips,
            marta_gtfs_available=validated_evidence.marta_gtfs_available,
            imls_venues_available=validated_evidence.imls_venues_available,
            usda_food_access_available=validated_evidence.usda_food_access_available,
            candidate_venues_count=candidate_venues_count,
        )

        if tool_context is not None:
            state = getattr(tool_context, "state", None)
            if isinstance(state, dict):
                state[STATE_MOBILITY_EVIDENCE] = payload

        return payload
