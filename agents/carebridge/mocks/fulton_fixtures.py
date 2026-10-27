"""Realistic, schema-validated Fulton County (`13121`) fixtures derived from `c5_01_load_explore.ipynb`."""

from __future__ import annotations

from typing import Any, Dict, List
from carebridge.contracts.api_models import PlanRequest, PlanResponse
from carebridge.contracts.audit_models import (
    AuditReport,
    AuditVerdict,
    DemographicImpactComparison,
)
from carebridge.contracts.evidence_models import (
    CandidateHostVenue,
    EvidenceReport,
    HealthEvidence,
    MobilityEvidence,
    RegionalDiseaseSignal,
    SpatialGrain,
    TractHealthRecord,
    TractMobilityRecord,
    ValidationCheckItem,
)
from carebridge.contracts.outreach_models import (
    OutreachMessages,
    StopOutreachDraft,
    UnpickedNeighborhoodExplanation,
)
from carebridge.contracts.plan_models import (
    DraftPlan,
    ProposedClinicStop,
    RunnerUpTractExplanation,
    ScoreBreakdown,
    SensitivitySummary,
)

# 12 representative Fulton County (`13121`) census tracts spanning South/Southwest/West Atlanta
# high-need neighborhoods and North/Midtown comparison tracts.
FULTON_TRACT_HEALTH_RECORDS: List[TractHealthRecord] = [
    TractHealthRecord(
        geo_id="13121010214",
        total_pop=1938,
        latitude=33.7485,
        longitude=-84.5120,
        pct_uninsured_18_64=24.2,
        pct_uninsured_all_ages=14.0,
        uninsured_age_structure_gap=10.2,
        pct_asthma=12.4,
        pct_copd=8.9,
        pct_diabetes=16.8,
        pct_bphigh=41.2,
        pct_checkup=68.5,
        pct_checkup_gap=31.5,
        pct_uninsured_18_64_ci_width=3.4,
        pct_no_vehicle=43.0,
        pct_age_65_plus=18.2,
        pct_mobility_difficulty=19.4,
        pct_lack_transport=15.8,
        km_to_any_care=0.8,
        km_to_safety_net=8.1,
        extra_km_if_uninsured=7.3,
        cross_border_state_care_km=6.9,
        pm25_days_over_20=5,
        mean_pm25_12km_caveat=9.6,
    ),
    TractHealthRecord(
        geo_id="13121007602",
        total_pop=3840,
        latitude=33.6812,
        longitude=-84.4510,
        pct_uninsured_18_64=25.6,
        pct_uninsured_all_ages=19.8,
        uninsured_age_structure_gap=5.8,
        pct_asthma=11.9,
        pct_copd=8.2,
        pct_diabetes=15.9,
        pct_bphigh=39.5,
        pct_checkup=69.2,
        pct_checkup_gap=30.8,
        pct_uninsured_18_64_ci_width=3.1,
        pct_no_vehicle=28.4,
        pct_age_65_plus=14.1,
        pct_mobility_difficulty=17.2,
        pct_lack_transport=14.2,
        km_to_any_care=1.9,
        km_to_safety_net=9.4,
        extra_km_if_uninsured=7.5,
        cross_border_state_care_km=8.2,
        pm25_days_over_20=5,
        mean_pm25_12km_caveat=9.5,
    ),
    TractHealthRecord(
        geo_id="13121008201",
        total_pop=4120,
        latitude=33.7620,
        longitude=-84.4650,
        pct_uninsured_18_64=22.8,
        pct_uninsured_all_ages=17.5,
        uninsured_age_structure_gap=5.3,
        pct_asthma=12.1,
        pct_copd=7.9,
        pct_diabetes=15.2,
        pct_bphigh=38.8,
        pct_checkup=70.1,
        pct_checkup_gap=29.9,
        pct_uninsured_18_64_ci_width=2.9,
        pct_no_vehicle=31.2,
        pct_age_65_plus=15.0,
        pct_mobility_difficulty=16.8,
        pct_lack_transport=13.9,
        km_to_any_care=1.4,
        km_to_safety_net=6.2,
        extra_km_if_uninsured=4.8,
        cross_border_state_care_km=6.2,
        pm25_days_over_20=5,
        mean_pm25_12km_caveat=9.6,
    ),
    TractHealthRecord(
        geo_id="13121010514",
        total_pop=5610,
        latitude=33.5820,
        longitude=-84.5680,
        pct_uninsured_18_64=26.4,
        pct_uninsured_all_ages=21.1,
        uninsured_age_structure_gap=5.3,
        pct_asthma=11.5,
        pct_copd=8.4,
        pct_diabetes=16.1,
        pct_bphigh=40.1,
        pct_checkup=67.8,
        pct_checkup_gap=32.2,
        pct_uninsured_18_64_ci_width=3.2,
        pct_no_vehicle=19.6,
        pct_age_65_plus=13.4,
        pct_mobility_difficulty=16.1,
        pct_lack_transport=12.7,
        km_to_any_care=4.8,
        km_to_safety_net=18.5,
        extra_km_if_uninsured=13.7,
        cross_border_state_care_km=14.1,
        pm25_days_over_20=4,
        mean_pm25_12km_caveat=9.3,
    ),
    TractHealthRecord(
        geo_id="13121011305",
        total_pop=4890,
        latitude=33.6310,
        longitude=-84.3820,
        pct_uninsured_18_64=23.5,
        pct_uninsured_all_ages=18.4,
        uninsured_age_structure_gap=5.1,
        pct_asthma=11.8,
        pct_copd=8.1,
        pct_diabetes=15.4,
        pct_bphigh=38.2,
        pct_checkup=69.8,
        pct_checkup_gap=30.2,
        pct_uninsured_18_64_ci_width=3.0,
        pct_no_vehicle=24.8,
        pct_age_65_plus=12.8,
        pct_mobility_difficulty=15.9,
        pct_lack_transport=13.4,
        km_to_any_care=2.6,
        km_to_safety_net=11.2,
        extra_km_if_uninsured=8.6,
        cross_border_state_care_km=7.4,
        pm25_days_over_20=5,
        mean_pm25_12km_caveat=9.5,
    ),
    TractHealthRecord(
        geo_id="13121011000",
        total_pop=3450,
        latitude=33.7025,
        longitude=-84.3980,
        pct_uninsured_18_64=21.9,
        pct_uninsured_all_ages=16.9,
        uninsured_age_structure_gap=5.0,
        pct_asthma=12.0,
        pct_copd=7.8,
        pct_diabetes=14.9,
        pct_bphigh=37.6,
        pct_checkup=71.0,
        pct_checkup_gap=29.0,
        pct_uninsured_18_64_ci_width=2.8,
        pct_no_vehicle=26.5,
        pct_age_65_plus=13.9,
        pct_mobility_difficulty=15.2,
        pct_lack_transport=12.9,
        km_to_any_care=1.7,
        km_to_safety_net=5.4,
        extra_km_if_uninsured=3.7,
        cross_border_state_care_km=5.4,
        pm25_days_over_20=5,
        mean_pm25_12km_caveat=9.6,
    ),
    TractHealthRecord(
        geo_id="13121006602",
        total_pop=3190,
        latitude=33.7190,
        longitude=-84.4210,
        pct_uninsured_18_64=20.8,
        pct_uninsured_all_ages=16.2,
        uninsured_age_structure_gap=4.6,
        pct_asthma=11.6,
        pct_copd=7.5,
        pct_diabetes=14.3,
        pct_bphigh=36.9,
        pct_checkup=71.8,
        pct_checkup_gap=28.2,
        pct_uninsured_18_64_ci_width=2.7,
        pct_no_vehicle=25.1,
        pct_age_65_plus=14.5,
        pct_mobility_difficulty=14.8,
        pct_lack_transport=12.1,
        km_to_any_care=1.5,
        km_to_safety_net=4.9,
        extra_km_if_uninsured=3.4,
        cross_border_state_care_km=4.9,
        pm25_days_over_20=5,
        mean_pm25_12km_caveat=9.5,
    ),
    TractHealthRecord(
        geo_id="13121007808",
        total_pop=4620,
        latitude=33.7390,
        longitude=-84.4910,
        pct_uninsured_18_64=22.4,
        pct_uninsured_all_ages=17.1,
        uninsured_age_structure_gap=5.3,
        pct_asthma=12.2,
        pct_copd=8.3,
        pct_diabetes=16.0,
        pct_bphigh=39.9,
        pct_checkup=69.5,
        pct_checkup_gap=30.5,
        pct_uninsured_18_64_ci_width=3.0,
        pct_no_vehicle=29.8,
        pct_age_65_plus=16.1,
        pct_mobility_difficulty=17.5,
        pct_lack_transport=14.0,
        km_to_any_care=1.6,
        km_to_safety_net=7.4,
        extra_km_if_uninsured=5.8,
        cross_border_state_care_km=6.8,
        pm25_days_over_20=5,
        mean_pm25_12km_caveat=9.6,
    ),
    TractHealthRecord(
        geo_id="13121010305",
        total_pop=5120,
        latitude=33.6050,
        longitude=-84.5390,
        pct_uninsured_18_64=21.5,
        pct_uninsured_all_ages=16.8,
        uninsured_age_structure_gap=4.7,
        pct_asthma=11.3,
        pct_copd=7.9,
        pct_diabetes=15.1,
        pct_bphigh=38.4,
        pct_checkup=70.4,
        pct_checkup_gap=29.6,
        pct_uninsured_18_64_ci_width=2.9,
        pct_no_vehicle=18.2,
        pct_age_65_plus=13.0,
        pct_mobility_difficulty=15.0,
        pct_lack_transport=11.8,
        km_to_any_care=4.1,
        km_to_safety_net=15.9,
        extra_km_if_uninsured=11.8,
        cross_border_state_care_km=12.6,
        pm25_days_over_20=4,
        mean_pm25_12km_caveat=9.3,
    ),
    TractHealthRecord(
        geo_id="13121012000",
        total_pop=3980,
        latitude=33.6580,
        longitude=-84.4390,
        pct_uninsured_18_64=20.1,
        pct_uninsured_all_ages=15.6,
        uninsured_age_structure_gap=4.5,
        pct_asthma=11.1,
        pct_copd=7.4,
        pct_diabetes=14.2,
        pct_bphigh=36.5,
        pct_checkup=71.5,
        pct_checkup_gap=28.5,
        pct_uninsured_18_64_ci_width=2.6,
        pct_no_vehicle=22.0,
        pct_age_65_plus=12.5,
        pct_mobility_difficulty=14.1,
        pct_lack_transport=11.5,
        km_to_any_care=2.2,
        km_to_safety_net=8.8,
        extra_km_if_uninsured=6.6,
        cross_border_state_care_km=7.9,
        pm25_days_over_20=5,
        mean_pm25_12km_caveat=9.5,
    ),
    TractHealthRecord(
        geo_id="13121009501",
        total_pop=4510,
        latitude=33.8420,
        longitude=-84.3710,
        pct_uninsured_18_64=6.4,
        pct_uninsured_all_ages=4.8,
        uninsured_age_structure_gap=1.6,
        pct_asthma=8.2,
        pct_copd=3.9,
        pct_diabetes=7.1,
        pct_bphigh=24.5,
        pct_checkup=79.4,
        pct_checkup_gap=20.6,
        pct_uninsured_18_64_ci_width=1.4,
        pct_no_vehicle=4.2,
        pct_age_65_plus=16.8,
        pct_mobility_difficulty=6.5,
        pct_lack_transport=3.8,
        km_to_any_care=1.1,
        km_to_safety_net=6.8,
        extra_km_if_uninsured=5.7,
        cross_border_state_care_km=6.8,
        pm25_days_over_20=4,
        mean_pm25_12km_caveat=9.4,
    ),
    TractHealthRecord(
        geo_id="13121010119",
        total_pop=5280,
        latitude=34.0720,
        longitude=-84.2750,
        pct_uninsured_18_64=5.9,
        pct_uninsured_all_ages=4.5,
        uninsured_age_structure_gap=1.4,
        pct_asthma=7.9,
        pct_copd=3.6,
        pct_diabetes=6.8,
        pct_bphigh=23.1,
        pct_checkup=81.2,
        pct_checkup_gap=18.8,
        pct_uninsured_18_64_ci_width=1.3,
        pct_no_vehicle=2.1,
        pct_age_65_plus=12.4,
        pct_mobility_difficulty=5.4,
        pct_lack_transport=2.9,
        km_to_any_care=2.4,
        km_to_safety_net=28.6,
        extra_km_if_uninsured=26.2,
        cross_border_state_care_km=19.4,
        pm25_days_over_20=3,
        mean_pm25_12km_caveat=9.1,
    ),
]

