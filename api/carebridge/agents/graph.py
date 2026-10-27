"""The CareBridge ADK graph (plan 09) and how a run becomes a PlanResponse.

    SequentialAgent carebridge
     ├─ ParallelAgent evidence: health_access ║ transit_community
     ├─ evidence_validator
     ├─ LoopAgent(max_iterations=2): siting_planner → equity_auditor → gate
     └─ communications

The siting planner is the team's Gemini LlmAgent (plan 06) with the coverage
optimizer as its tool. Health & Access (plan 02) is a Gemini LlmAgent whose
tool runs named queries over the Google-managed BigQuery MCP server. The equity
auditor (plan 07) is a second Gemini LlmAgent whose instructions oppose the
planner's: it runs the deterministic audit tools, cross-examines the planner's
claims and alone sees race and ethnicity. The other agents are deterministic
stand-ins over `carebridge/tools` until their LLM versions land; each emits the
same state keys the real agent will, so swapping one in changes nothing downstream.
Every node attaches a UI-facing `AgentEvent` to its ADK event so the API can
stream the run as it happens.
"""
import re
from collections.abc import AsyncGenerator
from typing import Any

from google.adk.agents import BaseAgent, LlmAgent, LoopAgent, ParallelAgent, SequentialAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.events import Event, EventActions
from google.adk.tools import FunctionTool, ToolContext
from google.genai import types
from pydantic import ConfigDict

from ..config import Settings
from ..contracts.api_models import PlanRequest
from ..contracts.audit_models import (
    AuditReport,
    AuditVerdict,
    DefectCategory,
    DemographicImpactComparison,
    NonDemographicAuditDefect,
)
from ..contracts.evidence_models import EvidenceReport, HealthEvidence, MobilityEvidence
from ..contracts.interaction_models import AgentEvent
from ..contracts.plan_models import DraftPlan
from ..contracts.state_keys import (
    STATE_AUDIT_REPORT,
    STATE_DRAFT_PLAN,
    STATE_EVIDENCE_REPORT,
    STATE_FINAL_PLAN,
    STATE_HEALTH_EVIDENCE,
    STATE_ITERATION_COUNT,
    STATE_MOBILITY_EVIDENCE,
    STATE_NON_DEMOGRAPHIC_FEEDBACK,
    STATE_OUTREACH_MESSAGES,
    STATE_PLAN_REQUEST,
    STATE_REVISION_HISTORY,
    STATE_REVISION_REQUIRED,
)
from ..data.bigquery import BigQueryRepo
from ..data.bq_mcp import BigQueryMcp
from ..security.model_armor import default_vertex_safety_settings
from ..security.owasp_guardrails import before_model_guardrail_callback
from ..security.race_blind_guard import PolicyViolationError, assert_race_blind_planner_input
from ..tools.audit import PARITY_FLOOR, audit_draft, demographic_impact, draft_outreach
from ..tools.evidence import unavailable_mobility_evidence, validate_evidence
from ..tools.optimizer.tool import optimize_four_clinic_stops
from .health_agent import build_health_access_llm, collect_health_evidence
from .trace import overlap_pair, tract_label

UI_EVENT = "carebridge_event"  # Event.custom_metadata key the API streams to the UI


def ui_event(agent: str, kind: str, message: str, **kw: Any) -> dict:
    """An AgentEvent without t_ms; the runner stamps time as it streams."""
    return AgentEvent(t_ms=0, agent=agent, kind=kind, message=message, **kw).model_dump(mode="json",
                                                                                    exclude={"t_ms"})


def _event(agent: BaseAgent, ctx: InvocationContext, ui: dict | None = None,
           state: dict | None = None, escalate: bool = False) -> Event:
    return Event(author=agent.name, invocation_id=ctx.invocation_id, branch=ctx.branch,
                 actions=EventActions(state_delta=state or {}, escalate=escalate or None),
                 custom_metadata={UI_EVENT: ui} if ui else None)


class _StandIn(BaseAgent):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    repo: Any = None


# ── 01 · Evidence (plans 02, 03) ───────────────────────────────────────────

