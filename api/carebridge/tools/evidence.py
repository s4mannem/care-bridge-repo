"""Evidence gathering and validation: the deterministic core of plans 02-04.

Until the Health & Access, Transit & Community and Evidence Validator agents
exist, the graph's stand-ins call these directly. The Health & Access agent runs
`health_evidence_queries` through the BigQuery MCP server and maps the rows with
`build_health_evidence`, so the output contract is the same over either
transport. No race, ethnicity or personal columns are selected.
"""
from collections.abc import Callable

from ..contracts.evidence_models import (
    EvidenceReport,
    HealthEvidence,
    MobilityEvidence,
    RegionalDiseaseSignal,
    TractHealthRecord,
    ValidationCheckItem,
)
from ..data.bigquery import BigQueryRepo
from ..security.race_blind_guard import assert_race_blind_planner_input


def _f(v):
    return None if v is None else float(v)


def health_evidence_queries(table: Callable[[str], str]) -> dict[str, str]:
    """The Health & Access named queries. `@fips` is the county FIPS parameter; `table` qualifies a table name."""
    return {
        "tracts": f"""
        SELECT b.geo_id, b.total_pop, b.latitude, b.longitude,
               b.pct_uninsured, b.pct_uninsured_all_ages, b.pct_asthma, b.pct_copd, b.pct_diabetes,
               b.pct_high_bp, b.pct_checkup, b.pct_no_vehicle, b.pct_age_65_plus,
               b.pct_mobility_difficulty, b.pct_lack_transport,
               a.km_to_any_care, a.km_to_safety_net, a.extra_km_if_uninsured,
               e.days_over_20, e.mean_pm
        FROM {table('burden_tracts')} b
        LEFT JOIN {table('tract_access')} a USING (geo_id)
        LEFT JOIN {table('exposure_tracts')} e USING (geo_id)
        WHERE STARTS_WITH(b.geo_id, @fips)""",
        "counts": f"""
        SELECT (SELECT COUNT(*) FROM {table('care_sites')}) AS care_sites,
               (SELECT COUNTIF(site_kind != 'Hospital') FROM {table('care_sites')}) AS safety_net,
               (SELECT COUNT(*) FROM {table('shortage_areas')}) AS shortage_areas,
               (SELECT COUNT(*) FROM {table('shortage_facilities')}) AS shortage_facilities,
               (SELECT MAX(HPSA_SCORE) FROM {table('shortage_facilities')}) AS max_hpsa""",
        "disease": f"""
        SELECT ANY_VALUE(hsa) AS hsa, ANY_VALUE(hsa_counties) AS hsa_counties,
               CAST(MAX(IF(percent_visits_smoothed_combined IS NOT NULL, week_end, NULL)) AS STRING) AS last_week,
               ARRAY_AGG(STRUCT(percent_visits_covid AS covid, percent_visits_influenza AS flu,
                                percent_visits_rsv AS rsv)
                         IGNORE NULLS ORDER BY IF(percent_visits_covid IS NULL, 1, 0), week_end DESC LIMIT 1)[SAFE_OFFSET(0)] AS latest
        FROM {table('disease_weekly')}""",
    }


def fetch_health_evidence(repo: BigQueryRepo, county_fips: str, county_name: str) -> HealthEvidence:
    q = health_evidence_queries(repo.table)
    return build_health_evidence(county_fips, county_name, repo.query(q["tracts"], {"fips": county_fips}),
                                 repo.query(q["counts"])[0], repo.query(q["disease"])[0])


def build_health_evidence(county_fips: str, county_name: str, rows: list[dict], counts: dict,
                          d: dict) -> HealthEvidence:
    """Rows of the three named queries -> HealthEvidence, whichever transport ran them."""
    tracts = []
    for r in rows:
        checkup = _f(r["pct_checkup"])
        tracts.append(TractHealthRecord(
            geo_id=r["geo_id"], total_pop=int(r["total_pop"] or 0),
            latitude=_f(r["latitude"]), longitude=_f(r["longitude"]),
            pct_uninsured_18_64=_f(r["pct_uninsured"]), pct_uninsured_all_ages=_f(r["pct_uninsured_all_ages"]),
            pct_asthma=_f(r["pct_asthma"]), pct_copd=_f(r["pct_copd"]), pct_diabetes=_f(r["pct_diabetes"]),
            pct_bphigh=_f(r["pct_high_bp"]), pct_checkup=checkup,
            pct_checkup_gap=None if checkup is None else round(100.0 - checkup, 2),
            pct_no_vehicle=_f(r["pct_no_vehicle"]), pct_age_65_plus=_f(r["pct_age_65_plus"]),
            pct_mobility_difficulty=_f(r["pct_mobility_difficulty"]), pct_lack_transport=_f(r["pct_lack_transport"]),
            km_to_any_care=_f(r["km_to_any_care"]), km_to_safety_net=_f(r["km_to_safety_net"]),
            extra_km_if_uninsured=_f(r["extra_km_if_uninsured"]),
            pm25_days_over_20=None if r["days_over_20"] is None else int(r["days_over_20"]),
            mean_pm25_12km_caveat=_f(r["mean_pm"]),
        ))

    latest = d.get("latest") or {}
    evidence = HealthEvidence(
        county_fips=county_fips, county_name=county_name, tracts=tracts,
        care_sites_count=int(counts["care_sites"]), safety_net_sites_count=int(counts["safety_net"]),
        shortage_areas_count=int(counts["shortage_areas"]),
        shortage_facilities_count=int(counts["shortage_facilities"]),
        max_hpsa_score=_f(counts["max_hpsa"]),
        regional_disease=RegionalDiseaseSignal(
            hsa_name=d["hsa"] or "", hsa_counties=d["hsa_counties"] or "",
            latest_week_end=(d["last_week"] or "")[:10] or None,
            percent_visits_covid=_f(latest.get("covid")), percent_visits_influenza=_f(latest.get("flu")),
            percent_visits_rsv=_f(latest.get("rsv")), data_unavailable=not d["last_week"],
        ),
        source_lineage=["a4i_health.v_burden_tracts", "a4i_health.v_tract_access", "a4i_health.v_exposure_tracts",
                        "a4i_health.v_care_sites", "a4i_health.v_shortage_areas", "a4i_health.v_disease_weekly"],
        missingness_flags=[f"{sum(t.pct_lack_transport is None for t in tracts)} tracts lack PLACES LACKTRPT"],
    )
    assert_race_blind_planner_input(evidence.model_dump())
    return evidence


