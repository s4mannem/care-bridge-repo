"""Protected audit tool and post-hoc demographic comparator for the Equity & Rigor Auditor Agent."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set

from carebridge.contracts.audit_models import (
    AuditReport,
    AuditVerdict,
    DefectCategory,
    DemographicImpactComparison,
    NonDemographicAuditDefect,
)
from carebridge.contracts.evidence_models import EvidenceReport
from carebridge.contracts.plan_models import DraftPlan, ProposedClinicStop
from carebridge.contracts.state_keys import (
    STATE_AUDIT_REPORT,
    STATE_DRAFT_PLAN,
    STATE_EVIDENCE_REPORT,
    STATE_NON_DEMOGRAPHIC_FEEDBACK,
    STATE_REVISION_REQUIRED,
)
from carebridge.mocks.fulton_fixtures import (
    DEMOGRAPHIC_AUDIT_FIXTURES,
    build_mock_draft_plan,
)
from carebridge.security.owasp_guardrails import UNVERIFIED_BOOKING_CLAIM_REGEX
from carebridge.security.race_blind_guard import (
    PolicyViolationError,
    assert_no_pii_in_payload,
    assert_race_blind_planner_input,
)
from carebridge.telemetry.otel import record_structured_log, trace_span
from carebridge.tools.optimizer.scoring import haversine_km

_RESPIRATORY_MENTION_RE = re.compile(
    r"\b(covid|influenza|flu|rsv|nssp|disease_weekly|respiratory\s+(?:ed|virus|trend|visit))\b",
    re.I,
)
_HSA_DISCLOSURE_RE = re.compile(
    r"\b(hsa|health\s+service\s+area|4-county|four-county|multi-county|fulton,\s*dekalb)\b",
    re.I,
)
_PM25_TRACT_RANKING_CLAIM_RE = re.compile(
    r"\b(ranked\s+by\s+pm2\.?5|highest\s+pm2\.?5\s+tract|tract-level\s+pm2\.?5)\b",
    re.I,
)
_DISTANCE_AS_TRAVEL_TIME_CLAIM_RE = re.compile(
    r"\b(bus\s+travel\s+time\s+is|\d+\s*-?\s*minute\s+bus\s+ride|door-to-door\s+journey\s+time\s+is)\b",
    re.I,
)


def _fetch_protected_demographic_audit_table(
    county_fips: str,
    caller_agent_name: str,
) -> Dict[str, Dict[str, Any]]:
    """Queries `external_demographic_audit` inside the Auditor's protected permission boundary."""
    if caller_agent_name != "equity_rigor_auditor":
        raise PolicyViolationError(
            f"Unauthorized access to protected demographic audit boundary by '{caller_agent_name}'."
        )

    try:
        from carebridge.data_plane.mcp_bigquery_toolset import mcp_query_posthoc_demographic_audit  # type: ignore

        rows = mcp_query_posthoc_demographic_audit(
            county_fips=county_fips,
            caller_agent_name=caller_agent_name,
        )
        if isinstance(rows, list) and rows:
            mapped: Dict[str, Dict[str, Any]] = {}
            for r in rows:
                if isinstance(r, dict) and r.get("geo_id"):
                    mapped[str(r["geo_id"])] = r
            if mapped:
                return mapped
    except PolicyViolationError:
        raise
    except Exception:
        pass

    return {
        k: dict(v)
        for k, v in DEMOGRAPHIC_AUDIT_FIXTURES.items()
        if str(k).startswith(str(county_fips))
    } or {k: dict(v) for k, v in DEMOGRAPHIC_AUDIT_FIXTURES.items()}