class HealthAccessAgent(BaseAgent):
    """Plan 02: Gemini evidence agent whose one tool runs the named queries over BigQuery's managed MCP server.

    Wraps the LlmAgent so the UI keeps its start / state_write events. If the model answers without
    calling the tool, the queries run anyway, so `health_evidence` is always written.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)
    mcp: Any = None

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        req = PlanRequest.model_validate(ctx.session.state[STATE_PLAN_REQUEST])
        yield _event(self, ctx, ui_event("health_access", "start",
                                         "Querying burden_tracts + tract_access via BigQuery MCP", parallel=True))
        health = None
        async for e in self.sub_agents[0].run_async(ctx):
            for call in e.get_function_calls():
                yield _event(self, ctx, ui_event("health_access", "tool",
                                                 f"{call.name} → bigquery.googleapis.com/mcp execute_sql_readonly",
                                                 parallel=True))
            delta = e.actions.state_delta if e.actions else {}
            if STATE_HEALTH_EVIDENCE in delta:
                health = HealthEvidence.model_validate(delta[STATE_HEALTH_EVIDENCE])
            yield e
            if e.is_final_response() and e.content and e.content.parts and e.content.parts[0].text:
                yield _event(self, ctx, ui_event("health_access", "finding", e.content.parts[0].text.strip(),
                                                 parallel=True))
        state = None
        if health is None:
            health = await collect_health_evidence(self.mcp, req.county_fips, req.county_name, ReadonlyContext(ctx))
            state = {STATE_HEALTH_EVIDENCE: health.model_dump(mode="json")}
        yield _event(self, ctx, ui_event("health_access", "state_write",
                                         f"{len(health.tracts)} tracts with burden and two distances (MCP)",
                                         parallel=True, state_key=STATE_HEALTH_EVIDENCE), state=state)


class TransitCommunityStandIn(_StandIn):
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        req = PlanRequest.model_validate(ctx.session.state[STATE_PLAN_REQUEST])
        mobility = unavailable_mobility_evidence(req.county_fips)
        yield _event(self, ctx, ui_event("transit_community", "skip", "MARTA GTFS unavailable: not loaded",
                                         parallel=True, state_key=STATE_MOBILITY_EVIDENCE),
                     state={STATE_MOBILITY_EVIDENCE: mobility.model_dump(mode="json")})


class EvidenceValidatorStandIn(_StandIn):
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        s = ctx.session.state
        yield _event(self, ctx, ui_event("evidence_validator", "start",
                                         "Checking grain, inversion and leakage on every input"))
        report = validate_evidence(HealthEvidence.model_validate(s[STATE_HEALTH_EVIDENCE]),
                                   MobilityEvidence.model_validate(s[STATE_MOBILITY_EVIDENCE]))
        for c in report.checks:
            if c.verdict != "PASS":
                yield _event(self, ctx, ui_event("evidence_validator", "finding",
                                                 f"{c.verdict} {c.check_name}: {c.detail}"))
        passes = sum(c.verdict == "PASS" for c in report.checks)
        yield _event(self, ctx, ui_event("evidence_validator", "state_write",
                                         f"{passes} checks passed · core tables "
                                         f"{'ready' if report.core_tables_ready else 'NOT ready'}",
                                         state_key=STATE_EVIDENCE_REPORT),
                     state={STATE_EVIDENCE_REPORT: report.model_dump(mode="json"), STATE_ITERATION_COUNT: 0,
                            STATE_REVISION_HISTORY: []})


# ── 02 · Plan ⇄ audit loop (plans 05-07) ───────────────────────────────────

def _run_optimizer(s: Any) -> dict:
    revision = int(s.get(STATE_ITERATION_COUNT, 0))
    draft = DraftPlan.model_validate(optimize_four_clinic_stops(
        health_evidence=s[STATE_HEALTH_EVIDENCE], mobility_evidence=s[STATE_MOBILITY_EVIDENCE],
        plan_request=s[STATE_PLAN_REQUEST], evidence_report=s[STATE_EVIDENCE_REPORT],
        non_demographic_feedback=s.get(STATE_NON_DEMOGRAPHIC_FEEDBACK) or None, revision_number=revision,
    ))
    history = list(s.get(STATE_REVISION_HISTORY) or [])
    s[STATE_DRAFT_PLAN] = draft.model_dump(mode="json")
    s[STATE_REVISION_HISTORY] = history + [draft.model_dump(mode="json")]
    return {
        "status": draft.status, "revision_number": revision,
        "stops": [{"rank": x.stop_rank, "saturday": x.assigned_saturday, "tract": tract_label(x.primary_tract_geoid),
                   "need": x.score_breakdown.composite_need_score} for x in draft.stops],
        "planner_notes": draft.planner_notes,
    }


def plan_four_stops(tool_context: ToolContext) -> dict:
    """Select four Saturday clinic stops with the deterministic coverage optimizer.

    Reads the evidence, request and any auditor feedback from session state, writes
    the DraftPlan to `draft_plan`, and returns a short summary of the chosen stops.
    """
    return _run_optimizer(tool_context.state)


def _ensure_draft_for_this_revision(callback_context: Any) -> None:
    """If the model answered without calling the tool, run it so the revision isn't stale."""
    s = callback_context.state
    draft = s.get(STATE_DRAFT_PLAN)
    if draft is None or draft.get("revision_number") != int(s.get(STATE_ITERATION_COUNT, 0)):
        _run_optimizer(s)