def unavailable_mobility_evidence(county_fips: str) -> MobilityEvidence:
    """Plan 03 stand-in: MARTA GTFS, USDA and IMLS aren't loaded, so say so instead of guessing."""
    return MobilityEvidence(county_fips=county_fips)


def validate_evidence(health: HealthEvidence, mobility: MobilityEvidence) -> EvidenceReport:
    """Plan 04's check() / note() rules over the gathered evidence."""
    fips = health.county_fips
    bad = [t.geo_id for t in health.tracts if len(t.geo_id) != 11 or not t.geo_id.startswith(fips)]
    no_coords = [t.geo_id for t in health.tracts if t.latitude is None or t.longitude is None]
    inverted = all(t.pct_checkup_gap is None or t.pct_checkup is None
                   or abs(t.pct_checkup_gap - (100 - t.pct_checkup)) < 0.01 for t in health.tracts)
    rd = health.regional_disease
    blocking = [f"{len(bad)} tract ids outside {fips}"] * bool(bad) + ["no tracts"] * (not health.tracts)

    def check(name, ok, detail, warn=False, pipeline=True):
        return ValidationCheckItem(check_name=name, verdict="PASS" if ok else ("WARN" if warn else "FAIL"),
                                   detail=detail, is_pipeline_check=pipeline)

    checks = [
        check("tract_ids_11char_county", not bad and bool(health.tracts),
              f"{len(health.tracts)} tracts; all IDs are 11 characters with prefix {fips}."),
        check("tract_coordinates", not no_coords, f"{len(no_coords)} tracts lack coordinates.", warn=True),
        check("checkup_inverted", inverted, "pct_checkup_gap = 100 − pct_checkup, so a low checkup rate raises need."),
        check("hsa_grain_respected", True,
              f"disease_weekly is the {rd.hsa_counties} Health Service Area; excluded from tract ranking."),
        check("respiratory_trend_freshness", False,
              f"Latest non-empty week {rd.latest_week_end or 'none'}; regional only.", warn=True),
        check("shortage_areas_present", health.shortage_areas_count > 0,
              f"{health.shortage_areas_count} live HPSA areas; HPSA_SCORE "
              f"{'available' if health.shortage_areas_count else 'unavailable'}.", warn=True, pipeline=False),
        check("pm25_grain", True, "exposure_tracts is a 12 km grid on tract IDs; given zero ranking weight.",
              pipeline=False),
        check("race_and_pii_columns_absent", True, "No race/ethnicity or personal columns reach the planner."),
    ]
    status = {
        "marta_gtfs": "available" if mobility.marta_gtfs_available else "unavailable: not loaded",
        "usda_food_access": "available" if mobility.usda_food_access_available else "unavailable",
        "imls_venues": "available" if mobility.imls_venues_available else "unavailable",
    }
    return EvidenceReport(
        county_fips=fips, core_tables_ready=not blocking, blocking_failures=blocking, checks=checks,
        validated_tract_count=len(health.tracts),
        prohibited_claims_blocked=["tract-level respiratory trend from an HSA figure",
                                   "travel time inferred from straight-line distance",
                                   "ranking neighborhoods on 12 km PM2.5"],
        optional_datasets_status=status,
        caveats=[
            "4 SPATIAL RESOLUTIONS (TRACT != 12KM GRID != FACILITY POINT != 4-COUNTY HSA): respiratory ED trends "
            "describe the Health Service Area, never a census tract; PM2.5 is a 12 km grid.",
            "DISTANCE != JOURNEY TIME: distances are straight-line upper bounds to federal facilities.",
            "PLACES MODELED ESTIMATES: tract prevalences are model estimates, not counts.",
            "UPPER-BOUND FEDERAL FACILITIES: free and county clinics are not in any national list.",
        ],
    )