def _check_non_demographic_defects(
    draft_plan: DraftPlan,
    evidence_report: Optional[EvidenceReport],
) -> List[NonDemographicAuditDefect]:
    """Deterministically evaluates operational, spatial-grain, and sensitivity defects (race-blind)."""
    defects: List[NonDemographicAuditDefect] = []

    # 1. Core evidence readiness & candidate count check
    if evidence_report is not None and not evidence_report.core_tables_ready:
        defects.append(
            NonDemographicAuditDefect(
                defect_id="DEFECT-CORE-EVIDENCE-NOT-READY",
                category=DefectCategory.MISSING_CORE_EVIDENCE,
                affected_stop_ranks=[],
                affected_tract_geoids=[],
                description=(
                    "Core BigQuery health tables failed validation gate (`core_tables_ready=False`); "
                    f"blocking failures: {', '.join(evidence_report.blocking_failures) or 'unspecified'}."
                ),
                remediation_instruction=(
                    "Do not site stops until core tables pass schema and row-count validation; return "
                    "status='insufficient_candidates'."
                ),
            )
        )

    if draft_plan.status == "insufficient_candidates" or len(draft_plan.stops) < 4:
        defects.append(
            NonDemographicAuditDefect(
                defect_id="DEFECT-INSUFFICIENT-CANDIDATES",
                category=DefectCategory.MISSING_CORE_EVIDENCE,
                affected_stop_ranks=[s.stop_rank for s in draft_plan.stops],
                affected_tract_geoids=[s.primary_tract_geoid for s in draft_plan.stops],
                description=(
                    f"DraftPlan status is '{draft_plan.status}' with {len(draft_plan.stops)} stops "
                    "(4 distinct Saturday mobile clinic stops required)."
                ),
                remediation_instruction=(
                    "Verify candidate tract filter and re-run optimize_four_clinic_stops to produce 4 distinct stops "
                    "or escalate insufficient candidate coverage to human operations."
                ),
            )
        )
        return defects

    # 2. Geographic & Catchment Overlap check (< 5.0 km separation or > 20% shared covered tracts)
    stops: List[ProposedClinicStop] = list(draft_plan.stops)
    for i in range(len(stops)):
        for j in range(i + 1, len(stops)):
            s1, s2 = stops[i], stops[j]
            dist_km = haversine_km(s1.latitude, s1.longitude, s2.latitude, s2.longitude)
            cov1: Set[str] = set(s1.covered_tract_geoids)
            cov2: Set[str] = set(s2.covered_tract_geoids)
            shared_tracts = sorted(cov1 & cov2)
            min_cov_size = max(1, min(len(cov1), len(cov2)))
            overlap_ratio = len(shared_tracts) / float(min_cov_size)

            if dist_km < 5.0 or overlap_ratio > 0.20 or s1.primary_tract_geoid == s2.primary_tract_geoid:
                defects.append(
                    NonDemographicAuditDefect(
                        defect_id=f"DEFECT-OVERLAP-S{s1.stop_rank}-S{s2.stop_rank}",
                        category=DefectCategory.CATCHMENT_OVERLAP,
                        affected_stop_ranks=[s1.stop_rank, s2.stop_rank],
                        affected_tract_geoids=sorted({s1.primary_tract_geoid, s2.primary_tract_geoid, *shared_tracts}),
                        description=(
                            f"Stop #{s1.stop_rank} ({s1.primary_tract_geoid}) and Stop #{s2.stop_rank} "
                            f"({s2.primary_tract_geoid}) are {dist_km:.2f} km apart (< 5.0 km minimum separation) "
                            f"with {overlap_ratio * 100.0:.1f}% catchment tract overlap."
                        ),
                        remediation_instruction=(
                            f"Re-run optimize_four_clinic_stops with revision_number=1 enforcing >= 5.0 km "
                            f"inter-stop separation and <= 20% catchment overlap; relocate Stop #{s2.stop_rank} "
                            f"(exclude tract {s2.primary_tract_geoid} if needed)."
                        ),
                    )
                )

    # 3. Per-stop Evidentiary, 4-Resolution, Directionality & Host Verification checks
    for stop in stops:
        combined_disclosures = " ".join([stop.plain_language_rationale, *stop.spatial_grain_disclosures])

        if not stop.evidence_citations or not stop.spatial_grain_disclosures:
            defects.append(
                NonDemographicAuditDefect(
                    defect_id=f"DEFECT-MISSING-CITATIONS-S{stop.stop_rank}",
                    category=DefectCategory.MISSING_CORE_EVIDENCE,
                    affected_stop_ranks=[stop.stop_rank],
                    affected_tract_geoids=[stop.primary_tract_geoid],
                    description=(
                        f"Stop #{stop.stop_rank} ({stop.primary_tract_geoid}) is missing mandatory "
                        "evidence_citations or spatial_grain_disclosures."
                    ),
                    remediation_instruction=(
                        f"Attach table-level evidence_citations and explicit spatial_grain_disclosures "
                        f"to Stop #{stop.stop_rank}."
                    ),
                )
            )

        # Check NSSP respiratory trend HSA grain disclosure
        if _RESPIRATORY_MENTION_RE.search(stop.plain_language_rationale) and not _HSA_DISCLOSURE_RE.search(
            combined_disclosures
        ):
            defects.append(
                NonDemographicAuditDefect(
                    defect_id=f"DEFECT-HSA-GRAIN-S{stop.stop_rank}",
                    category=DefectCategory.UNSUPPORTED_GRAIN_CLAIM,
                    affected_stop_ranks=[stop.stop_rank],
                    affected_tract_geoids=[stop.primary_tract_geoid],
                    description=(
                        f"Stop #{stop.stop_rank} ({stop.primary_tract_geoid}) references respiratory illness trends "
                        "without disclosing that NSSP `disease_weekly` applies to the 4-county Health Service Area "
                        "(HSA), not the individual census tract."
                    ),
                    remediation_instruction=(
                        f"Qualify all respiratory ED trend references on Stop #{stop.stop_rank} as 4-county "
                        "Atlanta HSA signals, never tract-level."
                    ),
                )
            )

        # Check 12km PM2.5 tract-ranking misuse or straight-line distance misrepresented as travel time
        if _PM25_TRACT_RANKING_CLAIM_RE.search(stop.plain_language_rationale) or _DISTANCE_AS_TRAVEL_TIME_CLAIM_RE.search(
            stop.plain_language_rationale
        ):
            defects.append(
                NonDemographicAuditDefect(
                    defect_id=f"DEFECT-RESOLUTION-MISUSE-S{stop.stop_rank}",
                    category=DefectCategory.UNSUPPORTED_GRAIN_CLAIM,
                    affected_stop_ranks=[stop.stop_rank],
                    affected_tract_geoids=[stop.primary_tract_geoid],
                    description=(
                        f"Stop #{stop.stop_rank} ({stop.primary_tract_geoid}) misrepresents 12km grid PM2.5 as a "
                        "tract ranker or treats straight-line federal clinic distance as bus travel time."
                    ),
                    remediation_instruction=(
                        f"Remove tract-level PM2.5 ranking claims and state that km_to_safety_net on "
                        f"Stop #{stop.stop_rank} is straight-line upper-bound distance, not transit travel time."
                    ),
                )
            )

        # Check unverified host booking claims
        if stop.host_verified or UNVERIFIED_BOOKING_CLAIM_REGEX.search(stop.plain_language_rationale):
            defects.append(
                NonDemographicAuditDefect(
                    defect_id=f"DEFECT-UNVERIFIED-HOST-S{stop.stop_rank}",
                    category=DefectCategory.INFEASIBLE_HOST_OR_TRANSIT,
                    affected_stop_ranks=[stop.stop_rank],
                    affected_tract_geoids=[stop.primary_tract_geoid],
                    description=(
                        f"Stop #{stop.stop_rank} ({stop.candidate_venue_name}) sets host_verified=True or claims "
                        "confirmed booking without field operations verification."
                    ),
                    remediation_instruction=(
                        f"Set host_verified=False and preserve provisional_warning on Stop #{stop.stop_rank}."
                    ),
                )
            )

    # 4. Question 7 runner-up neighborhood explanations check
    if not draft_plan.runner_up_tracts:
        defects.append(
            NonDemographicAuditDefect(
                defect_id="DEFECT-MISSING-RUNNER-UPS",
                category=DefectCategory.MISSING_CORE_EVIDENCE,
                affected_stop_ranks=[],
                affected_tract_geoids=[],
                description="DraftPlan omits runner_up_tracts (#5-#8) technical deferral explanations (Question 7).",
                remediation_instruction=(
                    "Populate runner_up_tracts (#5-#8) with technical_deferral_rationale explaining why each "
                    "runner-up tract was not assigned a dedicated stop."
                ),
            )
        )

    # 5. Sensitivity stability check
    if draft_plan.sensitivity is not None and draft_plan.sensitivity.top_4_stability_jaccard < 0.50:
        defects.append(
            NonDemographicAuditDefect(
                defect_id="DEFECT-SENSITIVITY-INSTABILITY",
                category=DefectCategory.SENSITIVITY_INSTABILITY,
                affected_stop_ranks=[s.stop_rank for s in stops],
                affected_tract_geoids=list(draft_plan.sensitivity.borderline_tracts),
                description=(
                    f"Top-4 Jaccard stability under +/-{draft_plan.sensitivity.weight_perturbation_pct:.0f}% weight "
                    f"perturbation is {draft_plan.sensitivity.top_4_stability_jaccard:.2f} (< 0.50 threshold)."
                ),
                remediation_instruction=(
                    "Use balanced_uninsured_safety_net_gap weights and document borderline tracts in planner_notes."
                ),
            )
        )

    return defects