FULTON_CARE_SITES: List[Dict[str, Any]] = [
    {
        "site_id": "HRSA-FQHC-13121-01",
        "site_name": "Southside Medical Center — Main Campus",
        "source_type": "FQHC",
        "county_fips": "13121",
        "latitude": 33.7145,
        "longitude": -84.3845,
        "is_safety_net": True,
        "tot_oper_hr_per_week": 45.0,
    },
    {
        "site_id": "HRSA-FQHC-13121-02",
        "site_name": "HEALing Community Center — West End",
        "source_type": "FQHC",
        "county_fips": "13121",
        "latitude": 33.7365,
        "longitude": -84.4170,
        "is_safety_net": True,
        "tot_oper_hr_per_week": 40.0,
    },
    {
        "site_id": "HRSA-FQHC-13121-03",
        "site_name": "Family Health Centers of Georgia — Westside",
        "source_type": "FQHC",
        "county_fips": "13121",
        "latitude": 33.7755,
        "longitude": -84.4290,
        "is_safety_net": True,
        "tot_oper_hr_per_week": 48.0,
    },
    {
        "site_id": "CMS-HOSP-13121-04",
        "site_name": "Grady Memorial Hospital",
        "source_type": "Hospital",
        "county_fips": "13121",
        "latitude": 33.7519,
        "longitude": -84.3822,
        "is_safety_net": False,
        "tot_oper_hr_per_week": 168.0,
    },
]