def _race_blind_before_model(callback_context: Any, llm_request: Any) -> None:
    # Checks what the model is actually sent. Session state is shared with the
    # auditor, so it legitimately holds audit_report by the revision.
    before_model_guardrail_callback(callback_context, llm_request)
    assert_race_blind_planner_input(str(llm_request.contents))


PLANNER_GRAPH_INSTRUCTION = """You are the CareBridge Siting Planner. You plan four Saturday mobile-clinic
stops for a county health department's outreach lead. Your posture is analytical, cited and hedged.

Call `plan_four_stops` exactly once. It runs the deterministic coverage optimizer on the evidence and any
auditor feedback, and records the draft. Never pick tracts or compute scores yourself.

Then reply in 2-4 sentences for the outreach lead: which tracts were chosen and why, in terms of uninsured
share, distance to a safety-net clinic and households without a car. Say that prevalence figures are CDC
PLACES model estimates and distances are straight-line upper bounds. If this is a revision, say what changed.
Never mention race, ethnicity or demographic parity.

This is revision {iteration_count}. Every revision needs a fresh `plan_four_stops` call, even if an
earlier draft exists.
Request: {plan_request}
Auditor feedback for this revision (empty on the first draft): {non_demographic_feedback?}
"""


def build_planner(settings: Settings) -> LlmAgent:
    return LlmAgent(
        name="siting_planner",
        model=settings.gemini_model_reasoning,
        description="Race-blind siting planner: calls the coverage optimizer and explains the draft.",
        instruction=PLANNER_GRAPH_INSTRUCTION,
        tools=[FunctionTool(func=plan_four_stops)],
        output_key="planner_summary",
        include_contents="none",
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
        generate_content_config=types.GenerateContentConfig(
            temperature=0.1, safety_settings=default_vertex_safety_settings()),
        before_model_callback=_race_blind_before_model,
        after_agent_callback=_ensure_draft_for_this_revision,
    )


# The auditor's scratch keys. Only the auditor's own tools and wrapper read them.
AUDITOR_IMPACT = "auditor_demographic_impact"
AUDITOR_ADDED_DEFECTS = "auditor_added_defects"

# Categories the LLM may add. Overlap and missing evidence stay rule-only, so those verdicts reproduce.
LLM_DEFECT_CATEGORIES = (DefectCategory.UNSUPPORTED_GRAIN_CLAIM, DefectCategory.INFEASIBLE_HOST_OR_TRANSIT,
                         DefectCategory.SENSITIVITY_INSTABILITY)
# Stricter than the planner guard's key list: feedback prose must not name a group or a parity figure at all.
DEMOGRAPHIC_WORDS = re.compile(r"\b(race|racial|ethnic\w*|black|african|hispanic|latin[oax]s?|asian|white|"
                               r"minorit\w*|parity|demographic\w*|acs)\b", re.I)


