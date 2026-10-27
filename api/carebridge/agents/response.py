"""Final session.state → PlanResponse (plan 10's response builder)."""
from typing import Any

from ..contracts.api_models import PlanRequest, PlanResponse
from ..contracts.audit_models import AuditReport, AuditVerdict
from ..contracts.evidence_models import EvidenceReport, MobilityEvidence
from ..contracts.outreach_models import OutreachMessages
from ..contracts.plan_models import DraftPlan
from ..contracts.state_keys import (
    STATE_AUDIT_REPORT,
    STATE_EVIDENCE_REPORT,
    STATE_FINAL_PLAN,
    STATE_MOBILITY_EVIDENCE,
    STATE_OUTREACH_MESSAGES,
    STATE_REVISION_HISTORY,
)

LIMITATIONS = [
    "Bus travel time: no license-clean federal dataset exists; distances are straight-line upper bounds.",
    "Free and county clinics: no national list exists. Facility layers are federal only (CMS + HRSA).",
    "Pharmacies: excluded. NPPES carries practitioner names and home addresses.",
    "Other mobile clinics: the one national registry has no license or bulk download; not scraped.",
    "How many people have asthma: unknown. CDC PLACES gives modeled prevalence, not counts.",
    "Is COVID rising in this neighborhood: unanswerable. disease_weekly is a 4-county HSA figure.",
    "Which specific people are unmanaged: none, by design. Individual-level data is prohibited.",
]


def build_plan_response(request_id: str, req: PlanRequest, state: dict[str, Any], elapsed_ms: float,
                        model: str) -> PlanResponse:
    def get(key, model_cls):
        v = state.get(key)
        return None if v is None else model_cls.model_validate(v)

    final = get(STATE_FINAL_PLAN, DraftPlan)
    audit = get(STATE_AUDIT_REPORT, AuditReport)
    evidence = get(STATE_EVIDENCE_REPORT, EvidenceReport)
    mobility = get(STATE_MOBILITY_EVIDENCE, MobilityEvidence)
    history = [DraftPlan.model_validate(d) for d in state.get(STATE_REVISION_HISTORY) or []]

    if final is None or evidence is None or not evidence.core_tables_ready:
        status = "error"
    elif audit is not None and (audit.verdict == AuditVerdict.NEEDS_HUMAN_REVIEW
                                or audit.demographic_impact.requires_human_equity_review):
        status = "needs_human_review"
    else:
        status = "provisional_approved"
    return PlanResponse(
        request_id=request_id, status=status,
        needs_human_review=status != "provisional_approved" or any(not s.host_verified for s in (final.stops if final else [])),
        county_fips=req.county_fips, county_name=req.county_name,
        final_plan=final, audit_report=audit, revision_history=history, evidence_report=evidence,
        outreach=get(STATE_OUTREACH_MESSAGES, OutreachMessages),
        provenance=["a4i_health.burden_tracts", "a4i_health.tract_access", "a4i_health.care_sites",
                    "a4i_health.disease_weekly", "a4i_health.shortage_areas",
                    "bigquery-public-data.census_bureau_acs.censustract_2020_5yr (auditor only)"],
        limitations=LIMITATIONS,
        data_availability={
            "a4i_health_core": bool(evidence and evidence.core_tables_ready),
            "marta_gtfs_saturday": bool(mobility and mobility.marta_gtfs_available),
            "usda_food_access": bool(mobility and mobility.usda_food_access_available),
            "imls_candidate_venues": bool(mobility and mobility.imls_venues_available),
            "external_demographic_audit": audit is not None,
        },
        telemetry_summary={"source": "adk", "model": model, "iterations": len(history),
                           "elapsed_ms": round(elapsed_ms)},
    )