FULTON_REGIONAL_DISEASE = RegionalDiseaseSignal(
    hsa_name="Atlanta Regional HSA (Fulton, Ga)",
    hsa_counties="Fulton, DeKalb, Clayton, Gwinnett",
    spatial_grain=SpatialGrain.MULTI_COUNTY_HSA,
    latest_week_end="2026-10-17",
    percent_visits_covid=1.8,
    percent_visits_influenza=2.4,
    percent_visits_rsv=1.3,
    ed_trends_covid="Stable",
    ed_trends_influenza="Increasing",
    ed_trends_rsv="Increasing",
    data_unavailable=False,
    grain_warning=(
        "NSSP ED visits are reported at the 4-county Health Service Area (HSA: Fulton, DeKalb, "
        "Clayton, Gwinnett) level, NEVER at the census tract or neighborhood level."
    ),
)

FULTON_CANDIDATE_VENUES: List[CandidateHostVenue] = [
    CandidateHostVenue(
        venue_id="IMLS-GA-13121-ADAMS",
        venue_name="Adamsville-Collier Heights Branch Library (Provisional Host)",
        venue_kind="Library (IMLS)",
        geo_id="13121010214",
        latitude=33.7485,
        longitude=-84.5120,
        saturday_transit_stops_within_400m=6,
        saturday_trips_per_hour=4.5,
        host_permission_verified=False,
    ),
    CandidateHostVenue(
        venue_id="IMLS-GA-13121-CLEVELAND",
        venue_name="Cleveland Avenue Branch Library (Provisional Host)",
        venue_kind="Library (IMLS)",
        geo_id="13121007602",
        latitude=33.6812,
        longitude=-84.4510,
        saturday_transit_stops_within_400m=5,
        saturday_trips_per_hour=4.0,
        host_permission_verified=False,
    ),
    CandidateHostVenue(
        venue_id="IMLS-GA-13121-BOWEN",
        venue_name="Northwest Atlanta / Perry Boulevard Library (Provisional Host)",
        venue_kind="Library (IMLS)",
        geo_id="13121008201",
        latitude=33.7620,
        longitude=-84.4650,
        saturday_transit_stops_within_400m=5,
        saturday_trips_per_hour=3.5,
        host_permission_verified=False,
    ),
    CandidateHostVenue(
        venue_id="IMLS-GA-13121-FAIRBURN",
        venue_name="South Fulton / Fairburn Public Library (Provisional Host)",
        venue_kind="Library (IMLS)",
        geo_id="13121010514",
        latitude=33.5820,
        longitude=-84.5680,
        saturday_transit_stops_within_400m=3,
        saturday_trips_per_hour=2.5,
        host_permission_verified=False,
    ),
    CandidateHostVenue(
        venue_id="IMLS-GA-13121-HAPEVILLE",
        venue_name="Hapeville / Southside Community Library (Provisional Host)",
        venue_kind="Library (IMLS)",
        geo_id="13121011305",
        latitude=33.6310,
        longitude=-84.3820,
        saturday_transit_stops_within_400m=4,
        saturday_trips_per_hour=3.5,
        host_permission_verified=False,
    ),
    CandidateHostVenue(
        venue_id="IMLS-GA-13121-METROPOLITAN",
        venue_name="Metropolitan Branch Library (Provisional Host)",
        venue_kind="Library (IMLS)",
        geo_id="13121011000",
        latitude=33.7025,
        longitude=-84.3980,
        saturday_transit_stops_within_400m=7,
        saturday_trips_per_hour=6.0,
        host_permission_verified=False,
    ),
]

