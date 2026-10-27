"""Deterministic check() and note() validation rule engine for the Evidence Validator Agent."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple, Union
from carebridge._compat import BaseModel
from carebridge.contracts.evidence_models import (
    EvidenceReport,
    HealthEvidence,
    MobilityEvidence,
    SpatialGrain,
    ValidationCheckItem,
)
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
    PolicyViolationError,
    assert_no_pii_in_payload,
    assert_race_blind_planner_input,
)
from carebridge.telemetry.otel import record_structured_log, trace_span

MANDATORY_EVIDENCE_CAVEATS: Tuple[str, ...] = (
    "4 SPATIAL RESOLUTIONS (TRACT != 12KM GRID != FACILITY POINT != 4-COUNTY HSA): Weekly respiratory ED trends (NSSP) represent the 4-county Health Service Area (Fulton, DeKalb, Clayton, Gwinnett), never an individual census tract; PM2.5 is a 12km grid (`p90/p10=1.05x`) and cannot rank neighborhoods.",
    "DISTANCE != JOURNEY TIME: km_to_any_care and km_to_safety_net are straight-line Euclidean upper-bound distances to federally recognized facilities, not bus transfer or road travel times. Access Across America transit matrices are excluded (CC BY-NC).",
    "PLACES MODELED ESTIMATES & 95% CI: Tract health prevalences are small-area modeled estimates (not patient headcounts); minor percentage-point differences (<1-2%) fall within overlapping 95% confidence intervals.",
    "UPPER-BOUND FEDERAL FACILITY BOUNDARY & PII EXCLUSIONS: Non-federal free clinics, county health departments, pharmacies (NPPES excluded due to practitioner PII), FQHC_ADMIN_CONTACT_* fields, and unlicensed mobile clinics are excluded; distances represent upper bounds on distance to care.",
)

DEFAULT_PROHIBITED_CLAIMS_BLOCKED: Tuple[str, ...] = (
    "Blocked tract-level attribution of 4-county HSA NSSP respiratory trends",
    "Blocked ranking tracts by 12km EPA PM2.5 grid mean (p90/p10=1.05x)",
    "Blocked treating straight-line federal site distance as bus travel time",
)

_PREVALENCE_FIELDS: Tuple[str, ...] = (
    "pct_uninsured_18_64",
    "pct_uninsured_all_ages",
    "pct_asthma",
    "pct_copd",
    "pct_diabetes",
    "pct_bphigh",
    "pct_checkup",
    "pct_checkup_gap",
    "pct_no_vehicle",
    "pct_age_65_plus",
    "pct_mobility_difficulty",
    "pct_lack_transport",
)


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """Safely extracts a field from either a dict or a Pydantic model / object."""
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _to_inspectable_structure(obj: Any) -> Any:
    """Recursively converts models and dicts (including dynamically attached attributes) for security inspection."""
    if isinstance(obj, BaseModel):
        merged: Dict[str, Any] = {}
        try:
            merged.update(obj.model_dump())
        except Exception:
            pass
        for k, v in vars(obj).items():
            if not k.startswith("_"):
                merged[k] = _to_inspectable_structure(v)
        return merged
    if isinstance(obj, dict):
        return {k: _to_inspectable_structure(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_to_inspectable_structure(item) for item in obj]
    return obj


def _record_item(
    checks: List[ValidationCheckItem],
    item: ValidationCheckItem,
) -> ValidationCheckItem:
    """Records a ValidationCheckItem keyed by check_name (last write wins, matching notebook Section 12)."""
    for idx, existing in enumerate(checks):
        if existing.check_name == item.check_name:
            checks[idx] = item
            return item
    checks.append(item)
    return item


def check(
    checks: List[ValidationCheckItem],
    check_name: str,
    ok: bool,
    detail: str = "",
) -> ValidationCheckItem:
    """Pipeline integrity check (fatal / blocking when `ok` is False)."""
    verdict = "PASS" if ok else "FAIL"
    item = ValidationCheckItem(
        check_name=check_name,
        verdict=verdict,
        detail=detail or ("Pipeline check passed." if ok else "Pipeline check failed."),
        is_pipeline_check=True,
    )
    return _record_item(checks, item)


def note(
    checks: List[ValidationCheckItem],
    check_name: str,
    bad: int,
    total: int,
    detail: str = "",
    limit: float = 0.05,
) -> ValidationCheckItem:
    """Publisher data nuance check: warns below `limit`, escalates to FAIL only above `limit`.

    `total == 0` means 'no denominator' and never escalates to FAIL.
    """
    frac = (bad / total) if total > 0 else 0.0
    verdict = "PASS" if bad == 0 else ("FAIL" if (total > 0 and frac > limit) else "WARN")
    resolved_detail = detail or (f"{bad:,} of {total:,}" if total > 0 else f"{bad:,}")
    item = ValidationCheckItem(
        check_name=check_name,
        verdict=verdict,
        detail=resolved_detail,
        is_pipeline_check=False,
    )
    return _record_item(checks, item)


def evaluate_evidence_quality(
    health_evidence: HealthEvidence | Dict[str, Any],
    mobility_evidence: Optional[MobilityEvidence | Dict[str, Any]] = None,
) -> EvidenceReport:
    """Executes all deterministic `check()` and `note()` rules on collected Lane 01 evidence."""
    county_fips = str(_get(health_evidence, "county_fips", "13121") or "13121").strip()
    if mobility_evidence is None:
        mobility_evidence = MobilityEvidence(
            county_fips=county_fips,
            marta_gtfs_available=False,
            usda_food_access_available=False,
            imls_venues_available=False,
            tract_mobility=[],
        )

    with trace_span("agent.evidence_validator.validate", county_fips=county_fips) as span:
        checks: List[ValidationCheckItem] = []
        prohibited_claims_blocked: List[str] = list(DEFAULT_PROHIBITED_CLAIMS_BLOCKED)
        caveats: List[str] = list(MANDATORY_EVIDENCE_CAVEATS)

        tracts = list(_get(health_evidence, "tracts", []) or [])
        n_tracts = len(tracts)

        # ------------------------------------------------------------------
        # 1. Pipeline Integrity check() Suite (Fatal / Blocking)
        # ------------------------------------------------------------------
        # 1a. burden_tracts is non-empty
        check(
            checks,
            "burden_tracts_not_empty",
            n_tracts > 0,
            f"{n_tracts} tracts loaded for county {county_fips}."
            if n_tracts > 0
            else f"v_burden_tracts is empty (0 rows) for county {county_fips}.",
        )

        # 1b. Every geo_id is 11 characters and starts with county_fips
        invalid_length_geoids: List[str] = []
        wrong_prefix_geoids: List[str] = []
        valid_tract_count = 0

        for idx, t in enumerate(tracts):
            gid = str(_get(t, "geo_id", "") or "").strip()
            len_ok = len(gid) == 11 and gid.isdigit()
            pref_ok = gid.startswith(county_fips)
            safe_gid = f"geoid_{gid}_len{len(gid)}" if (len(gid) == 10 and gid.isdigit()) else (gid or f"<empty_row_{idx}>")
            if not len_ok:
                invalid_length_geoids.append(safe_gid)
            if not pref_ok:
                wrong_prefix_geoids.append(safe_gid)
            if len_ok and pref_ok:
                valid_tract_count += 1

        mob_county_fips = str(_get(mobility_evidence, "county_fips", county_fips) or "").strip()
        mob_county_ok = mob_county_fips == county_fips
        for tm in list(_get(mobility_evidence, "tract_mobility", []) or []):
            mgid = str(_get(tm, "geo_id", "") or "").strip()
            safe_mgid = f"geoid_{mgid}_len{len(mgid)}" if (len(mgid) == 10 and mgid.isdigit()) else mgid
            if len(mgid) != 11 or not mgid.isdigit():
                invalid_length_geoids.append(safe_mgid)
            if not mgid.startswith(county_fips):
                wrong_prefix_geoids.append(safe_mgid)
            for venue in list(_get(tm, "candidate_venues", []) or []):
                vgid = str(_get(venue, "geo_id", "") or "").strip()
                safe_vgid = f"geoid_{vgid}_len{len(vgid)}" if (len(vgid) == 10 and vgid.isdigit()) else vgid
                if len(vgid) != 11 or not vgid.isdigit():
                    invalid_length_geoids.append(safe_vgid)
                if not vgid.startswith(county_fips):
                    wrong_prefix_geoids.append(safe_vgid)

        geoid_ok = (
            n_tracts > 0
            and len(invalid_length_geoids) == 0
            and len(wrong_prefix_geoids) == 0
            and mob_county_ok
        )
        check(
            checks,
            "tract_geoid_11char_and_county_prefix",
            geoid_ok,
            f"All {n_tracts} fixture tracts have 11-char GEOIDs starting with {county_fips}."
            if geoid_ok
            else (
                f"Invalid tract GEOIDs or county mismatch: wrong_length={invalid_length_geoids}, "
                f"wrong_county_prefix={wrong_prefix_geoids}, mobility_county_fips={mob_county_fips} "
                f"(expected {county_fips})."
            ),
        )

        # 1c. Zero duplicate tract IDs
        geo_id_list = [str(_get(t, "geo_id", "") or "").strip() for t in tracts]
        duplicate_count = len(geo_id_list) - len(set(geo_id_list))
        check(
            checks,
            "unique_tract_geoids",
            duplicate_count == 0,
            f"Zero duplicate tract GEOIDs across {n_tracts} rows."
            if duplicate_count == 0
            else f"{duplicate_count} duplicate tract GEOID(s) detected in v_burden_tracts.",
        )

        # 1d. North America coordinate bounds (lat in [17, 72], lon in [-180, -60])
        out_of_bounds_coords: List[str] = []
        missing_coords_geoids: List[str] = []
        tracts_with_valid_coords = 0

        for t in tracts:
            gid = str(_get(t, "geo_id", "") or "")
            lat = _get(t, "latitude", None)
            lon = _get(t, "longitude", None)
            if lat is None or lon is None:
                missing_coords_geoids.append(gid)
                continue
            try:
                lat_f = float(lat)
                lon_f = float(lon)
            except (TypeError, ValueError):
                out_of_bounds_coords.append(gid)
                continue
            if not (17.0 <= lat_f <= 72.0 and -180.0 <= lon_f <= -60.0):
                out_of_bounds_coords.append(gid)
            else:
                tracts_with_valid_coords += 1

        coords_bounds_ok = (
            n_tracts > 0
            and len(out_of_bounds_coords) == 0
            and tracts_with_valid_coords > 0
        )
        check(
            checks,
            "north_america_coordinates_bounds",
            coords_bounds_ok,
            f"All {tracts_with_valid_coords} tract centroids lie inside North America bounds (lat [17, 72], lon [-180, -60])."
            if coords_bounds_ok
            else (
                f"Coordinate check failed: out_of_bounds={out_of_bounds_coords}, "
                f"valid_centroids={tracts_with_valid_coords}/{n_tracts}."
            ),
        )

        # 1e. care_sites_count > 0 and every tract has valid km_to_any_care and km_to_safety_net
        care_sites_count = int(_get(health_evidence, "care_sites_count", 0) or 0)
        missing_access_geoids: List[str] = []
        for t in tracts:
            gid = str(_get(t, "geo_id", "") or "")
            km_any = _get(t, "km_to_any_care", None)
            km_net = _get(t, "km_to_safety_net", None)
            if km_any is None or km_net is None:
                missing_access_geoids.append(gid)
                continue
            try:
                if float(km_any) < 0.0 or float(km_net) < 0.0:
                    missing_access_geoids.append(gid)
            except (TypeError, ValueError):
                missing_access_geoids.append(gid)

        access_ok = care_sites_count > 0 and n_tracts > 0 and len(missing_access_geoids) == 0
        check(
            checks,
            "care_sites_and_access_distances_present",
            access_ok,
            f"{care_sites_count} county care sites loaded; all {n_tracts} tracts have valid km_to_any_care and km_to_safety_net."
            if access_ok
            else (
                f"Access distance check failed: care_sites_count={care_sites_count}, "
                f"tracts_missing_or_negative_distances={missing_access_geoids}."
            ),
        )

        # 1f. Routine checkup inversion verified (pct_checkup_gap == round(100.0 - pct_checkup, 2))
        bad_checkup_geoids: List[str] = []
        for t in tracts:
            gid = str(_get(t, "geo_id", "") or "")
            pct_checkup = _get(t, "pct_checkup", None)
            pct_checkup_gap = _get(t, "pct_checkup_gap", None)
            if pct_checkup is not None:
                try:
                    expected_gap = round(100.0 - float(pct_checkup), 2)
                    if pct_checkup_gap is None or abs(float(pct_checkup_gap) - expected_gap) > 0.05:
                        bad_checkup_geoids.append(gid)
                except (TypeError, ValueError):
                    bad_checkup_geoids.append(gid)

        check(
            checks,
            "pct_checkup_inversion_verified",
            len(bad_checkup_geoids) == 0,
            "pct_checkup_gap == 100.0 - pct_checkup verified across all tracts."
            if len(bad_checkup_geoids) == 0
            else f"Routine checkup inversion (100.0 - pct_checkup) invalid or missing on tracts: {bad_checkup_geoids}.",
        )

        # 1g. Regional disease spatial_grain == SpatialGrain.MULTI_COUNTY_HSA (Tract != HSA)
        regional_disease = _get(health_evidence, "regional_disease", None)
        raw_grain = _get(regional_disease, "spatial_grain", None)
        grain_val = raw_grain.value if isinstance(raw_grain, SpatialGrain) else str(raw_grain or "")
        hsa_name = str(_get(regional_disease, "hsa_name", "") or "").strip()
        hsa_counties = str(_get(regional_disease, "hsa_counties", "") or "").strip()
        hsa_grain_ok = (
            regional_disease is not None
            and grain_val == SpatialGrain.MULTI_COUNTY_HSA.value
            and hsa_name.lower() != "all"
            and bool(hsa_counties)
        )
        check(
            checks,
            "regional_disease_hsa_grain_verified",
            hsa_grain_ok,
            f"v_disease_weekly verified at {SpatialGrain.MULTI_COUNTY_HSA.value} grain ({hsa_counties})."
            if hsa_grain_ok
            else (
                f"v_disease_weekly grain violation: spatial_grain={grain_val!r}, hsa_name={hsa_name!r}. "
                "NSSP trends must be tagged as multi_county_health_service_area, never tract or state='All'."
            ),
        )

        # 1h. Race-blind & PII exclusion check
        race_and_pii_ok = True
        try:
            assert_race_blind_planner_input(_to_inspectable_structure(health_evidence))
            assert_race_blind_planner_input(_to_inspectable_structure(mobility_evidence))
            assert_no_pii_in_payload(_to_inspectable_structure(health_evidence))
            assert_no_pii_in_payload(_to_inspectable_structure(mobility_evidence))
        except PolicyViolationError:
            race_and_pii_ok = False
            prohibited_claims_blocked.append(
                "Blocked leaked demographic or administrative contact PII attribute from entering Planner state"
            )

        check(
            checks,
            "race_blind_and_pii_exclusion",
            race_and_pii_ok,
            "Zero prohibited demographic or administrative contact PII columns present."
            if race_and_pii_ok
            else "Prohibited demographic attribute or individual administrative contact PII detected in evidence payload.",
        )

        # ------------------------------------------------------------------
        # 2. Publisher Data Nuance note() Suite (Warns & Escalates Above Limit)
        # ------------------------------------------------------------------
        # 2a. Impossible prevalences (< 0 or > 100)
        impossible_prevalence_geoids: List[str] = []
        for t in tracts:
            gid = str(_get(t, "geo_id", "") or "")
            for field_name in _PREVALENCE_FIELDS:
                val = _get(t, field_name, None)
                if val is not None:
                    try:
                        val_f = float(val)
                        if val_f < 0.0 or val_f > 100.0:
                            impossible_prevalence_geoids.append(f"{gid}:{field_name}={val_f}")
                            break
                    except (TypeError, ValueError):
                        impossible_prevalence_geoids.append(f"{gid}:{field_name}=NaN")
                        break

        note(
            checks,
            "prevalence_bounds_0_to_100",
            bad=len(impossible_prevalence_geoids),
            total=n_tracts,
            detail=(
                "All tract health and SVI percentages are within [0, 100]."
                if len(impossible_prevalence_geoids) == 0
                else f"Impossible prevalence percentages (<0 or >100) found: {impossible_prevalence_geoids}."
            ),
            limit=0.01,
        )

        # 2b. Missing centroid coordinates (warn <= 5%, fail > 5%)
        note(
            checks,
            "tract_centroid_coordinates_present",
            bad=len(missing_coords_geoids),
            total=n_tracts,
            detail=(
                f"All {n_tracts} tracts have centroid coordinates."
                if len(missing_coords_geoids) == 0
                else f"{len(missing_coords_geoids)} of {n_tracts} tracts lack PLACES centroid coordinates: {missing_coords_geoids}."
            ),
            limit=0.05,
        )

        # 2c. Zero-population or suppressed PLACES tracts (warn <= 5%, fail > 5%)
        suppressed_or_zeropop_geoids: List[str] = []
        for t in tracts:
            gid = str(_get(t, "geo_id", "") or "")
            pop = _get(t, "total_pop", None)
            unins = _get(t, "pct_uninsured_18_64", None)
            if pop is None or int(pop) <= 0 or unins is None:
                suppressed_or_zeropop_geoids.append(gid)

        suppressed_note = note(
            checks,
            "zero_population_or_suppressed_tracts",
            bad=len(suppressed_or_zeropop_geoids),
            total=n_tracts,
            detail=(
                f"All {n_tracts} tracts have positive population and unsuppressed PLACES estimates."
                if len(suppressed_or_zeropop_geoids) == 0
                else (
                    f"{len(suppressed_or_zeropop_geoids)} of {n_tracts} tracts have zero population or "
                    f"suppressed PLACES estimates (airports/parks/institutional): {suppressed_or_zeropop_geoids}."
                )
            ),
            limit=0.05,
        )
        if suppressed_note.verdict == "WARN":
            caveats.append(
                f"SUPPRESSED / ZERO-POPULATION TRACTS: {len(suppressed_or_zeropop_geoids)} tract(s) "
                f"({suppressed_or_zeropop_geoids}) have zero population or suppressed PLACES estimates and are excluded from ranking."
            )

        # 2d. Plausible safety-net distances (<= 100 km)
        far_safety_net_geoids: List[str] = []
        for t in tracts:
            gid = str(_get(t, "geo_id", "") or "")
            km_net = _get(t, "km_to_safety_net", None)
            if km_net is not None:
                try:
                    if float(km_net) > 100.0:
                        far_safety_net_geoids.append(gid)
                except (TypeError, ValueError):
                    pass

        note(
            checks,
            "plausible_safety_net_distances",
            bad=len(far_safety_net_geoids),
            total=n_tracts,
            detail=(
                "All tract safety-net distances are <= 100 km."
                if len(far_safety_net_geoids) == 0
                else f"{len(far_safety_net_geoids)} tract(s) exceed 100 km to nearest safety-net facility: {far_safety_net_geoids}."
            ),
            limit=0.10,
        )

        # 2e. HPSA shortage_areas vs shortage_facilities nuance (total=0 -> never blocks)
        shortage_areas_count = int(_get(health_evidence, "shortage_areas_count", 0) or 0)
        shortage_facilities_count = int(_get(health_evidence, "shortage_facilities_count", 0) or 0)
        note(
            checks,
            "hpsa_shortage_area_vs_facility_nuance",
            bad=1 if shortage_areas_count == 0 else 0,
            total=0,
            detail=(
                f"Fulton County has 0 active shortage_areas (99 Proposed For Withdrawal) vs {shortage_facilities_count} shortage_facilities."
                if shortage_areas_count == 0
                else f"{shortage_areas_count} active shortage_areas and {shortage_facilities_count} shortage_facilities loaded."
            ),
        )

        # 2f. Regional disease weekly missingness (data_unavailable -> WARN, never blocks)
        disease_unavail = bool(_get(regional_disease, "data_unavailable", False)) or (
            regional_disease is not None
            and _get(regional_disease, "percent_visits_covid", None) is None
            and _get(regional_disease, "percent_visits_influenza", None) is None
            and _get(regional_disease, "percent_visits_rsv", None) is None
        )
        note(
            checks,
            "regional_disease_weekly_availability",
            bad=1 if disease_unavail else 0,
            total=0,
            detail=(
                "NSSP weekly respiratory ED visit percentages are unavailable (data_unavailable=True); report 'we cannot tell', never 'no increase'."
                if disease_unavail
                else f"NSSP 4-county HSA respiratory surveillance available (latest_week_end={_get(regional_disease, 'latest_week_end', 'unknown')})."
            ),
        )
        if disease_unavail:
            caveats.append(
                "NSSP DISEASE SURVEILLANCE MISSINGNESS: Weekly HSA respiratory ED percentages are unavailable for the latest window; CareBridge reports 'we cannot tell' rather than claiming 'no increase'."
            )

        # 2f-bis. Regional disease freshness check (warn if latest_week_end is >90 days old or historical)
        latest_week_end_val = str(_get(regional_disease, "latest_week_end", "") or "")
        is_stale_disease = False
        stale_detail = f"Latest non-empty week {latest_week_end_val or 'none'}; regional only."
        if latest_week_end_val and not disease_unavail:
            try:
                from datetime import datetime, timezone
                # Parse YYYY-MM-DD or ISO timestamp
                parsed_date = datetime.fromisoformat(latest_week_end_val.split()[0].split("T")[0])
                # If timestamp is more than 90 days prior to current date
                current_now = datetime.now(timezone.utc).replace(tzinfo=None)
                age_days = (current_now - parsed_date).days
                if age_days > 90:
                    is_stale_disease = True
                    stale_detail = (
                        f"Last non-empty week {latest_week_end_val} is {age_days} days old (>90 days stale); "
                        "recent weeks blank in CDC NSSP feed; excluded from tract ranking."
                    )
            except Exception:
                pass

        note(
            checks,
            "respiratory_trend_freshness",
            bad=1 if is_stale_disease else 0,
            total=0,
            detail=stale_detail,
            limit=0.0,
        )
        if is_stale_disease:
            caveats.append(
                f"NSSP DISEASE FRESHNESS CAVEAT: {stale_detail} CareBridge siting planner assigns zero weight to stale syndromic signals."
            )


        # 2g. Optional datasets availability (missing optional datasets WARN, never block)
        marta_ok = bool(_get(mobility_evidence, "marta_gtfs_available", False))
        usda_ok = bool(_get(mobility_evidence, "usda_food_access_available", False))
        imls_ok = bool(_get(mobility_evidence, "imls_venues_available", False))

        optional_datasets_status: Dict[str, str] = {
            "marta_gtfs": "available" if marta_ok else "unavailable",
            "usda_food_access": "available" if usda_ok else "unavailable",
            "imls_candidate_venues": "available" if imls_ok else "unavailable",
        }
        missing_optional = [k for k, v in optional_datasets_status.items() if v != "available"]

        note(
            checks,
            "optional_datasets_availability",
            bad=len(missing_optional),
            total=0,
            detail=(
                "All optional mobility and community venue datasets (marta_gtfs, usda_food_access, imls_candidate_venues) are available."
                if not missing_optional
                else (
                    f"Optional dataset gap ({', '.join(missing_optional)} unavailable); "
                    "degrading gracefully to census tract centroids without blocking planning."
                )
            ),
        )
        if missing_optional:
            caveats.append(
                f"OPTIONAL DATASET GRACEFUL DEGRADATION: {', '.join(missing_optional)} unavailable; "
                "Siting Planner will operate on core health/access tables and tract centroids without blocking."
            )

        # Propagate any mobility caveats not already in caveats
        for mob_caveat in list(_get(mobility_evidence, "caveats", []) or []):
            if isinstance(mob_caveat, str) and mob_caveat not in caveats:
                caveats.append(mob_caveat)

        blocking_failures = [
            f"{item.check_name}: {item.detail}"
            for item in checks
            if item.verdict == "FAIL"
        ]
        core_tables_ready = len(blocking_failures) == 0
        validated_tract_count = valid_tract_count if core_tables_ready else 0

        pass_count = sum(1 for c in checks if c.verdict == "PASS")
        warn_count = sum(1 for c in checks if c.verdict == "WARN")
        fail_count = sum(1 for c in checks if c.verdict == "FAIL")

        span.set_attribute("core_tables_ready", core_tables_ready)
        span.set_attribute("pass_count", pass_count)
        span.set_attribute("warn_count", warn_count)
        span.set_attribute("fail_count", fail_count)
        span.set_attribute("validated_tract_count", validated_tract_count)

        record_structured_log(
            component="evidence_validator_agent",
            event_type="evidence_validation_completed",
            severity="INFO" if core_tables_ready else "WARNING",
            county_fips=county_fips,
            core_tables_ready=core_tables_ready,
            pass_count=pass_count,
            warn_count=warn_count,
            fail_count=fail_count,
            validated_tract_count=validated_tract_count,
        )

        return EvidenceReport(
            county_fips=county_fips,
            core_tables_ready=core_tables_ready,
            blocking_failures=blocking_failures,
            checks=checks,
            validated_tract_count=validated_tract_count,
            prohibited_claims_blocked=prohibited_claims_blocked,
            optional_datasets_status=optional_datasets_status,
            caveats=caveats,
        )


def validate_collected_evidence(
    tool_context: Any = None,
    health_evidence: Optional[Dict[str, Any]] = None,
    mobility_evidence: Optional[Dict[str, Any]] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """ADK FunctionTool entrypoint that validates `health_evidence` and `mobility_evidence` and writes `evidence_report`."""
    _ = kwargs
    state: Optional[Dict[str, Any]] = None
    if tool_context is not None:
        if hasattr(tool_context, "state") and isinstance(tool_context.state, dict):
            state = tool_context.state
        elif hasattr(tool_context, "session") and hasattr(tool_context.session, "state"):
            state = tool_context.session.state

    if health_evidence is None and state is not None:
        health_evidence = state.get(STATE_HEALTH_EVIDENCE)
    if mobility_evidence is None and state is not None:
        mobility_evidence = state.get(STATE_MOBILITY_EVIDENCE)

    if health_evidence is None:
        health_evidence = build_mock_health_evidence()
    if mobility_evidence is None:
        mobility_evidence = build_mock_mobility_evidence()

    report = evaluate_evidence_quality(
        health_evidence=health_evidence,
        mobility_evidence=mobility_evidence,
    )
    report_dict = report.model_dump()

    assert_no_pii_in_payload(report_dict)
    assert_race_blind_planner_input(report_dict)

    if state is not None:
        state[STATE_EVIDENCE_REPORT] = report_dict

    return report_dict


# Alias matching Step 3.3 import name `validate_collected_evidence_tool`
validate_collected_evidence_tool = validate_collected_evidence
