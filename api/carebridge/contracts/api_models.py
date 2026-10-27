"""API request/response models for the FastAPI Gateway (`POST /v1/plan`)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from carebridge._compat import BaseModel, Field
from carebridge.contracts.audit_models import AuditReport
from carebridge.contracts.evidence_models import EvidenceReport
from carebridge.contracts.outreach_models import OutreachMessages
from carebridge.contracts.plan_models import DraftPlan


class PlanRequest(BaseModel):
    county_fips: str = Field(default="13121", pattern=r"^\d{5}$")
    county_name: str = Field(default="Fulton", min_length=2, max_length=64)
    state_abbr: str = Field(default="GA", pattern=r"^[A-Z]{2}$")
    saturdays: List[str] = Field(
        default_factory=lambda: ["2026-11-07", "2026-11-14", "2026-11-21", "2026-11-28"],
        min_length=4,
        max_length=4,
    )
    strategy: str = Field(
        default="balanced_uninsured_safety_net_gap",
        pattern=r"^(balanced_uninsured_safety_net_gap|chronic_respiratory_focus|zero_vehicle_transit_priority)$",
    )
    include_optional_datasets: bool = True
    simulate_first_draft_defect: bool = Field(
        default=False,
        description="Demo toggle: forces an overlapping catchment in draft 0 so Auditor rejects and triggers 1 revision.",
    )


class PlanResponse(BaseModel):
    request_id: str
    status: str = Field(..., pattern=r"^(provisional_approved|needs_human_review|error)$")
    needs_human_review: bool
    county_fips: str
    county_name: str
    final_plan: Optional[DraftPlan] = None
    audit_report: Optional[AuditReport] = None
    revision_history: List[DraftPlan] = Field(default_factory=list)
    evidence_report: Optional[EvidenceReport] = None
    outreach: Optional[OutreachMessages] = None
    provenance: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    data_availability: Dict[str, bool] = Field(default_factory=dict)
    telemetry_summary: Dict[str, Any] = Field(default_factory=dict)