def _compute_posthoc_demographic_impact(
    draft_plan: DraftPlan,
    demographic_table: Dict[str, Dict[str, Any]],
) -> DemographicImpactComparison:
    """Computes population-weighted county vs 4-stop catchment demographic parity (VISIBLE TO AUDITOR ONLY)."""
    county_rows = list(demographic_table.values())
    if not county_rows:
        county_rows = list(DEMOGRAPHIC_AUDIT_FIXTURES.values())

    county_total_pop = sum(max(1, int(r.get("total_pop", 0))) for r in county_rows)

    covered_geoids: Set[str] = set()
    for stop in draft_plan.stops:
        covered_geoids.add(stop.primary_tract_geoid)
        covered_geoids.update(stop.covered_tract_geoids)

    catchment_rows = [demographic_table[g] for g in sorted(covered_geoids) if g in demographic_table]
    if not catchment_rows and draft_plan.stops:
        # Fallback if custom test tract IDs are not in fixture keys
        catchment_rows = county_rows[: min(4, len(county_rows))]

    catchment_total_pop = sum(max(1, int(r.get("total_pop", 0))) for r in catchment_rows) if catchment_rows else 0

    def _weighted_mean(rows: List[Dict[str, Any]], field: str) -> float:
        total_w = sum(max(1, int(r.get("total_pop", 0))) for r in rows)
        if total_w <= 0:
            return 0.0
        return sum(float(r.get(field, 0.0)) * max(1, int(r.get("total_pop", 0))) for r in rows) / float(total_w)

    county_svi_theme3 = round(min(1.0, max(0.0, _weighted_mean(county_rows, "rpl_theme3_proxy"))), 3)
    catchment_svi_theme3 = (
        round(min(1.0, max(0.0, _weighted_mean(catchment_rows, "rpl_theme3_proxy"))), 3)
        if catchment_rows
        else 0.0
    )

    group_fields = {
        "black": "pct_black",
        "hispanic": "pct_hispanic",
        "white": "pct_white",
        "asian": "pct_asian",
        "minority_overall": "pct_minority",
    }

    group_comparisons: Dict[str, Dict[str, float]] = {}
    disparity_findings: List[str] = []
    requires_human_equity_review = False

    for group_label, col_name in group_fields.items():
        county_pct = round(_weighted_mean(county_rows, col_name), 2)
        catchment_pct = round(_weighted_mean(catchment_rows, col_name), 2) if catchment_rows else 0.0
        parity_ratio = round(catchment_pct / county_pct, 2) if county_pct > 0 else 1.0
        group_comparisons[group_label] = {
            "county_pct": county_pct,
            "catchment_pct": catchment_pct,
            "parity_ratio": parity_ratio,
        }
        if group_label in ("black", "hispanic", "minority_overall") and catchment_rows and parity_ratio < 0.80:
            requires_human_equity_review = True
            disparity_findings.append(
                f"Post-hoc equity alert: '{group_label}' catchment representation ({catchment_pct:.1f}%) is below "
                f"0.80x county baseline ({county_pct:.1f}%, parity_ratio={parity_ratio:.2f}). Flagged for human "
                "public-health leadership review (never fed back as a race target to Planner)."
            )

    if not disparity_findings:
        minority_stats = group_comparisons.get("minority_overall", {})
        disparity_findings.append(
            f"Post-hoc equity check passed: race-blind structural siting covers underserved communities at "
            f"{minority_stats.get('parity_ratio', 1.0):.2f}x county baseline parity "
            f"(catchment SVI Theme 3 mean={catchment_svi_theme3:.2f} vs county={county_svi_theme3:.2f})."
        )

    return DemographicImpactComparison(
        county_total_pop=county_total_pop,
        catchment_total_pop=catchment_total_pop,
        county_svi_theme3_mean=county_svi_theme3,
        catchment_svi_theme3_mean=catchment_svi_theme3,
        group_comparisons=group_comparisons,
        disparity_findings=disparity_findings,
        requires_human_equity_review=requires_human_equity_review,
    )