def _planner_claims(s: Any, draft: DraftPlan) -> str:
    """Everything the planner asserted in prose: the text a flagged defect must quote."""
    parts = [s.get("planner_summary") or "", *draft.planner_notes]
    for x in draft.stops:
        parts += [x.plain_language_rationale, *x.evidence_citations, *x.spatial_grain_disclosures]
    parts += [r.technical_deferral_rationale for r in draft.runner_up_tracts]
    if draft.sensitivity:
        parts.append(draft.sensitivity.notes)
    return " ".join(" ".join(parts).split()).lower()


def _impact(repo: BigQueryRepo, s: Any, draft: DraftPlan) -> DemographicImpactComparison:
    if s.get(AUDITOR_IMPACT):
        return DemographicImpactComparison.model_validate(s[AUDITOR_IMPACT])
    impact = demographic_impact(repo, draft, HealthEvidence.model_validate(s[STATE_HEALTH_EVIDENCE]))
    s[AUDITOR_IMPACT] = impact.model_dump(mode="json")
    return impact


def build_auditor_tools(repo: BigQueryRepo, max_revisions: int) -> list[FunctionTool]:
    def compare_demographic_impact(tool_context: ToolContext) -> dict:
        """Post-hoc ACS 2020 comparison of who the four catchments reach against the whole county.

        Auditor only. The numbers go into the audit report for human reviewers and never back to the planner.
        """
        s = tool_context.state
        impact = _impact(repo, s, DraftPlan.model_validate(s[STATE_DRAFT_PLAN]))
        return {"group_comparisons": impact.group_comparisons, "disparity_findings": impact.disparity_findings,
                "parity_floor": PARITY_FLOOR, "requires_human_equity_review": impact.requires_human_equity_review}

    def run_rule_audit(tool_context: ToolContext) -> dict:
        """Deterministic rule checks on the draft: stops under 5 km apart, missing stops or core evidence.

        Returns the rule verdict and defects, plus every claim the planner made in prose, for cross-examination.
        """
        s = tool_context.state
        draft = DraftPlan.model_validate(s[STATE_DRAFT_PLAN])
        report, _ = audit_draft(draft, _impact(repo, s, draft), max_revisions)
        return {
            "revision_audited": draft.revision_number, "rule_verdict": report.verdict.value,
            "rule_defects": [d.model_dump(mode="json") for d in report.non_demographic_defects],
            "planner_summary": s.get("planner_summary") or "",
            "planner_notes": draft.planner_notes,
            "stops": [{"rank": x.stop_rank, "tract": tract_label(x.primary_tract_geoid),
                       "venue": x.candidate_venue_name, "host_verified": x.host_verified,
                       "rationale": x.plain_language_rationale, "citations": x.evidence_citations,
                       "grain_disclosures": x.spatial_grain_disclosures} for x in draft.stops],
            "runner_ups": [{"tract": tract_label(r.tract_geoid), "need_rank": r.need_rank,
                            "reason": r.deferral_reason_code, "rationale": r.technical_deferral_rationale}
                           for r in draft.runner_up_tracts],
            "sensitivity": draft.sensitivity.model_dump(mode="json") if draft.sensitivity else None,
        }

    def flag_evidentiary_defect(category: str, affected_stop_ranks: list[int], quoted_claim: str,
                                description: str, remediation_instruction: str, tool_context: ToolContext) -> dict:
        """Record a defect the rule checks missed. The planner sees it on revision.

        Args:
            category: unsupported_grain_claim, infeasible_host_or_transit or sensitivity_instability.
            affected_stop_ranks: Stop ranks (1-4) the claim is about; empty if plan-wide.
            quoted_claim: The planner's words, verbatim. Rejected if they are not in the planner's text.
            description: What is wrong and which data grain or source contradicts it. No demographic content.
            remediation_instruction: What the planner must change. No demographic content.
        """
        s = tool_context.state
        draft = DraftPlan.model_validate(s[STATE_DRAFT_PLAN])
        try:
            cat = DefectCategory(category)
        except ValueError:
            cat = None
        if cat not in LLM_DEFECT_CATEGORIES:
            return {"accepted": False, "reason": f"category must be one of {[c.value for c in LLM_DEFECT_CATEGORIES]}"}
        quote = " ".join(quoted_claim.split()).lower()
        if len(quote) < 12 or quote not in _planner_claims(s, draft):
            return {"accepted": False, "reason": "quoted_claim is not verbatim in the planner's text. Cite or withdraw."}
        if DEMOGRAPHIC_WORDS.search(f"{description} {remediation_instruction} {quoted_claim}"):
            return {"accepted": False, "reason": "Demographic content cannot go back to the planner. "
                                                 "Put it in your summary for the human reviewer instead."}
        added = list(s.get(AUDITOR_ADDED_DEFECTS) or [])
        defect = NonDemographicAuditDefect(
            defect_id=f"D{draft.revision_number}-{cat.name}-{len(added) + 1}", category=cat,
            affected_stop_ranks=[r for r in affected_stop_ranks if 1 <= r <= 4],
            description=f'{description} (Planner wrote: "{quoted_claim.strip()}")',
            remediation_instruction=remediation_instruction,
        ).model_dump(mode="json")
        try:
            assert_race_blind_planner_input(defect)
        except PolicyViolationError as exc:
            return {"accepted": False, "reason": str(exc)}
        s[AUDITOR_ADDED_DEFECTS] = added + [defect]
        return {"accepted": True, "defect_id": defect["defect_id"]}

    return [FunctionTool(func=f) for f in (run_rule_audit, compare_demographic_impact, flag_evidentiary_defect)]


