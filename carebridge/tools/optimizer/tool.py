"""ADK FunctionTool wrapper for the deterministic Four-Stop Coverage Optimizer."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

from carebridge.contracts.evidence_models import (
    EvidenceReport,
    HealthEvidence,
    MobilityEvidence,
    TractMobilityRecord,
)
from carebridge.contracts.plan_models import DraftPlan
from carebridge.contracts.state_keys import (
    STATE_DRAFT_PLAN,
    STATE_EVIDENCE_REPORT,
    STATE_HEALTH_EVIDENCE,
    STATE_MOBILITY_EVIDENCE,
    STATE_NON_DEMOGRAPHIC_FEEDBACK,
    STATE_PLAN_REQUEST,
)
from carebridge.mocks.fulton_fixtures import (
    build_mock_health_evidence,
    build_mock_mobility_evidence,
)
from carebridge.security.race_blind_guard import (
    assert_no_pii_in_payload,
    assert_race_blind_planner_input,
)
from carebridge.telemetry.otel import record_structured_log, trace_span
from carebridge.tools.optimizer.coverage import (
    DEFAULT_SATURDAYS,
    build_runner_up_explanations,
    select_four_distinct_stops,
)
from carebridge.tools.optimizer.scoring import compute_tract_scores
from carebridge.tools.optimizer.sensitivity import run_weight_sensitivity

_EXCLUDE_GEOID_RE = re.compile(r"exclude[_\s]+(?:tract[_\s]+)?(\d{11})", re.I)


def optimize_four_clinic_stops(
    county_fips: str = "13121",
    strategy: str = "balanced_uninsured_safety_net_gap",
    revision_number: int = 0,
    simulate_first_draft_defect: bool = False,
    excluded_tract_geoids: Optional[List[str]] = None,
    min_separation_km_override: Optional[float] = None,
    tool_context: Optional[Any] = None,
    health_evidence: Optional[Any] = None,
    mobility_evidence: Optional[Any] = None,
    evidence_report: Optional[Any] = None,
    non_demographic_feedback: Optional[List[str]] = None,
    saturdays: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Deterministic 4-stop mobile health clinic coverage optimizer tool.

    Reads race-blind `health_evidence`, `mobility_evidence`, `plan_request`, and optional
    `non_demographic_feedback` from `tool_context.state` (or explicit arguments), computes
    within-county normalized need scores, selects 4 distinct Saturday stops, computes
    `runner_up_tracts` (#5-#8), and runs +/-15% weight sensitivity analysis.
    """
    state: Dict[str, Any] = {}
    if tool_context is not None and isinstance(getattr(tool_context, "state", None), dict):
        state = tool_context.state

    # Resolve plan_request parameters from state if present
    plan_req = state.get(STATE_PLAN_REQUEST)
    if isinstance(plan_req, dict):
        if plan_req.get("county_fips") and county_fips == "13121":
            county_fips = str(plan_req["county_fips"])
        if plan_req.get("strategy") and strategy == "balanced_uninsured_safety_net_gap":
            strategy = str(plan_req["strategy"])
        if saturdays is None and plan_req.get("saturdays"):
            saturdays = list(plan_req["saturdays"])
        if "simulate_first_draft_defect" in plan_req and not simulate_first_draft_defect:
            simulate_first_draft_defect = bool(plan_req["simulate_first_draft_defect"])

    if "current_revision_number" in state and revision_number == 0:
        revision_number = int(state["current_revision_number"])

    feedback_list: List[str] = list(
        non_demographic_feedback
        if non_demographic_feedback is not None
        else (state.get(STATE_NON_DEMOGRAPHIC_FEEDBACK) or [])
    )
    if feedback_list and revision_number == 0:
        revision_number = 1

    # Enforce strict race-blind & PII-free check on feedback
    if feedback_list:
        assert_race_blind_planner_input(feedback_list)
        assert_no_pii_in_payload(feedback_list)

    # Check EvidenceReport readiness gate if available
    raw_ev_report = evidence_report if evidence_report is not None else state.get(STATE_EVIDENCE_REPORT)
    if raw_ev_report is not None:
        ev_report = (
            raw_ev_report
            if isinstance(raw_ev_report, EvidenceReport)
            else EvidenceReport.model_validate(raw_ev_report)
        )
        if not ev_report.core_tables_ready:
            insufficient_plan = DraftPlan(
                county_fips=county_fips,
                strategy_used=strategy,
                status="insufficient_candidates",
                revision_number=min(1, max(0, revision_number)),
                stops=[],
                runner_up_tracts=[],
                sensitivity=None,
                planner_notes=[
                    "Core BigQuery health tables failed validation gate; cannot site mobile clinics.",
                    *ev_report.blocking_failures,
                ],
            )
            dumped = insufficient_plan.model_dump()
            if state is not None:
                state[STATE_DRAFT_PLAN] = dumped
            return dumped

    # Load HealthEvidence
    raw_health = health_evidence if health_evidence is not None else state.get(STATE_HEALTH_EVIDENCE)
    if raw_health is not None:
        assert_race_blind_planner_input(
            raw_health.model_dump() if hasattr(raw_health, "model_dump") else raw_health
        )
        assert_no_pii_in_payload(
            raw_health.model_dump() if hasattr(raw_health, "model_dump") else raw_health
        )
        he_model = (
            raw_health
            if isinstance(raw_health, HealthEvidence)
            else HealthEvidence.model_validate(raw_health)
        )
    else:
        he_model = build_mock_health_evidence(county_fips=county_fips)

    # Load MobilityEvidence
    raw_mobility = (
        mobility_evidence if mobility_evidence is not None else state.get(STATE_MOBILITY_EVIDENCE)
    )
    if raw_mobility is not None:
        assert_race_blind_planner_input(
            raw_mobility.model_dump() if hasattr(raw_mobility, "model_dump") else raw_mobility
        )
        assert_no_pii_in_payload(
            raw_mobility.model_dump() if hasattr(raw_mobility, "model_dump") else raw_mobility
        )
        mob_model = (
            raw_mobility
            if isinstance(raw_mobility, MobilityEvidence)
            else MobilityEvidence.model_validate(raw_mobility)
        )
    else:
        mob_model = build_mock_mobility_evidence(county_fips=county_fips, include_optional=True)

    mobility_map: Dict[str, TractMobilityRecord] = {
        m.geo_id: m for m in mob_model.tract_mobility
    }

    excluded_set = set(excluded_tract_geoids or [])
    for fb in feedback_list:
        for match in _EXCLUDE_GEOID_RE.finditer(fb):
            excluded_set.add(match.group(1))

    min_sep_km = float(min_separation_km_override) if min_separation_km_override is not None else 5.0
    if revision_number >= 1:
        # On revision 1, remediate any catchment overlap by enforcing >= 5.0 km separation
        simulate_first_draft_defect = False
        min_sep_km = max(5.0, min_sep_km)

    with trace_span(
        "tool.optimizer.run",
        strategy=strategy,
        revision_number=revision_number,
        county_fips=county_fips,
    ) as span:
        scores = compute_tract_scores(
            tracts=he_model.tracts,
            mobility_map=mobility_map,
            strategy=strategy,
        )
        span.set_attribute("candidate_tracts_count", len(scores))

        selected_stops = select_four_distinct_stops(
            tracts=he_model.tracts,
            scores=scores,
            mobility_map=mobility_map,
            saturdays=saturdays or DEFAULT_SATURDAYS,
            catchment_radius_km=4.0,
            min_separation_km=min_sep_km,
            overlap_discount=0.85,
            excluded_tract_geoids=sorted(excluded_set),
            simulate_first_draft_defect=simulate_first_draft_defect,
            revision_number=revision_number,
        )

        if len(selected_stops) < 4:
            span.set_attribute("selected_tracts", [])
            span.set_attribute("top_4_stability_jaccard", 0.0)
            insufficient_plan = DraftPlan(
                county_fips=county_fips,
                strategy_used=strategy,
                status="insufficient_candidates",
                revision_number=min(1, max(0, revision_number)),
                stops=[],
                runner_up_tracts=[],
                sensitivity=None,
                planner_notes=[
                    f"Only {len(scores)} valid candidate tracts available after filtering (minimum 4 distinct stops required)."
                ],
            )
            dumped = insufficient_plan.model_dump()
            if state is not None:
                state[STATE_DRAFT_PLAN] = dumped
            return dumped

        runner_ups = build_runner_up_explanations(
            tracts=he_model.tracts,
            scores=scores,
            selected_stops=selected_stops,
            mobility_map=mobility_map,
            catchment_radius_km=4.0,
            min_separation_km=min_sep_km,
        )

        sensitivity = run_weight_sensitivity(
            tracts=he_model.tracts,
            mobility_map=mobility_map,
            strategy=strategy,
            baseline_stops=selected_stops,
            perturbation_pct=15.0,
            excluded_tract_geoids=sorted(excluded_set),
            catchment_radius_km=4.0,
            min_separation_km=min_sep_km,
        )

        planner_notes: List[str] = [
            f"Deterministic 4-stop greedy max-coverage optimization completed using race-blind strategy '{strategy}'.",
            "Routine checkup prevalence (pct_checkup) inverted as (100 - pct_checkup) so low preventive care rates increase need score.",
            "All 4 stops are marked PROVISIONAL (host_verified=False) pending field operations confirmation.",
        ]
        if simulate_first_draft_defect and revision_number == 0:
            planner_notes.append(
                "DRAFT 0 NOTE: Inter-stop separation relaxed on Stop #2 (simulate_first_draft_defect=True)."
            )
        if revision_number >= 1 or feedback_list:
            planner_notes.append(
                f"REVISION {revision_number} REMEDIATION: Resolved Auditor non-demographic feedback "
                f"by enforcing >= {min_sep_km:.1f} km inter-stop catchment separation across all 4 stops."
            )

        draft_plan = DraftPlan(
            county_fips=county_fips,
            strategy_used=strategy,
            status="ok",
            revision_number=min(1, max(0, revision_number)),
            stops=selected_stops,
            runner_up_tracts=runner_ups,
            sensitivity=sensitivity,
            planner_notes=planner_notes,
        )

        selected_ids = [s.primary_tract_geoid for s in selected_stops]
        span.set_attribute("selected_tracts", selected_ids)
        span.set_attribute("top_4_stability_jaccard", sensitivity.top_4_stability_jaccard)

        record_structured_log(
            component="four_stop_coverage_optimizer",
            event_type="optimize_four_clinic_stops",
            county_fips=county_fips,
            strategy=strategy,
            revision_number=revision_number,
            selected_tracts=selected_ids,
            top_4_stability_jaccard=sensitivity.top_4_stability_jaccard,
        )

        dumped = draft_plan.model_dump()
        assert_race_blind_planner_input(dumped)
        assert_no_pii_in_payload(dumped)

        if state is not None:
            state[STATE_DRAFT_PLAN] = dumped

        return dumped