_VENUE_BY_TRACTS = {v.geo_id: [v] for v in FULTON_CANDIDATE_VENUES}

FULTON_TRACT_MOBILITY_RECORDS: List[TractMobilityRecord] = [
    TractMobilityRecord(
        geo_id=t.geo_id,
        saturday_active_stops_count=6 if idx < 6 else 2,
        saturday_mean_headway_min=20.0 if idx < 6 else 40.0,
        usda_low_income_low_access=(idx < 9),
        candidate_venues=_VENUE_BY_TRACTS.get(t.geo_id, []),
    )
    for idx, t in enumerate(FULTON_TRACT_HEALTH_RECORDS)
]

# Protected post-hoc demographic reference (`external_demographic_audit`) — VISIBLE TO AUDITOR ONLY!
DEMOGRAPHIC_AUDIT_FIXTURES: Dict[str, Dict[str, Any]] = {
    "13121010214": {
        "geo_id": "13121010214",
        "total_pop": 1938,
        "pct_black": 91.4,
        "pct_hispanic": 4.2,
        "pct_white": 2.8,
        "pct_asian": 0.6,
        "pct_minority": 97.2,
        "rpl_theme3_proxy": 0.94,
    },
    "13121007602": {
        "geo_id": "13121007602",
        "total_pop": 3840,
        "pct_black": 84.5,
        "pct_hispanic": 9.8,
        "pct_white": 3.9,
        "pct_asian": 0.9,
        "pct_minority": 96.1,
        "rpl_theme3_proxy": 0.91,
    },
    "13121008201": {
        "geo_id": "13121008201",
        "total_pop": 4120,
        "pct_black": 88.2,
        "pct_hispanic": 5.6,
        "pct_white": 4.5,
        "pct_asian": 0.8,
        "pct_minority": 95.5,
        "rpl_theme3_proxy": 0.89,
    },
    "13121010514": {
        "geo_id": "13121010514",
        "total_pop": 5610,
        "pct_black": 79.6,
        "pct_hispanic": 12.4,
        "pct_white": 5.8,
        "pct_asian": 1.2,
        "pct_minority": 94.2,
        "rpl_theme3_proxy": 0.86,
    },
    "13121011305": {
        "geo_id": "13121011305",
        "total_pop": 4890,
        "pct_black": 71.2,
        "pct_hispanic": 18.5,
        "pct_white": 7.4,
        "pct_asian": 1.9,
        "pct_minority": 92.6,
        "rpl_theme3_proxy": 0.84,
    },
    "13121011000": {
        "geo_id": "13121011000",
        "total_pop": 3450,
        "pct_black": 82.0,
        "pct_hispanic": 8.1,
        "pct_white": 7.9,
        "pct_asian": 1.0,
        "pct_minority": 92.1,
        "rpl_theme3_proxy": 0.82,
    },
    "13121006602": {
        "geo_id": "13121006602",
        "total_pop": 3190,
        "pct_black": 80.4,
        "pct_hispanic": 7.9,
        "pct_white": 9.5,
        "pct_asian": 1.2,
        "pct_minority": 90.5,
        "rpl_theme3_proxy": 0.79,
    },
    "13121007808": {
        "geo_id": "13121007808",
        "total_pop": 4620,
        "pct_black": 89.1,
        "pct_hispanic": 5.1,
        "pct_white": 4.2,
        "pct_asian": 0.7,
        "pct_minority": 95.8,
        "rpl_theme3_proxy": 0.90,
    },
    "13121010305": {
        "geo_id": "13121010305",
        "total_pop": 5120,
        "pct_black": 77.8,
        "pct_hispanic": 11.2,
        "pct_white": 8.4,
        "pct_asian": 1.5,
        "pct_minority": 91.6,
        "rpl_theme3_proxy": 0.81,
    },
    "13121012000": {
        "geo_id": "13121012000",
        "total_pop": 3980,
        "pct_black": 76.5,
        "pct_hispanic": 10.4,
        "pct_white": 10.2,
        "pct_asian": 1.8,
        "pct_minority": 89.8,
        "rpl_theme3_proxy": 0.77,
    },
    "13121009501": {
        "geo_id": "13121009501",
        "total_pop": 4510,
        "pct_black": 11.2,
        "pct_hispanic": 6.4,
        "pct_white": 74.8,
        "pct_asian": 5.9,
        "pct_minority": 25.2,
        "rpl_theme3_proxy": 0.18,
    },
    "13121010119": {
        "geo_id": "13121010119",
        "total_pop": 5280,
        "pct_black": 14.5,
        "pct_hispanic": 8.2,
        "pct_white": 58.4,
        "pct_asian": 16.9,
        "pct_minority": 41.6,
        "rpl_theme3_proxy": 0.34,
    },
}