AUDITOR_GRAPH_INSTRUCTION = """You are the CareBridge Independent Equity & Rigor Auditor. The siting planner wants
its draft approved. Your job is to find the reasons it should not be. Your posture is skeptical, adversarial and
cite-or-reject: treat every claim in the draft as unsupported until a tool or the data grain proves it. You are
not the planner's colleague and you never soften a finding to help the plan through. You cannot rewrite the plan
and you never propose stops or tracts.

You have not seen how the draft was made, only what the planner claims. This is revision {iteration_count}.

1. Call `run_rule_audit`. Its rule defects (catchment overlap, missing core evidence) stand as found.
2. Call `compare_demographic_impact`. The planner was forbidden from seeing race and ethnicity; you are required
   to look. Report every group whose parity ratio is below the floor.
3. Cross-examine every sentence the planner wrote (`planner_summary`, stop rationales, citations, notes, runner-up
   rationales) against the data grains below. For each claim that overreaches, call `flag_evidentiary_defect`
   with the planner's words quoted verbatim:
   - Respiratory trends (COVID, flu, RSV) come from a 4-county HSA weekly series. Any claim that they rise, fall
     or differ in a tract or neighborhood is unsupported_grain_claim.
   - Distances are straight-line upper bounds to federal (CMS + HRSA) sites. Calling them travel time, bus time,
     drive time or "minutes away" is unsupported_grain_claim. No transit data is loaded: a claim about bus routes
     or Saturday service is infeasible_host_or_transit.
   - The clinic itself runs on Saturdays: "Saturday stop" or "Saturday clinic" names the van's schedule and is
     not a transit claim.
   - No host venue is confirmed. Calling a site booked, confirmed or secured is infeasible_host_or_transit.
   - CDC PLACES values are modeled estimates. Presenting them as counted cases, or ranking tracts on differences of
     a point or two, is unsupported_grain_claim.
   - A top-4 that is unstable under the sensitivity check (Jaccard below 0.50) presented as robust is
     sensitivity_instability.
   Flag only what you can quote. A rejected flag means you were wrong: do not retry it in other words.
4. Demographic findings never go into a flagged defect, and never name a group, a race, an ethnicity or a parity
   figure there. They go to human public-health review through your summary, not back to the planner.

The verdict is computed from the rule defects plus your accepted flags: approved if there are none; otherwise
rejected for one revision on revision 0, needs human review on revision 1.

Finish with the auditor summary for the human reviewer: 3-5 sentences of plain prose, no markdown, headings or
lists. The first sentence states the verdict and its main reason. Then each defect with the stop ranks it affects, what the post-hoc demographic comparison shows (with the ratios below the floor), and what
the plan cannot claim. Do not praise the plan.
"""


