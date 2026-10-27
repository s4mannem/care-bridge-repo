"""The agent run as a sequence of `AgentEvent`s, derived from a finished PlanResponse.

The stub runner streams these with their original pacing, and
`ui/scripts/build_mock.py` writes them next to the recorded plans for the
offline UI build. The ADK runner will emit real events from its telemetry
plugin instead, in the same shape.
"""
import math

from ..contracts.api_models import PlanRequest, PlanResponse
from ..contracts.interaction_models import AgentEvent
from ..contracts.plan_models import DraftPlan, ProposedClinicStop

MIN_SEPARATION_KM = 5.0
STRATEGY_LABELS = {
    "balanced_uninsured_safety_net_gap": "Balanced",
    "chronic_respiratory_focus": "Chronic & respiratory",
    "zero_vehicle_transit_priority": "No car",
}


def haversine_km(a: ProposedClinicStop, b: ProposedClinicStop) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a.latitude, a.longitude, b.latitude, b.longitude))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def overlap_pair(draft: DraftPlan) -> tuple[ProposedClinicStop, ProposedClinicStop, float] | None:
    """Closest pair of stops closer than the minimum separation, if any."""
    pairs = [(a, b, haversine_km(a, b)) for i, a in enumerate(draft.stops) for b in draft.stops[i + 1:]]
    close = [p for p in pairs if p[2] < MIN_SEPARATION_KM]
    return min(close, key=lambda p: p[2]) if close else None


def tract_label(geo_id: str) -> str:
    code = geo_id[5:]
    return f"Tract {int(code[:4])}" + (f".{code[4:]}" if code[4:] != "00" else "")


def build_trace(r: PlanResponse, req: PlanRequest) -> list[AgentEvent]:
    out: list[AgentEvent] = []
    t = 0

    def add(gap: int, agent: str, kind: str, message: str, **kw) -> None:
        nonlocal t
        t += gap
        out.append(AgentEvent(t_ms=t, agent=agent, kind=kind, message=message, **kw))

    def names(d: DraftPlan) -> str:
        return ", ".join(tract_label(s.primary_tract_geoid) for s in d.stops)

    ev = r.evidence_report
    add(0, "coordinator", "start",
        f"POST /v1/plan · {r.county_name} · {STRATEGY_LABELS.get(req.strategy, req.strategy)}"
        + (" · simulate draft-0 defect" if req.simulate_first_draft_defect else ""),
        state_key="plan_request")
    add(400, "health_access", "start", "Querying burden_tracts + tract_access via BigQuery MCP", parallel=True)
    marta = r.data_availability.get("marta_gtfs_saturday", False)
    status = (ev.optional_datasets_status.get("marta_gtfs") if ev else None) or "unavailable"
    add(0, "transit_community", "start" if marta else "skip",
        "Querying MARTA Saturday service" if marta else f"MARTA GTFS {status}",
        parallel=True, state_key=None if marta else "mobility_evidence")
    add(1200, "health_access", "state_write",
        f"{ev.validated_tract_count if ev else 0} tracts with burden and two distances",
        parallel=True, state_key="health_evidence")

    add(500, "evidence_validator", "start", "Checking grain, inversion and leakage on every input")
    for c in (ev.checks if ev else []):
        if c.verdict != "PASS":
            add(500, "evidence_validator", "finding", f"{c.verdict} {c.check_name}: {c.detail}")
    passes = sum(c.verdict == "PASS" for c in ev.checks) if ev else 0
    add(400, "evidence_validator", "state_write",
        f"{passes} checks passed · core tables {'ready' if ev and ev.core_tables_ready else 'NOT ready'}",
        state_key="evidence_report")

    for i, d in enumerate(r.revision_history):
        last = i == len(r.revision_history) - 1
        add(600, "siting_planner", "start",
            f"Race-blind planning · {STRATEGY_LABELS.get(d.strategy_used, d.strategy_used)} weights" if i == 0
            else "Revising with non_demographic_feedback only")
        add(800, "optimizer", "tool", f"optimize_four_clinic_stops(revision={d.revision_number})")
        add(500, "siting_planner", "state_write", f"Draft {d.revision_number}: {names(d)}",
            state_key="draft_plan", draft_index=i, draft=d)
        if not last:
            add(700, "equity_auditor", "start", f"Auditing draft {d.revision_number} (no access to planner reasoning)")
            pair = overlap_pair(d)
            add(1200, "equity_auditor", "verdict",
                f"REJECT: defects found in draft {d.revision_number}" if pair is None else
                f"REJECT: stops {pair[0].stop_rank} and {pair[1].stop_rank} are {pair[2]:.1f} km apart, "
                f"so their {pair[0].catchment_radius_km:.0f} km catchments overlap.",
                verdict="reject", draft_index=i, state_key="revision_required",
                conflict_ranks=None if pair is None else [pair[0].stop_rank, pair[1].stop_rank])
            add(200, "equity_auditor", "state_write", "CATCHMENT_OVERLAP sent back; no demographic fields",
                state_key="non_demographic_feedback")

    audit = r.audit_report
    if audit is not None:
        add(700, "equity_auditor", "start",
            f"Auditing draft {audit.revision_audited} + post-hoc ACS comparison (auditor only)")
        for f in audit.demographic_impact.disparity_findings:
            add(600, "equity_auditor", "finding", f"PARITY {f}")
        verdict = audit.verdict.value if hasattr(audit.verdict, "value") else str(audit.verdict)
        label = "APPROVED" if verdict == "approved" else verdict.upper().replace("_", " ")
        add(600, "equity_auditor", "verdict", f"{label}: {audit.auditor_summary.split('. ')[0]}.",
            verdict=verdict, state_key="audit_report")
    add(200, "coordinator", "state_write",
        f"final_plan · status={r.status} · needs_human_review={str(r.needs_human_review).lower()}",
        state_key="final_plan")
    if r.outreach is not None:
        add(600, "communications", "start", "Drafting EN/ES notices from final_plan only")
        add(1400, "communications", "state_write",
            f"{len(r.outreach.stop_notices)} stop notices · "
            f"{len(r.outreach.unpicked_neighborhood_explanations)} \"why not here\" notes",
            state_key="outreach_messages")
    add(300, "coordinator", "done",
        "Plan ready, pending human review" if r.needs_human_review else "Plan ready")
    return out