def build_mock_health_evidence(county_fips: str = "13121") -> HealthEvidence:
    return HealthEvidence(
        county_fips=county_fips,
        county_name="Fulton",
        tracts=list(FULTON_TRACT_HEALTH_RECORDS),
        care_sites_count=85,
        safety_net_sites_count=41,
        shortage_areas_count=0,
        shortage_facilities_count=6,
        max_hpsa_score=19.0,
        regional_disease=FULTON_REGIONAL_DISEASE,
        source_lineage=[
            "a4i_health.v_burden_tracts (CDC PLACES 2025 + CDC/ATSDR SVI 2022, race-blind columns only)",
            "a4i_health.v_tract_access (straight-line upper-bound distances to federal sites)",
            "a4i_health.v_care_sites & v_care_sites_state (HRSA Health Centers + CMS POS, TOT_OPER_HR_PER_WEEK)",
            "a4i_health.v_shortage_areas (0 active in Fulton; 99 Proposed For Withdrawal) & v_shortage_facilities (6)",
            "a4i_health.v_exposure_tracts (EPA 12km grid tail days > 20 ug/m3)",
            "a4i_health.v_disease_weekly (CDC NSSP 4-county HSA respiratory ED trends)",
        ],
        missingness_flags=[
            "shortage_areas_count=0 active in Fulton County (all 99 rows are Proposed For Withdrawal) despite 135 tracts having extra_km_if_uninsured > 0.",
        ],
    )


def build_mock_mobility_evidence(
    county_fips: str = "13121",
    include_optional: bool = True,
) -> MobilityEvidence:
    if not include_optional:
        return MobilityEvidence(
            county_fips=county_fips,
            marta_gtfs_available=False,
            usda_food_access_available=False,
            imls_venues_available=False,
            tract_mobility=[],
            caveats=[
                "Optional MARTA GTFS, USDA Food Access, and IMLS library venue views disabled or unavailable; using tract centroids.",
                "A nearby Saturday bus stop measures stop presence, not door-to-door clinic journey time.",
            ],
        )
    return MobilityEvidence(
        county_fips=county_fips,
        marta_gtfs_available=True,
        usda_food_access_available=True,
        imls_venues_available=True,
        tract_mobility=list(FULTON_TRACT_MOBILITY_RECORDS),
        caveats=[
            "A nearby Saturday bus stop measures stop presence, not door-to-door clinic journey time.",
            "Access Across America transit travel-time matrices excluded due to CC BY-NC license boundary.",
        ],
    )