def build_auditor_llm(settings: Settings, repo: BigQueryRepo) -> LlmAgent:
    return LlmAgent(
        name="equity_rigor_auditor",
        model=settings.gemini_model_reasoning,
        description="Adversarial auditor: runs the rule and post-hoc demographic audits and flags overreaching claims.",
        instruction=AUDITOR_GRAPH_INSTRUCTION,
        tools=build_auditor_tools(repo, settings.max_audit_revisions),
        include_contents="none",
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
        generate_content_config=types.GenerateContentConfig(
            temperature=0.0, safety_settings=default_vertex_safety_settings()),
        before_model_callback=before_model_guardrail_callback,
    )


class EquityRigorAuditor(_StandIn):
    """Runs the auditor LLM in its own turn, then settles the verdict from the tools' deterministic results.

    Writes the same state keys and UI events the gate, the stream and the UI read.
    """
    max_revisions: int = 1

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        s = ctx.session.state
        draft = DraftPlan.model_validate(s[STATE_DRAFT_PLAN])
        start = _event(self, ctx, ui_event("equity_auditor", "start",
                                           f"Auditing draft {draft.revision_number} + post-hoc ACS comparison "
                                           "(auditor only, no access to planner reasoning)"),
                       state={AUDITOR_IMPACT: None, AUDITOR_ADDED_DEFECTS: []})
        # A content-bearing event of our own starts the auditor's turn here, so the LLM sees none of the planner's.
        start.content = types.Content(role="model", parts=[types.Part(text=f"Audit draft {draft.revision_number}.")])
        yield start

        summary = ""
        async for e in self.sub_agents[0].run_async(ctx):
            calls = [c.name for c in e.get_function_calls()]
            if calls:
                e.custom_metadata = {**(e.custom_metadata or {}),
                                     UI_EVENT: ui_event("equity_auditor", "tool", " + ".join(calls))}
            for r in e.get_function_responses():
                if r.name == "flag_evidentiary_defect" and (r.response or {}).get("accepted"):
                    e.custom_metadata = {**(e.custom_metadata or {}), UI_EVENT: ui_event(
                        "equity_auditor", "finding", f"Evidentiary defect {r.response['defect_id']} flagged")}
            if e.is_final_response() and e.content and e.content.parts:
                summary = "".join(p.text or "" for p in e.content.parts if not p.thought).strip() or summary
            yield e

        impact = _impact(self.repo, s, draft)
        rule_report, _ = audit_draft(draft, impact, self.max_revisions)
        defects = rule_report.non_demographic_defects + [
            NonDemographicAuditDefect.model_validate(d) for d in s.get(AUDITOR_ADDED_DEFECTS) or []]
        if not defects:
            verdict = AuditVerdict.APPROVED
        elif draft.revision_number < self.max_revisions:
            verdict = AuditVerdict.REJECTED_REVISION_REQUIRED
        else:
            verdict = AuditVerdict.NEEDS_HUMAN_REVIEW
        rejected = verdict == AuditVerdict.REJECTED_REVISION_REQUIRED
        feedback = [d.model_dump(mode="json") for d in defects] if rejected else []
        assert_race_blind_planner_input(feedback)
        report = AuditReport.model_validate({**rule_report.model_dump(mode="json"), "verdict": verdict.value,
                                             "non_demographic_defects": [d.model_dump(mode="json") for d in defects],
                                             "auditor_summary": summary or rule_report.auditor_summary})
        if not rejected:
            for f in impact.disparity_findings:
                yield _event(self, ctx, ui_event("equity_auditor", "finding", f"PARITY {f}"))
        pair = overlap_pair(draft)
        ranks = [pair[0].stop_rank, pair[1].stop_rank] if pair else next(
            (d.affected_stop_ranks for d in defects if d.affected_stop_ranks), None)
        label = "REJECT" if rejected else verdict.value.upper().replace("_", " ")
        yield _event(self, ctx, ui_event(
            "equity_auditor", "verdict", f"{label}: {report.auditor_summary.split('. ')[0].rstrip('.')}.",
            verdict="reject" if rejected else verdict.value,
            state_key=STATE_REVISION_REQUIRED if rejected else STATE_AUDIT_REPORT,
            draft_index=len(s.get(STATE_REVISION_HISTORY) or []) - 1,
            conflict_ranks=ranks if rejected else None),
            state={STATE_AUDIT_REPORT: report.model_dump(mode="json"), STATE_REVISION_REQUIRED: rejected,
                   STATE_NON_DEMOGRAPHIC_FEEDBACK: feedback})
        if rejected:
            yield _event(self, ctx, ui_event("equity_auditor", "state_write",
                                             f"{len(feedback)} non-demographic defect(s) sent back",
                                             state_key=STATE_NON_DEMOGRAPHIC_FEEDBACK))
        # The planner's next turn starts at the latest other agent's content, so this neutral line closes the
        # auditor's turn: its summary and tool responses (demographics included) stay out of the planner's context.
        close = _event(self, ctx)
        close.content = types.Content(role="model", parts=[types.Part(
            text=f"Audit of draft {draft.revision_number} closed: {label}.")])
        yield close


