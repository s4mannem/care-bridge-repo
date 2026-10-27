"""Programmatic ADK Runner and PlanResponse assembler for the CareBridge AI Coordinator."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Dict, List, Optional

from carebridge.agents.coordinator.exit_gate import compute_needs_human_review
from carebridge.agents.coordinator.workflow import build_carebridge_coordinator_workflow
from carebridge.contracts.api_models import PlanRequest, PlanResponse
from carebridge.contracts.audit_models import AuditReport
from carebridge.contracts.evidence_models import EvidenceReport, MobilityEvidence
from carebridge.contracts.outreach_models import OutreachMessages
from carebridge.contracts.plan_models import DraftPlan
from carebridge.contracts.state_keys import (
    STATE_AUDIT_REPORT,
    STATE_DRAFT_PLAN,
    STATE_EVIDENCE_REPORT,
    STATE_FINAL_PLAN,
    STATE_MOBILITY_EVIDENCE,
    STATE_OUTREACH_MESSAGES,
    STATE_PLAN_REQUEST,
    STATE_REQUEST_ID,
    STATE_REVISION_HISTORY,
)
from carebridge.security.race_blind_guard import assert_no_pii_in_payload
from carebridge.telemetry.adk_telemetry_plugin import CareBridgeTelemetryPlugin
from carebridge.telemetry.otel import (
    record_structured_log,
    set_current_request_id,
    trace_span,
)

try:
    from google.adk.runners import InMemoryRunner  # type: ignore
    from google.adk.sessions import InMemorySessionService  # type: ignore
except ImportError:  # pragma: no cover
    from carebridge.agents.health_agent.agent import (  # type: ignore
        InMemoryRunner,
        InMemorySessionService,
    )


def _dedupe_preserve_order(items: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for item in items:
        cleaned = str(item).strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            out.append(cleaned)
    return out


def _assemble_provenance(
    final_plan: Optional[DraftPlan],
    evidence_report: Optional[EvidenceReport],
) -> List[str]:
    citations: List[str] = [
        "a4i_health.v_burden_tracts (CDC PLACES + CDC SVI non-racial socioeconomic/mobility indicators, 11-char tract grain)",
        "a4i_health.v_tract_access (Straight-line upper-bound distances to federally recognized care sites, 11-char tract grain)",
        "a4i_health.v_care_sites (HRSA FQHC & federal safety-net facility points, admin contact PII excluded)",
        "a4i_health.v_shortage_areas (HRSA HPSA designation polygons/records)",
        "a4i_health.v_shortage_facilities (HRSA HPSA point-designated safety-net facilities)",
        "a4i_health.v_exposure_tracts (EPA 12km grid PM2.5 contextual exposure surface)",
        "a4i_health.v_disease_weekly (CDC NSSP 4-county Atlanta Health Service Area weekly respiratory ED trends)",
        "external.v_posthoc_demographic_audit (Protected post-hoc demographic parity audit view — Auditor boundary only)",
    ]
    if evidence_report is not None:
        if evidence_report.optional_datasets_status.get("marta_gtfs") == "available":
            citations.append(
                "marta_gtfs.v_tract_saturday_transit_access (MARTA GTFS Saturday active stop & route frequency view)"
            )
        if evidence_report.optional_datasets_status.get("usda_food_access") == "available":
            citations.append(
                "usda_fara.v_tract_food_access (USDA Food Access Research Atlas low-access/low-vehicle tract flags)"
            )
        if evidence_report.optional_datasets_status.get("imls_libraries") == "available":
            citations.append(
                "imls_pls.v_candidate_host_venues (IMLS Public Libraries Survey & community facility candidate host points)"
            )
    if final_plan is not None:
        for stop in final_plan.stops:
            citations.extend(stop.evidence_citations)
    return _dedupe_preserve_order(citations)


def _assemble_limitations(
    final_plan: Optional[DraftPlan],
    evidence_report: Optional[EvidenceReport],
    audit_report: Optional[AuditReport],
) -> List[str]:
    items: List[str] = []
    if evidence_report is not None:
        items.extend(evidence_report.caveats)
    if audit_report is not None:
        items.extend(audit_report.limitations_attached)
    if final_plan is not None:
        for stop in final_plan.stops:
            if stop.provisional_warning:
                items.append(stop.provisional_warning)
    items.append(
        "All 4 proposed Saturday mobile clinic stops are PROVISIONAL (host_verified=False) until field operations confirm host permission, parking pad clearance, and Saturday clinical staffing."
    )
    return _dedupe_preserve_order(items)


def _assemble_data_availability(
    state: Dict[str, Any],
    evidence_report: Optional[EvidenceReport],
) -> Dict[str, bool]:
    core_ready = bool(evidence_report.core_tables_ready) if evidence_report is not None else True
    opt_status = evidence_report.optional_datasets_status if evidence_report is not None else {}

    raw_mob = state.get(STATE_MOBILITY_EVIDENCE)
    marta_ready = opt_status.get("marta_gtfs") == "available"
    usda_ready = opt_status.get("usda_food_access") == "available"
    imls_ready = opt_status.get("imls_libraries") == "available"
    if isinstance(raw_mob, MobilityEvidence):
        marta_ready = bool(raw_mob.marta_saturday_ready)
        usda_ready = bool(raw_mob.usda_food_access_ready)
        imls_ready = bool(raw_mob.imls_venues_ready)
    elif isinstance(raw_mob, dict):
        marta_ready = bool(raw_mob.get("marta_saturday_ready", marta_ready))
        usda_ready = bool(raw_mob.get("usda_food_access_ready", usda_ready))
        imls_ready = bool(raw_mob.get("imls_venues_ready", imls_ready))

    return {
        "burden_tracts": core_ready,
        "tract_access": core_ready,
        "care_sites": core_ready,
        "shortage_areas": core_ready,
        "shortage_facilities": core_ready,
        "exposure_tracts": core_ready,
        "disease_weekly": core_ready,
        "marta_gtfs": marta_ready,
        "usda_food_access": usda_ready,
        "imls_libraries": imls_ready,
    }


def assemble_plan_response_from_state(
    request: PlanRequest,
    state: Dict[str, Any],
    request_id: Optional[str] = None,
) -> PlanResponse:
    """Assembles and validates a `PlanResponse` from completed Coordinator `session.state`."""
    resolved_req_id = str(
        request_id or state.get(STATE_REQUEST_ID) or f"req-{uuid.uuid4().hex[:12]}"
    )

    raw_final = state.get(STATE_FINAL_PLAN) or state.get(STATE_DRAFT_PLAN)
    final_plan: Optional[DraftPlan] = None
    if raw_final is not None:
        final_plan = (
            raw_final
            if isinstance(raw_final, DraftPlan)
            else DraftPlan.model_validate(raw_final)
        )

    raw_audit = state.get(STATE_AUDIT_REPORT)
    audit_report: Optional[AuditReport] = None
    if raw_audit is not None:
        audit_report = (
            raw_audit
            if isinstance(raw_audit, AuditReport)
            else AuditReport.model_validate(raw_audit)
        )

    raw_history = state.get(STATE_REVISION_HISTORY) or []
    revision_history: List[DraftPlan] = [
        item if isinstance(item, DraftPlan) else DraftPlan.model_validate(item)
        for item in raw_history
    ]
    if not revision_history and final_plan is not None:
        revision_history = [final_plan]

    raw_ev = state.get(STATE_EVIDENCE_REPORT)
    evidence_report: Optional[EvidenceReport] = None
    if raw_ev is not None:
        evidence_report = (
            raw_ev
            if isinstance(raw_ev, EvidenceReport)
            else EvidenceReport.model_validate(raw_ev)
        )

    raw_outreach = state.get(STATE_OUTREACH_MESSAGES)
    outreach: Optional[OutreachMessages] = None
    if raw_outreach is not None:
        outreach = (
            raw_outreach
            if isinstance(raw_outreach, OutreachMessages)
            else OutreachMessages.model_validate(raw_outreach)
        )

    needs_human_review = bool(
        state.get("needs_human_review", compute_needs_human_review(state))
    )
    status = "needs_human_review" if needs_human_review else "provisional_approved"

    telemetry_plugin = state.get("_telemetry_plugin")
    telemetry_summary: Dict[str, Any] = (
        telemetry_plugin.summary()
        if telemetry_plugin is not None and hasattr(telemetry_plugin, "summary")
        else {"request_id": resolved_req_id}
    )

    response = PlanResponse(
        request_id=resolved_req_id,
        status=status,
        needs_human_review=needs_human_review,
        county_fips=request.county_fips,
        county_name=request.county_name,
        final_plan=final_plan,
        audit_report=audit_report,
        revision_history=revision_history,
        evidence_report=evidence_report,
        outreach=outreach,
        provenance=_assemble_provenance(final_plan, evidence_report),
        limitations=_assemble_limitations(final_plan, evidence_report, audit_report),
        data_availability=_assemble_data_availability(state, evidence_report),
        telemetry_summary=telemetry_summary,
    )
    assert_no_pii_in_payload(response.model_dump())
    return response


async def execute_carebridge_plan(
    request: Optional[PlanRequest] = None,
    *,
    session_state_out: Optional[Dict[str, Any]] = None,
    initial_state_overrides: Optional[Dict[str, Any]] = None,
) -> PlanResponse:
    """Executes the 4-stage CareBridge AI Coordinator ADK workflow and returns `PlanResponse`."""
    req = request or PlanRequest()
    req_id = set_current_request_id()
    telemetry_plugin = CareBridgeTelemetryPlugin()

    initial_state: Dict[str, Any] = {
        STATE_REQUEST_ID: req_id,
        STATE_PLAN_REQUEST: req.model_dump(),
        STATE_REVISION_HISTORY: [],
        "_telemetry_plugin": telemetry_plugin,
    }
    if initial_state_overrides:
        initial_state.update(initial_state_overrides)

    workflow = build_carebridge_coordinator_workflow()
    runner = InMemoryRunner(agent=workflow, app_name="carebridge")
    session = await runner.session_service.create_session(
        app_name="carebridge",
        user_id="public-health-planner",
        session_id=f"sess-{req_id}",
        state=initial_state,
    )

    user_prompt = (
        f"Generate a 4-stop Saturday mobile health clinic plan for {req.county_name} County "
        f"(FIPS {req.county_fips}, strategy={req.strategy}, saturdays={', '.join(req.saturdays)})."
    )

    with trace_span(
        "coordinator.execute_carebridge_plan",
        request_id=req_id,
        county_fips=req.county_fips,
        strategy=req.strategy,
        simulate_first_draft_defect=req.simulate_first_draft_defect,
    ) as span:
        async for _ in runner.run_async(
            user_id="public-health-planner",
            session_id=session.id,
            new_message=user_prompt,
        ):
            pass

        response = assemble_plan_response_from_state(
            request=req,
            state=session.state,
            request_id=req_id,
        )
        span.set_attribute("status", response.status)
        span.set_attribute("needs_human_review", response.needs_human_review)
        span.set_attribute("revisions_count", len(response.revision_history))

        record_structured_log(
            component="carebridge_coordinator",
            event_type="execute_carebridge_plan_complete",
            request_id=req_id,
            status=response.status,
            needs_human_review=response.needs_human_review,
            revisions_count=len(response.revision_history),
        )

    if session_state_out is not None:
        session_state_out.update(
            {k: v for k, v in session.state.items() if not k.startswith("_")}
        )

    return response


def execute_carebridge_plan_sync(
    request: Optional[PlanRequest] = None,
    *,
    session_state_out: Optional[Dict[str, Any]] = None,
    initial_state_overrides: Optional[Dict[str, Any]] = None,
) -> PlanResponse:
    """Synchronous convenience wrapper around `execute_carebridge_plan`."""
    return asyncio.run(
        execute_carebridge_plan(
            request=request,
            session_state_out=session_state_out,
            initial_state_overrides=initial_state_overrides,
        )
    )