def build_mock_evidence_report(county_fips: str = "13121") -> EvidenceReport:
    return EvidenceReport(
        county_fips=county_fips,
        core_tables_ready=True,
        blocking_failures=[],
        checks=[
            ValidationCheckItem(
                check_name="tract_geoid_11char_and_county_prefix",
                verdict="PASS",
                detail="All 12 fixture tracts have 11-char GEOIDs starting with 13121.",
                is_pipeline_check=True,
            ),
            ValidationCheckItem(
                check_name="race_blind_and_pii_exclusion",
                verdict="PASS",
                detail="Zero prohibited demographic or administrative contact PII columns present.",
                is_pipeline_check=True,
            ),
            ValidationCheckItem(
                check_name="pct_checkup_inversion_verified",
                verdict="PASS",
                detail="pct_checkup_gap == 100.0 - pct_checkup verified across all tracts.",
                is_pipeline_check=True,
            ),
            ValidationCheckItem(
                check_name="hpsa_shortage_area_vs_facility_nuance",
                verdict="WARN",
                detail="Fulton County has 0 active shortage_areas (99 Proposed For Withdrawal) vs 6 shortage_facilities.",
                is_pipeline_check=False,
            ),
        ],
        validated_tract_count=len(FULTON_TRACT_HEALTH_RECORDS),
        prohibited_claims_blocked=[
            "Blocked tract-level attribution of 4-county HSA NSSP respiratory trends",
            "Blocked ranking tracts by 12km EPA PM2.5 grid mean (p90/p10=1.05x)",
            "Blocked treating straight-line federal site distance as bus travel time",
        ],
        optional_datasets_status={
            "marta_gtfs": "available",
            "usda_food_access": "available",
            "imls_candidate_venues": "available",
        },
        caveats=[
            "4 SPATIAL RESOLUTIONS (TRACT != 12KM GRID != FACILITY POINT != 4-COUNTY HSA): Weekly respiratory ED trends (NSSP) represent the 4-county Health Service Area (Fulton, DeKalb, Clayton, Gwinnett), never an individual census tract; PM2.5 is a 12km grid (`p90/p10=1.05x`) and cannot rank neighborhoods.",
            "DISTANCE != JOURNEY TIME: km_to_any_care and km_to_safety_net are straight-line Euclidean upper-bound distances to federally recognized facilities, not bus transfer or road travel times. Access Across America transit matrices are excluded (CC BY-NC).",
            "PLACES MODELED ESTIMATES & 95% CI: Tract health prevalences are small-area modeled estimates (not patient headcounts); minor percentage-point differences (<1-2%) fall within overlapping 95% confidence intervals.",
            "UPPER-BOUND FEDERAL FACILITY BOUNDARY & PII EXCLUSIONS: Non-federal free clinics, county health departments, pharmacies (NPPES excluded due to practitioner PII), FQHC_ADMIN_CONTACT_* fields, and unlicensed mobile clinics are excluded; distances represent upper bounds on distance to care.",
        ],
    )


