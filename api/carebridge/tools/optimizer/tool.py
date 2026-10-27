"""ADK FunctionTool entrypoint for the Four-Stop Coverage Optimizer."""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from carebridge.contracts.api_models import PlanRequest
from carebridge.contracts.audit_models import AuditReport
from carebridge.contracts.evidence_models import (
    EvidenceReport,
    HealthEvidence,
    MobilityEvidence,
    TractMobilityRecord,
)
from carebridge.contracts.plan_models import DraftPlan
from carebridge.contracts.state_keys import (
    STATE_EVIDENCE_REPORT,
    STATE_HEALTH_EVIDENCE,
    STATE_MOBILITY_EVIDENCE,
    STATE_NON_DEMOGRAPHIC_FEEDBACK,
    STATE_PLAN_REQUEST,
)
from carebridge.security.race_blind_guard import assert_race_blind_planner_input
from carebridge.telemetry.otel import trace_span
from carebridge.tools.optimizer.coverage import select_four_distinct_stops
from carebridge.tools.optimizer.sensitivity import run_weight_sensitivity


def optimize_four_clinic_stops(
    health_evidence: Optional[HealthEvidence | Dict[str, Any]] = None,
    mobility_evidence: Optional[MobilityEvidence | Dict[str, Any]] = None,
    plan_request: Optional[PlanRequest | Dict[str, Any]] = None,
    evidence_report: Optional[EvidenceReport | Dict[str, Any]] = None,
    non_demographic_feedback: Optional[List[Any]] = None,
    revision_number: int = 0,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Deterministic tool selecting 4 distinct Saturday mobile clinic stops.

    Computes within-county normalized need scores, enforces spatial separation,
    generates Question 7 runner-up deferral explanations, and evaluates sensitivity.
    Never consumes race or ethnicity features.
    """
    with trace_span("tool.optimizer.run") as span:
        # Resolve inputs from kwargs if called by ADK passing session state
        if health_evidence is None and STATE_HEALTH_EVIDENCE in kwargs:
            health_evidence = kwargs[STATE_HEALTH_EVIDENCE]
        if mobility_evidence is None and STATE_MOBILITY_EVIDENCE in kwargs:
            mobility_evidence = kwargs[STATE_MOBILITY_EVIDENCE]
        if plan_request is None and STATE_PLAN_REQUEST in kwargs:
            plan_request = kwargs[STATE_PLAN_REQUEST]
        if evidence_report is None and STATE_EVIDENCE_REPORT in kwargs:
            evidence_report = kwargs[STATE_EVIDENCE_REPORT]
        if non_demographic_feedback is None and STATE_NON_DEMOGRAPHIC_FEEDBACK in kwargs:
            non_demographic_feedback = kwargs[STATE_NON_DEMOGRAPHIC_FEEDBACK]

        # Coerce models
        if isinstance(health_evidence, dict):
            health_evidence = HealthEvidence.model_validate(health_evidence)
        if isinstance(mobility_evidence, dict):
            mobility_evidence = MobilityEvidence.model_validate(mobility_evidence)
        if isinstance(plan_request, dict):
            plan_request = PlanRequest.model_validate(plan_request)
        if isinstance(evidence_report, dict):
            evidence_report = EvidenceReport.model_validate(evidence_report)

        # Race-blind boundary check
        if health_evidence:
            assert_race_blind_planner_input(health_evidence.model_dump())
        if mobility_evidence:
            assert_race_blind_planner_input(mobility_evidence.model_dump())

        county_fips = (
            plan_request.county_fips if plan_request
            else (health_evidence.county_fips if health_evidence else "13121")
        )
        strategy = (
            plan_request.strategy if plan_request
            else "balanced_uninsured_safety_net_gap"
        )
        saturdays = (
            plan_request.saturdays if plan_request
            else ["2026-11-07", "2026-11-14", "2026-11-21", "2026-11-28"]
        )

        # Gate on core_tables_ready
        if evidence_report and not evidence_report.core_tables_ready:
            draft = DraftPlan(
                county_fips=county_fips,
                strategy_used=strategy,
                status="insufficient_candidates",
                revision_number=revision_number,
                stops=[],
                runner_up_tracts=[],
                sensitivity=None,
                planner_notes=[
                    "EvidenceReport indicated core_tables_ready=False.",
                    *evidence_report.blocking_failures,
                ],
            )
            span.set_attribute("status", draft.status)
            return draft.model_dump()

        if not health_evidence or not health_evidence.tracts:
            draft = DraftPlan(
                county_fips=county_fips,
                strategy_used=strategy,
                status="insufficient_candidates",
                revision_number=revision_number,
                stops=[],
                runner_up_tracts=[],
                sensitivity=None,
                planner_notes=["No health evidence tracts available."],
            )
            span.set_attribute("status", draft.status)
            return draft.model_dump()

        tracts = health_evidence.tracts
        mobility_map: Dict[str, TractMobilityRecord] = {}
        if mobility_evidence:
            mobility_map = {m.geo_id: m for m in mobility_evidence.tract_mobility}

        simulate_defect = bool(
            plan_request
            and plan_request.simulate_first_draft_defect
            and revision_number == 0
        )

        # Check if non_demographic_feedback requests resolving an overlap or excluded tracts
        min_separation_km = 5.0
        excluded_geoids: set[str] = set()
        planner_notes: List[str] = []

        if non_demographic_feedback:
            planner_notes.append(
                f"Incorporated {len(non_demographic_feedback)} non-demographic audit remediation items."
            )
            for fb in non_demographic_feedback:
                # The auditor sends NonDemographicAuditDefect dicts; plain strings are still accepted.
                text = f"{fb.get('category', '')} {fb.get('description', '')}" if isinstance(fb, dict) else str(fb)
                fb_lower = text.lower()
                if "overlap" in fb_lower or "separation" in fb_lower:
                    min_separation_km = 6.0  # stricter separation on revision
                    planner_notes.append(
                        f"Revision {revision_number} resolves catchment overlap: stops now at least "
                        f"{min_separation_km:.0f} km apart."
                    )

        stops, runner_ups = select_four_distinct_stops(
            tracts=tracts,
            mobility_map=mobility_map,
            saturdays=saturdays,
            strategy=strategy,
            min_separation_km=min_separation_km,
            excluded_tract_geoids=excluded_geoids,
            simulate_first_draft_defect=simulate_defect,
        )

        if len(stops) < 4:
            draft = DraftPlan(
                county_fips=county_fips,
                strategy_used=strategy,
                status="insufficient_candidates",
                revision_number=revision_number,
                stops=stops,
                runner_up_tracts=runner_ups,
                sensitivity=None,
                planner_notes=[
                    f"Found only {len(stops)} candidates satisfying separation constraints."
                ],
            )
            span.set_attribute("status", draft.status)
            return draft.model_dump()

        sensitivity = run_weight_sensitivity(
            tracts=tracts,
            mobility_map=mobility_map,
            strategy=strategy,
            saturdays=saturdays,
        )

        status_str = "ok"
        draft = DraftPlan(
            county_fips=county_fips,
            strategy_used=strategy,
            status=status_str,
            revision_number=revision_number,
            stops=stops,
            runner_up_tracts=runner_ups,
            sensitivity=sensitivity,
            planner_notes=planner_notes,
        )

        span.set_attribute("status", draft.status)
        span.set_attribute("revision_number", revision_number)
        span.set_attribute("selected_tracts", [s.primary_tract_geoid for s in stops])
        span.set_attribute("top_4_stability_jaccard", sensitivity.top_4_stability_jaccard)

        return draft.model_dump()
