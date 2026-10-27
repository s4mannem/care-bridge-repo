"""Data-plane parameter, schema, and race-blind boundary validators for BigQuery MCP queries."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List

from carebridge.contracts.evidence_models import CandidateHostVenue, MobilityEvidence, TractMobilityRecord
from carebridge.security.race_blind_guard import (
    assert_no_pii_in_payload,
    assert_race_blind_planner_input,
)

_COUNTY_FIPS_RE = re.compile(r"^\d{5}$")
_TRACT_GEOID_RE = re.compile(r"^\d{11}$")

MAX_BQ_BYTES_BILLED: int = 100_000_000  # 100 MB per query cap (OWASP LLM04 DoS prevention)


def validate_county_fips(county_fips: str) -> str:
    """Validates that `county_fips` is strictly a 5-digit numeric FIPS code.

    Raises:
        ValueError: If `county_fips` is not a 5-digit string (prevents SQL injection).
    """
    if not isinstance(county_fips, str):
        raise ValueError(f"Invalid county_fips type '{type(county_fips).__name__}': expected 5-digit string.")
    cleaned = county_fips.strip()
    if not _COUNTY_FIPS_RE.match(cleaned):
        raise ValueError(
            f"Invalid county_fips '{county_fips}': must be an exact 5-digit numeric FIPS code (e.g. '13121')."
        )
    return cleaned


def validate_evidence_payload(payload: Any) -> Any:
    """Asserts that an evidence query result contains zero demographic (SVI Theme 3/race) or PII fields."""
    assert_race_blind_planner_input(payload)
    assert_no_pii_in_payload(payload)
    return payload


def validate_tract_geoid_rows(rows: Iterable[Dict[str, Any]], county_fips: str) -> List[str]:
    """Checks that every row with a `geo_id` has an 11-digit string starting with `county_fips`."""
    validated_fips = validate_county_fips(county_fips)
    errors: List[str] = []
    seen = set()
    for idx, row in enumerate(rows):
        geoid = str(row.get("geo_id", ""))
        if not _TRACT_GEOID_RE.match(geoid):
            errors.append(f"Row {idx} has non-11-digit geo_id '{geoid}'.")
        elif not geoid.startswith(validated_fips):
            errors.append(f"Row {idx} geo_id '{geoid}' does not start with county_fips '{validated_fips}'.")
        if geoid in seen:
            errors.append(f"Duplicate geo_id '{geoid}' detected in query result.")
        seen.add(geoid)
    return errors


def enforce_unverified_host_venues(evidence: MobilityEvidence) -> MobilityEvidence:
    """Ensures every `CandidateHostVenue` in `MobilityEvidence` has `host_permission_verified=False`."""
    updated_tracts: List[TractMobilityRecord] = []
    for tm in evidence.tract_mobility:
        sanitized_venues: List[CandidateHostVenue] = [
            v.model_copy(update={"host_permission_verified": False})
            if v.host_permission_verified is not False
            else v
            for v in tm.candidate_venues
        ]
        updated_tracts.append(tm.model_copy(update={"candidate_venues": sanitized_venues}))
    return evidence.model_copy(update={"tract_mobility": updated_tracts})