def build_mock_draft_plan(county_fips: str = "13121") -> DraftPlan:
    stops = [
        ProposedClinicStop(
            stop_rank=1,
            assigned_saturday="2026-11-07",
            primary_tract_geoid="13121010214",
            covered_tract_geoids=["13121010214", "13121007808"],
            candidate_venue_name="Adamsville-Collier Heights Branch Library (Provisional Host)",
            latitude=33.7485,
            longitude=-84.5120,
            catchment_radius_km=4.0,
            estimated_population_in_catchment=6558,
            score_breakdown=ScoreBreakdown(
                uninsured_norm=0.89,
                safety_net_distance_norm=0.25,
                no_vehicle_norm=1.0,
                chronic_respiratory_norm=0.98,
                checkup_preventive_gap_norm=0.95,
                saturday_transit_access_bonus=0.86,
                overlap_penalty=0.0,
                composite_need_score=0.82,
            ),
            plain_language_rationale=(
                "Tract 13121010214 exhibits 24.2% uninsured adults 18-64 (CDC PLACES modeled estimate, +/-3.4% CI), "
                "31.5% routine checkup gap (100 - pct_checkup), 43.0% zero-vehicle households (CDC SVI ACS), and "
                "8.1 km straight-line upper-bound distance to the nearest federal safety-net clinic (7.3 km penalty vs any care)."
            ),
            evidence_citations=[
                "a4i_health.v_burden_tracts:geo_id=13121010214",
                "a4i_health.v_tract_access:geo_id=13121010214",
            ],
            spatial_grain_disclosures=[
                "Tract prevalence values are CDC PLACES small-area modeled estimates (11-char tract grain).",
                "km_to_safety_net=8.1 km is straight-line upper-bound distance to federal FQHCs, not bus transit time.",
                "Regional influenza/RSV increase applies to the 4-county Atlanta HSA, not specifically tract 13121010214.",
            ],
            host_verified=False,
        ),
        ProposedClinicStop(
            stop_rank=2,
            assigned_saturday="2026-11-14",
            primary_tract_geoid="13121010514",
            covered_tract_geoids=["13121010514", "13121010305"],
            candidate_venue_name="South Fulton / Fairburn Public Library (Provisional Host)",
            latitude=33.5820,
            longitude=-84.5680,
            catchment_radius_km=4.0,
            estimated_population_in_catchment=10730,
            score_breakdown=ScoreBreakdown(
                uninsured_norm=1.0,
                safety_net_distance_norm=0.63,
                no_vehicle_norm=0.43,
                chronic_respiratory_norm=0.92,
                checkup_preventive_gap_norm=1.0,
                saturday_transit_access_bonus=0.43,
                overlap_penalty=0.0,
                composite_need_score=0.79,
            ),
            plain_language_rationale=(
                "Tract 13121010514 has 26.4% uninsured adults 18-64 (PLACES modeled estimate), a 32.2% preventive "
                "checkup gap (100 - pct_checkup), and an 18.5 km straight-line upper-bound distance to the nearest "
                "federal safety-net clinic (13.7 km uninsured penalty)."
            ),
            evidence_citations=[
                "a4i_health.v_burden_tracts:geo_id=13121010514",
                "a4i_health.v_tract_access:geo_id=13121010514",
            ],
            spatial_grain_disclosures=[
                "Tract prevalence values are CDC PLACES small-area modeled estimates.",
                "km_to_safety_net=18.5 km is straight-line upper-bound distance to federal facilities.",
            ],
            host_verified=False,
        ),
        ProposedClinicStop(
            stop_rank=3,
            assigned_saturday="2026-11-21",
            primary_tract_geoid="13121007602",
            covered_tract_geoids=["13121007602", "13121012000"],
            candidate_venue_name="Cleveland Avenue Branch Library (Provisional Host)",
            latitude=33.6812,
            longitude=-84.4510,
            catchment_radius_km=4.0,
            estimated_population_in_catchment=7820,
            score_breakdown=ScoreBreakdown(
                uninsured_norm=0.96,
                safety_net_distance_norm=0.30,
                no_vehicle_norm=0.64,
                chronic_respiratory_norm=0.90,
                checkup_preventive_gap_norm=0.90,
                saturday_transit_access_bonus=0.71,
                overlap_penalty=0.0,
                composite_need_score=0.75,
            ),
            plain_language_rationale=(
                "Tract 13121007602 has 25.6% uninsured adults 18-64 (PLACES modeled estimate), 30.8% routine checkup "
                "gap, 28.4% zero-vehicle households (SVI ACS), and 9.4 km straight-line distance to a safety-net clinic."
            ),
            evidence_citations=[
                "a4i_health.v_burden_tracts:geo_id=13121007602",
                "a4i_health.v_tract_access:geo_id=13121007602",
            ],
            spatial_grain_disclosures=[
                "Tract prevalence values are CDC PLACES modeled estimates.",
                "MARTA Saturday stop count (5 stops within 400m) measures stop presence, not door-to-door journey time.",
            ],
            host_verified=False,
        ),
        ProposedClinicStop(
            stop_rank=4,
            assigned_saturday="2026-11-28",
            primary_tract_geoid="13121011305",
            covered_tract_geoids=["13121011305"],
            candidate_venue_name="Hapeville / Southside Community Library (Provisional Host)",
            latitude=33.6310,
            longitude=-84.3820,
            catchment_radius_km=4.0,
            estimated_population_in_catchment=4890,
            score_breakdown=ScoreBreakdown(
                uninsured_norm=0.86,
                safety_net_distance_norm=0.36,
                no_vehicle_norm=0.56,
                chronic_respiratory_norm=0.88,
                checkup_preventive_gap_norm=0.85,
                saturday_transit_access_bonus=0.57,
                overlap_penalty=0.0,
                composite_need_score=0.71,
            ),
            plain_language_rationale=(
                "Tract 13121011305 has 23.5% uninsured adults 18-64 (PLACES modeled estimate), 30.2% routine checkup "
                "gap, 24.8% zero-vehicle households, and 11.2 km straight-line distance to the nearest federal safety-net clinic."
            ),
            evidence_citations=[
                "a4i_health.v_burden_tracts:geo_id=13121011305",
                "a4i_health.v_tract_access:geo_id=13121011305",
            ],
            spatial_grain_disclosures=[
                "Tract prevalence values are CDC PLACES modeled estimates.",
                "km_to_safety_net=11.2 km is straight-line upper-bound distance to federal facilities.",
            ],
            host_verified=False,
        ),
    ]

    runner_ups = [
        RunnerUpTractExplanation(
            tract_geoid="13121007808",
            need_rank=5,
            composite_need_score=0.74,
            deferral_reason_code="catchment_already_covered",
            covered_by_stop_rank=1,
            distance_to_nearest_selected_stop_km=2.1,
            technical_deferral_rationale=(
                "Tract 13121007808 ranks #5 in composite need (0.74) but sits 2.1 km from Stop #1 "
                "(13121010214), well inside Stop #1's 4.0 km catchment ring. Placing a second Saturday stop here "
                "would duplicate coverage rather than extending access to uncovered South Fulton tracts."
            ),
        ),
        RunnerUpTractExplanation(
            tract_geoid="13121008201",
            need_rank=6,
            composite_need_score=0.72,
            deferral_reason_code="inter_stop_separation_constraint",
            covered_by_stop_rank=1,
            distance_to_nearest_selected_stop_km=4.6,
            technical_deferral_rationale=(
                "Tract 13121008201 ranks #6 in composite need (0.72) but is 4.6 km from Stop #1 "
                "(below the 5.0 km minimum inter-stop separation threshold) and is 6.2 km from Family Health Centers "
                "of Georgia — Westside."
            ),
        ),
    ]

    return DraftPlan(
        county_fips=county_fips,
        strategy_used="balanced_uninsured_safety_net_gap",
        status="ok",
        revision_number=0,
        stops=stops,
        runner_up_tracts=runner_ups,
        sensitivity=SensitivitySummary(
            weight_perturbation_pct=15.0,
            top_4_stability_jaccard=0.88,
            borderline_tracts=["13121008201", "13121011000"],
            notes="Top-4 catchments remain stable (Jaccard=0.88) across +/-15% weight perturbations.",
        ),
        planner_notes=[
            "All 4 stops selected via deterministic race-blind greedy maximum-coverage optimizer.",
            "pct_checkup inverted as 100 - pct_checkup before normalization.",
        ],
    )


