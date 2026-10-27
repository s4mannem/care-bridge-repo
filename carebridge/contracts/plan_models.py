"""Siting plan models for the Four-Stop Coverage Optimizer and Siting Planner Agent."""

from __future__ import annotations

from typing import List, Optional
from carebridge._compat import BaseModel, Field


class ScoreBreakdown(BaseModel):
    uninsured_norm: float = Field(..., ge=0.0, le=1.0)
    safety_net_distance_norm: float = Field(..., ge=0.0, le=1.0)
    no_vehicle_norm: float = Field(..., ge=0.0, le=1.0)
    chronic_respiratory_norm: float = Field(..., ge=0.0, le=1.0)
    checkup_preventive_gap_norm: float = Field(
        0.0,
        ge=0.0,
        le=1.0,
        description="Normalized (100 - pct_checkup): low routine checkup rate inverted so high = high need.",
    )
    saturday_transit_access_bonus: float = Field(0.0, ge=0.0, le=1.0)
    overlap_penalty: float = Field(0.0, ge=0.0, le=1.0)
    composite_need_score: float = Field(..., ge=0.0, le=1.0)


class ProposedClinicStop(BaseModel):
    stop_rank: int = Field(..., ge=1, le=4)
    assigned_saturday: str = Field(..., description="ISO date YYYY-MM-DD for the Saturday")
    primary_tract_geoid: str = Field(..., min_length=11, max_length=11)
    covered_tract_geoids: List[str] = Field(..., min_length=1)
    candidate_venue_name: str
    latitude: float = Field(..., ge=17.0, le=72.0)
    longitude: float = Field(..., ge=-180.0, le=-60.0)
    catchment_radius_km: float = Field(default=4.0, ge=0.0)
    estimated_population_in_catchment: int = Field(..., ge=0)
    score_breakdown: ScoreBreakdown
    plain_language_rationale: str = Field(
        ...,
        description="Analytical, source-cited, resolution-qualified rationale for the outreach lead (NOT flyer copy).",
    )
    evidence_citations: List[str] = Field(..., min_length=1)
    spatial_grain_disclosures: List[str] = Field(..., min_length=1)
    host_verified: bool = False
    provisional_warning: str = (
        "PROVISIONAL SITE: Host permission, parking pad clearance, and Saturday staffing "
        "must be confirmed by field operations before public announcement."
    )


class RunnerUpTractExplanation(BaseModel):
    """Answers Question 7: 'How do I tell the neighborhood we didn't pick why we didn't pick them?'"""

    tract_geoid: str = Field(..., min_length=11, max_length=11)
    need_rank: int = Field(..., ge=5, description="County-wide composite need rank (e.g., #5-#8)")
    composite_need_score: float = Field(..., ge=0.0, le=1.0)
    deferral_reason_code: str = Field(
        ...,
        pattern=r"^(catchment_already_covered|inter_stop_separation_constraint|no_saturday_transit_or_venue|lower_marginal_coverage)$",
    )
    covered_by_stop_rank: Optional[int] = Field(
        None,
        ge=1,
        le=4,
        description="Which selected stop (1-4) already covers or sits within 5 km of this tract",
    )
    distance_to_nearest_selected_stop_km: float = Field(..., ge=0.0)
    technical_deferral_rationale: str = Field(
        ...,
        description="Analytical, cited explanation of why this high-need tract was not assigned one of the 4 stops.",
    )


class SensitivitySummary(BaseModel):
    weight_perturbation_pct: float = 15.0
    top_4_stability_jaccard: float = Field(..., ge=0.0, le=1.0)
    borderline_tracts: List[str] = Field(default_factory=list)
    notes: str


class DraftPlan(BaseModel):
    county_fips: str
    strategy_used: str
    status: str = Field(..., pattern=r"^(ok|insufficient_candidates)$")
    revision_number: int = Field(0, ge=0, le=1)
    stops: List[ProposedClinicStop] = Field(default_factory=list)
    runner_up_tracts: List[RunnerUpTractExplanation] = Field(
        default_factory=list,
        description="High-need runner-up tracts (#5-#8) with explicit deferral rationales.",
    )
    sensitivity: Optional[SensitivitySummary] = None
    planner_notes: List[str] = Field(default_factory=list)
