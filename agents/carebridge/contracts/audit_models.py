"""Audit models for the Independent Equity & Rigor Auditor Agent."""

from __future__ import annotations

from enum import Enum
from typing import Dict, List
from carebridge._compat import BaseModel, Field


class AuditVerdict(str, Enum):
    APPROVED = "approved"
    REJECTED_REVISION_REQUIRED = "rejected_revision_required"
    NEEDS_HUMAN_REVIEW = "needs_human_review"


class DefectCategory(str, Enum):
    CATCHMENT_OVERLAP = "catchment_overlap"
    UNSUPPORTED_GRAIN_CLAIM = "unsupported_grain_claim"
    MISSING_CORE_EVIDENCE = "missing_core_evidence"
    INFEASIBLE_HOST_OR_TRANSIT = "infeasible_host_or_transit"
    SENSITIVITY_INSTABILITY = "sensitivity_instability"


class NonDemographicAuditDefect(BaseModel):
    """Safe to return to Siting Planner Agent during bounded revision (Demographic Diode)."""

    defect_id: str
    category: DefectCategory
    affected_stop_ranks: List[int]
    affected_tract_geoids: List[str] = Field(default_factory=list)
    description: str
    remediation_instruction: str


class DemographicImpactComparison(BaseModel):
    """VISIBLE TO AUDITOR & HUMAN REVIEWERS ONLY. NEVER SENT BACK TO PLANNER."""

    county_total_pop: int
    catchment_total_pop: int
    county_svi_theme3_mean: float = Field(..., ge=0.0, le=1.0)
    catchment_svi_theme3_mean: float = Field(..., ge=0.0, le=1.0)
    group_comparisons: Dict[str, Dict[str, float]] = Field(
        default_factory=dict,
        description="Group -> {'county_pct': x, 'catchment_pct': y, 'parity_ratio': y/x}",
    )
    disparity_findings: List[str] = Field(default_factory=list)
    requires_human_equity_review: bool = False


class AuditReport(BaseModel):
    revision_audited: int = Field(..., ge=0, le=1)
    verdict: AuditVerdict
    non_demographic_defects: List[NonDemographicAuditDefect] = Field(default_factory=list)
    demographic_impact: DemographicImpactComparison
    auditor_summary: str
    limitations_attached: List[str] = Field(default_factory=list)