def build_mock_audit_report() -> AuditReport:
    return AuditReport(
        revision_audited=0,
        verdict=AuditVerdict.APPROVED,
        non_demographic_defects=[],
        demographic_impact=DemographicImpactComparison(
            county_total_pop=50548,
            catchment_total_pop=29998,
            county_svi_theme3_mean=0.74,
            catchment_svi_theme3_mean=0.88,
            group_comparisons={
                "black": {"county_pct": 69.8, "catchment_pct": 81.9, "parity_ratio": 1.17},
                "hispanic": {"county_pct": 9.6, "catchment_pct": 11.4, "parity_ratio": 1.19},
                "minority_overall": {"county_pct": 82.1, "catchment_pct": 94.3, "parity_ratio": 1.15},
            },
            disparity_findings=[
                "Post-hoc equity check passed: race-blind structural siting covers underserved minority tracts at 1.15x county baseline parity.",
            ],
            requires_human_equity_review=False,
        ),
        auditor_summary=(
            "APPROVED: All 4 proposed stops satisfy >= 5.0 km separation, invert pct_checkup properly, "
            "cite spatial grain limits (4-county HSA vs tract), include runner-up deferral explanations, "
            "and pass post-hoc demographic parity review."
        ),
        limitations_attached=[
            "Distances are straight-line upper bounds to federally recognized sites inside Fulton County.",
            "All host venues remain provisional (host_verified=False) pending field operations confirmation.",
        ],
    )


def build_mock_outreach_messages() -> OutreachMessages:
    return OutreachMessages(
        county_name="Fulton",
        stop_notices=[
            StopOutreachDraft(
                stop_rank=1,
                assigned_saturday="2026-11-07",
                candidate_venue_name="Adamsville-Collier Heights Branch Library (Provisional Host)",
                english_notice=(
                    "PROPOSED LOCATION — Pending host site confirmation before public release: "
                    "Free Saturday mobile health checkups (blood pressure, diabetes, asthma, and routine care) "
                    "proposed near Adamsville-Collier Heights Library on Saturday, Nov 7."
                ),
                spanish_notice=(
                    "UBICACIÓN PROPUESTA — Pendiente de confirmación del sitio antes del anuncio público: "
                    "Chequeos médicos gratuitos los sábados (presión arterial, diabetes, asma y cuidado preventivo) "
                    "propuestos cerca de la Biblioteca Adamsville-Collier Heights el sábado 7 de noviembre."
                ),
                why_chosen_explanation=(
                    "Chosen because many neighbors here do not have a car (43%) and the nearest sliding-scale "
                    "clinic is over 8 km away."
                ),
                provisional_disclaimer_included=True,
            ),
        ],
        unpicked_neighborhood_explanations=[
            UnpickedNeighborhoodExplanation(
                tract_geoid="13121007808",
                need_rank=5,
                nearest_selected_stop_rank=1,
                distance_to_selected_stop_km=2.1,
                english_explanation=(
                    "We know your neighborhood has high health care need (#5 in Fulton County). Because we only have "
                    "four Saturdays this month, we placed Stop #1 just 2.1 km away at Adamsville-Collier Heights "
                    "Library so one stop can serve both neighborhoods without overlapping two vans in the same area."
                ),
                spanish_explanation=(
                    "Sabemos que su vecindario tiene una alta necesidad de salud (#5 en el condado de Fulton). "
                    "Como solo tenemos cuatro sábados este mes, ubicamos la Parada #1 a solo 2.1 km en la Biblioteca "
                    "Adamsville-Collier Heights para servir a ambos vecindarios."
                ),
            ),
        ],
        regional_surveillance_note_en=(
            "Note: Weekly respiratory virus updates (flu, COVID-19, RSV) are tracked across the 4-county Atlanta "
            "Health Service Area, not by individual neighborhood."
        ),
        regional_surveillance_note_es=(
            "Nota: Las actualizaciones semanales de virus respiratorios (gripe, COVID-19, VRS) se miden en el "
            "Área de Servicio de Salud de 4 condados de Atlanta, no por vecindario individual."
        ),
    )


def build_mock_plan_response() -> PlanResponse:
    draft = build_mock_draft_plan()
    return PlanResponse(
        request_id="req-mock-13121",
        status="provisional_approved",
        needs_human_review=False,
        county_fips="13121",
        county_name="Fulton",
        final_plan=draft,
        audit_report=build_mock_audit_report(),
        revision_history=[draft],
        evidence_report=build_mock_evidence_report(),
        outreach=build_mock_outreach_messages(),
        provenance=[
            "a4i_health.v_burden_tracts",
            "a4i_health.v_tract_access",
            "a4i_health.v_care_sites",
            "a4i_health.v_shortage_areas",
            "a4i_health.v_shortage_facilities",
            "a4i_health.v_exposure_tracts",
            "a4i_health.v_disease_weekly",
        ],
        limitations=[
            "All 4 proposed stops are PROVISIONAL until host site agreements and parking permits are confirmed.",
            "km_to_any_care and km_to_safety_net are straight-line upper-bound distances to federal facilities.",
        ],
        data_availability={
            "v_burden_tracts": True,
            "v_tract_access": True,
            "v_care_sites": True,
            "v_shortage_areas": True,
            "v_shortage_facilities": True,
            "v_exposure_tracts": True,
            "v_disease_weekly": True,
            "marta_gtfs": True,
            "usda_food_access": True,
            "imls_candidate_venues": True,
        },
        telemetry_summary={
            "request_id": "req-mock-13121",
            "total_agent_invocations": 6,
            "total_tokens": 0,
        },
    )
