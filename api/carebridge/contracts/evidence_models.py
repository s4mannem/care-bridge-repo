"""Evidence models for Health & Access Agent, Transit & Community Agent, and Evidence Validator."""

from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional
from carebridge._compat import BaseModel, Field


class SpatialGrain(str, Enum):
    TRACT = "census_tract_11char"
    GRID_12KM = "epa_12km_grid_on_tract_id"
    FACILITY_POINT = "facility_lon_lat_point"
    SHORTAGE_POLYGON = "hrsa_mixed_grain_component"
    MULTI_COUNTY_HSA = "multi_county_health_service_area"


class DataEstimateKind(str, Enum):
    MODELED_SMALL_AREA = "modeled_small_area_estimate"
    SURVEY_ESTIMATE = "acs_5yr_survey_estimate"
    ADMINISTRATIVE_REGISTRY = "federal_registry_point"
    SYNDROMIC_SURVEILLANCE = "nssp_weekly_ed_percentage"
    SCHEDULED_TRANSIT = "gtfs_static_saturday_schedule"


class TractHealthRecord(BaseModel):
    geo_id: str = Field(..., min_length=11, max_length=11, description="11-char Census Tract FIPS")
    total_pop: int = Field(..., ge=0)
    latitude: Optional[float] = Field(None, ge=17.0, le=72.0)
    longitude: Optional[float] = Field(None, ge=-180.0, le=-60.0)
    # PLACES (18-64 uninsured) vs SVI (all ages uninsured)
    pct_uninsured_18_64: Optional[float] = Field(None, ge=0.0, le=100.0)
    pct_uninsured_all_ages: Optional[float] = Field(None, ge=0.0, le=100.0)
    uninsured_age_structure_gap: Optional[float] = None
    pct_asthma: Optional[float] = Field(None, ge=0.0, le=100.0)
    pct_copd: Optional[float] = Field(None, ge=0.0, le=100.0)
    pct_diabetes: Optional[float] = Field(None, ge=0.0, le=100.0)
    pct_bphigh: Optional[float] = Field(None, ge=0.0, le=100.0)
    pct_checkup: Optional[float] = Field(
        None,
        ge=0.0,
        le=100.0,
        description="PLACES routine checkup prevalence (LOW is bad; invert as 100 - pct_checkup before ranking).",
    )
    pct_checkup_gap: Optional[float] = Field(
        None,
        ge=0.0,
        le=100.0,
        description="Inverted preventive gap: 100.0 - pct_checkup (HIGH is bad, aligned with other burden measures).",
    )
    pct_uninsured_18_64_ci_width: Optional[float] = Field(
        None,
        ge=0.0,
        description="PLACES 95% confidence interval width (_crude95ci) for ranking uncertainty checks.",
    )
    pct_no_vehicle: Optional[float] = Field(None, ge=0.0, le=100.0)
    pct_age_65_plus: Optional[float] = Field(None, ge=0.0, le=100.0)
    pct_mobility_difficulty: Optional[float] = Field(None, ge=0.0, le=100.0)
    pct_lack_transport: Optional[float] = Field(None, ge=0.0, le=100.0)
    # Straight-line upper-bound distances from tract_access (federal sites only)
    km_to_any_care: Optional[float] = Field(None, ge=0.0)
    km_to_safety_net: Optional[float] = Field(None, ge=0.0)
    extra_km_if_uninsured: Optional[float] = None
    cross_border_state_care_km: Optional[float] = Field(
        None,
        ge=0.0,
        description="Distance to nearest facility in care_sites_state across county lines.",
    )
    # Air tail exposure (days > 20 ug/m3, NOT mean PM2.5 ranking)
    pm25_days_over_20: Optional[int] = Field(None, ge=0)
    mean_pm25_12km_caveat: Optional[float] = Field(None, ge=0.0)


class RegionalDiseaseSignal(BaseModel):
    hsa_name: str
    hsa_counties: str
    spatial_grain: SpatialGrain = SpatialGrain.MULTI_COUNTY_HSA
    latest_week_end: Optional[str] = None
    percent_visits_covid: Optional[float] = None
    percent_visits_influenza: Optional[float] = None
    percent_visits_rsv: Optional[float] = None
    ed_trends_covid: Optional[str] = None
    ed_trends_influenza: Optional[str] = None
    ed_trends_rsv: Optional[str] = None
    data_unavailable: bool = False
    grain_warning: str = (
        "NSSP ED visits are reported at the multi-county Health Service Area (HSA) level, "
        "NEVER at the census tract or neighborhood level."
    )


class HealthEvidence(BaseModel):
    county_fips: str = Field(..., pattern=r"^\d{5}$")
    county_name: str
    tracts: List[TractHealthRecord]
    care_sites_count: int = Field(..., ge=0)
    safety_net_sites_count: int = Field(..., ge=0)
    shortage_areas_count: int = Field(..., ge=0)
    shortage_facilities_count: int = Field(..., ge=0)
    max_hpsa_score: Optional[float] = Field(None, ge=0.0, le=25.0)
    regional_disease: RegionalDiseaseSignal
    source_lineage: List[str] = Field(default_factory=list)
    missingness_flags: List[str] = Field(default_factory=list)


class CandidateHostVenue(BaseModel):
    venue_id: str
    venue_name: str
    venue_kind: str = Field(..., description="e.g., Library (IMLS), Community Center, MARTA Station Lot")
    geo_id: str = Field(..., min_length=11, max_length=11)
    latitude: float = Field(..., ge=17.0, le=72.0)
    longitude: float = Field(..., ge=-180.0, le=-60.0)
    saturday_transit_stops_within_400m: int = Field(0, ge=0)
    saturday_trips_per_hour: Optional[float] = Field(None, ge=0.0)
    host_permission_verified: bool = Field(
        default=False,
        description="Must remain False until human field ops confirms venue agreement.",
    )


class TractMobilityRecord(BaseModel):
    geo_id: str = Field(..., min_length=11, max_length=11)
    saturday_active_stops_count: int = Field(0, ge=0)
    saturday_mean_headway_min: Optional[float] = None
    usda_low_income_low_access: Optional[bool] = None
    candidate_venues: List[CandidateHostVenue] = Field(default_factory=list)


class MobilityEvidence(BaseModel):
    county_fips: str = Field(..., pattern=r"^\d{5}$")
    marta_gtfs_available: bool = False
    usda_food_access_available: bool = False
    imls_venues_available: bool = False
    tract_mobility: List[TractMobilityRecord] = Field(default_factory=list)
    caveats: List[str] = Field(
        default_factory=lambda: [
            "A nearby Saturday bus stop measures stop presence, not door-to-door clinic journey time."
        ]
    )


class ValidationCheckItem(BaseModel):
    check_name: str
    verdict: str = Field(..., pattern=r"^(PASS|WARN|FAIL)$")
    detail: str
    is_pipeline_check: bool = True


class EvidenceReport(BaseModel):
    county_fips: str
    core_tables_ready: bool
    blocking_failures: List[str] = Field(default_factory=list)
    checks: List[ValidationCheckItem] = Field(default_factory=list)
    validated_tract_count: int = 0
    prohibited_claims_blocked: List[str] = Field(default_factory=list)
    optional_datasets_status: Dict[str, str] = Field(default_factory=dict)
    caveats: List[str] = Field(default_factory=list)