class AuditGate(BaseAgent):
    """Ends the loop when the audit didn't ask for a revision; otherwise bumps the revision number."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        s = ctx.session.state
        if s.get(STATE_REVISION_REQUIRED):
            yield _event(self, ctx, state={STATE_ITERATION_COUNT: int(s.get(STATE_ITERATION_COUNT, 0)) + 1})
        else:
            yield _event(self, ctx, state={STATE_FINAL_PLAN: s[STATE_DRAFT_PLAN]}, escalate=True)


# ── 03 · Outreach (plan 08) ────────────────────────────────────────────────

class CommunicationsStandIn(_StandIn):
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        s = ctx.session.state
        final = DraftPlan.model_validate(s.get(STATE_FINAL_PLAN) or s[STATE_DRAFT_PLAN])
        req = PlanRequest.model_validate(s[STATE_PLAN_REQUEST])
        yield _event(self, ctx, ui_event("communications", "start", "Drafting EN/ES notices from final_plan only"))
        outreach = draft_outreach(final, HealthEvidence.model_validate(s[STATE_HEALTH_EVIDENCE]), req.county_name)
        yield _event(self, ctx, ui_event("communications", "state_write",
                                         f"{len(outreach.stop_notices)} stop notices · "
                                         f"{len(outreach.unpicked_neighborhood_explanations)} \"why not here\" notes",
                                         state_key=STATE_OUTREACH_MESSAGES),
                     state={STATE_FINAL_PLAN: final.model_dump(mode="json"),
                            STATE_OUTREACH_MESSAGES: outreach.model_dump(mode="json")})


def build_graph(settings: Settings, repo: BigQueryRepo, mcp: BigQueryMcp | None = None) -> SequentialAgent:
    mcp = mcp or BigQueryMcp(settings)
    return SequentialAgent(name="carebridge", sub_agents=[
        ParallelAgent(name="evidence", sub_agents=[
            HealthAccessAgent(name="health_access", mcp=mcp, sub_agents=[build_health_access_llm(settings, mcp)]),
            TransitCommunityStandIn(name="transit_community", repo=repo),
        ]),
        EvidenceValidatorStandIn(name="evidence_validator", repo=repo),
        LoopAgent(name="plan_audit_loop", max_iterations=settings.max_audit_revisions + 1, sub_agents=[
            build_planner(settings),
            EquityRigorAuditor(name="equity_auditor", repo=repo, max_revisions=settings.max_audit_revisions,
                               sub_agents=[build_auditor_llm(settings, repo)]),
            AuditGate(name="gate"),
        ]),
        CommunicationsStandIn(name="communications", repo=repo),
    ])