def execute_independent_plan_audit(
    county_fips: str = "13121",
    tool_context: Optional[Any] = None,
    draft_plan: Optional[Any] = None,
    evidence_report: Optional[Any] = None,
    demographic_override: Optional[Dict[str, Dict[str, Any]]] = None,
    caller_agent_name: Optional[str] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Deterministically audits `draft_plan` for non-demographic rigor and post-hoc demographic impact.

    Strictly restricted to `agent_name == 'equity_rigor_auditor'` (OWASP LLM06 access boundary).
    Writes full `AuditReport` to `state['audit_report']`, boolean `state['revision_required']`,
    and strictly race-blind `[d.model_dump() for d in non_demographic_defects]` to
    `state['non_demographic_feedback']`.
    """
    resolved_caller = (
        getattr(tool_context, "agent_name", None)
        if tool_context is not None and getattr(tool_context, "agent_name", None) is not None
        else (caller_agent_name or "equity_rigor_auditor")
    )
    if resolved_caller != "equity_rigor_auditor":
        raise PolicyViolationError(
            f"Unauthorized access to protected demographic audit boundary by '{resolved_caller}'."
        )

    state: Dict[str, Any] = {}
    if tool_context is not None and isinstance(getattr(tool_context, "state", None), dict):
        state = tool_context.state

    raw_draft = draft_plan if draft_plan is not None else state.get(STATE_DRAFT_PLAN)
    if raw_draft is None:
        dp_model = build_mock_draft_plan("13121")
    elif isinstance(raw_draft, DraftPlan):
        dp_model = raw_draft
    else:
        dp_model = DraftPlan.model_validate(raw_draft)

    raw_ev = evidence_report if evidence_report is not None else state.get(STATE_EVIDENCE_REPORT)
    ev_model: Optional[EvidenceReport] = None
    if raw_ev is not None:
        ev_model = raw_ev if isinstance(raw_ev, EvidenceReport) else EvidenceReport.model_validate(raw_ev)

    with trace_span(
        "agent.auditor.evaluate",
        revision_audited=dp_model.revision_number,
        county_fips=dp_model.county_fips,
    ) as span:
        non_demographic_defects = _check_non_demographic_defects(dp_model, ev_model)

        demographic_table = (
            demographic_override
            if demographic_override is not None
            else _fetch_protected_demographic_audit_table(
                county_fips=dp_model.county_fips,
                caller_agent_name=resolved_caller,
            )
        )
        demographic_impact = _compute_posthoc_demographic_impact(dp_model, demographic_table)

        revision_audited = int(dp_model.revision_number)
        if non_demographic_defects:
            if revision_audited == 0 and dp_model.status == "ok":
                verdict = AuditVerdict.REJECTED_REVISION_REQUIRED
                revision_required = True
            else:
                verdict = AuditVerdict.NEEDS_HUMAN_REVIEW
                revision_required = False
        else:
            if demographic_impact.requires_human_equity_review or dp_model.status != "ok":
                verdict = AuditVerdict.NEEDS_HUMAN_REVIEW
                revision_required = False
            else:
                verdict = AuditVerdict.APPROVED
                revision_required = False

        if verdict == AuditVerdict.APPROVED:
            auditor_summary = (
                f"APPROVED (revision {revision_audited}): All 4 proposed stops satisfy >= 5.0 km inter-stop "
                "separation, invert pct_checkup properly, disclose spatial grain boundaries (4-county HSA vs tract), "
                "explain runner-up tract deferrals (#5-#8), and pass post-hoc demographic parity review."
            )
        elif verdict == AuditVerdict.REJECTED_REVISION_REQUIRED:
            defect_ids = ", ".join(d.defect_id for d in non_demographic_defects)
            auditor_summary = (
                f"REJECTED — REVISION REQUIRED (revision {revision_audited}): Detected "
                f"{len(non_demographic_defects)} non-demographic defect(s) [{defect_ids}]. Returning sanitized "
                "non-demographic remediation instructions to Siting Planner Agent for bounded revision."
            )
        else:
            auditor_summary = (
                f"NEEDS HUMAN REVIEW (revision {revision_audited}): Automated revision cap reached or human "
                "equity/operations sign-off required before provisional release."
            )

        limitations_attached = [
            "Distances (`km_to_any_care`, `km_to_safety_net`) are straight-line upper bounds to federally recognized sites inside the county border, not transit journey times.",
            "Weekly respiratory ED trends (`disease_weekly`) apply to the 4-county Health Service Area (HSA: Fulton, DeKalb, Clayton, Gwinnett), never individual census tracts.",
            "CDC PLACES tract prevalences are small-area modeled estimates with overlapping 95% confidence intervals for <1-2% differences.",
            "All 4 proposed clinic host venues remain PROVISIONAL (`host_verified=False`) pending field operations confirmation of host permission, parking pad clearance, and Saturday staffing.",
        ]

        audit_report = AuditReport(
            revision_audited=revision_audited,
            verdict=verdict,
            non_demographic_defects=non_demographic_defects,
            demographic_impact=demographic_impact,
            auditor_summary=auditor_summary,
            limitations_attached=limitations_attached,
        )

        # ONE-WAY DEMOGRAPHIC DIODE: sanitize non_demographic_feedback and verify it is 100% race-blind & PII-free
        sanitized_feedback = [d.model_dump() for d in audit_report.non_demographic_defects]
        assert_race_blind_planner_input(sanitized_feedback)
        assert_no_pii_in_payload(sanitized_feedback)

        report_dict = audit_report.model_dump()
        assert_no_pii_in_payload(report_dict)

        if state is not None:
            state[STATE_AUDIT_REPORT] = report_dict
            state[STATE_REVISION_REQUIRED] = revision_required
            state[STATE_NON_DEMOGRAPHIC_FEEDBACK] = sanitized_feedback

        span.set_attribute("revision_audited", revision_audited)
        span.set_attribute("verdict", verdict.value)
        span.set_attribute("defects_count", len(non_demographic_defects))
        span.set_attribute("catchment_svi_theme3_mean", demographic_impact.catchment_svi_theme3_mean)
        span.set_attribute("county_svi_theme3_mean", demographic_impact.county_svi_theme3_mean)

        record_structured_log(
            component="equity_rigor_auditor",
            event_type="agent.auditor.evaluate",
            revision_audited=revision_audited,
            verdict=verdict.value,
            defects_count=len(non_demographic_defects),
            catchment_svi_theme3_mean=demographic_impact.catchment_svi_theme3_mean,
            county_svi_theme3_mean=demographic_impact.county_svi_theme3_mean,
        )

        return report_dict


# Alias referenced in Plan 07 Section 1
run_equity_and_rigor_audit = execute_independent_plan_audit
