"""The CareBridge ADK graph (plan 09) and how a run becomes a PlanResponse.

    SequentialAgent carebridge
     ├─ ParallelAgent evidence: health_access ║ transit_community
     ├─ evidence_validator
     ├─ LoopAgent(max_iterations=2): siting_planner → equity_auditor → gate
     └─ communications

The siting planner is the team's Gemini LlmAgent (plan 06) with the coverage
optimizer as its tool. The other agents are deterministic stand-ins over
`carebridge/tools` until their LLM versions land; each emits the same state
keys the real agent will, so swapping one in changes nothing downstream.
Every node attaches a UI-facing `AgentEvent` to its ADK event so the API can
stream the run as it happens.
"""
from collections.abc import AsyncGenerator
from typing import Any

from google.adk.agents import BaseAgent, LlmAgent, LoopAgent, ParallelAgent, SequentialAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.adk.tools import FunctionTool, ToolContext
from google.genai import types
from pydantic import ConfigDict

from ..config import Settings
from ..contracts.api_models import PlanRequest
from ..contracts.audit_models import AuditVerdict
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
from ..security.model_armor import default_vertex_safety_settings
from ..security.owasp_guardrails import before_model_guardrail_callback
from ..security.race_blind_guard import assert_race_blind_planner_input
from ..tools.audit import audit_draft, demographic_impact, draft_outreach
from ..tools.evidence import fetch_health_evidence, unavailable_mobility_evidence, validate_evidence
from ..tools.optimizer.tool import optimize_four_clinic_stops
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

class HealthAccessStandIn(_StandIn):
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        req = PlanRequest.model_validate(ctx.session.state[STATE_PLAN_REQUEST])
        yield _event(self, ctx, ui_event("health_access", "start",
                                         "Querying burden_tracts + tract_access in BigQuery", parallel=True))
        health = fetch_health_evidence(self.repo, req.county_fips, req.county_name)
        yield _event(self, ctx, ui_event("health_access", "state_write",
                                         f"{len(health.tracts)} tracts with burden and two distances",
                                         parallel=True, state_key=STATE_HEALTH_EVIDENCE),
                     state={STATE_HEALTH_EVIDENCE: health.model_dump(mode="json")})


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


class EquityAuditorStandIn(_StandIn):
    max_revisions: int = 1

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        s = ctx.session.state
        draft = DraftPlan.model_validate(s[STATE_DRAFT_PLAN])
        yield _event(self, ctx, ui_event("equity_auditor", "start",
                                         f"Auditing draft {draft.revision_number} + post-hoc ACS comparison "
                                         "(auditor only)"))
        impact = demographic_impact(self.repo, draft, HealthEvidence.model_validate(s[STATE_HEALTH_EVIDENCE]))
        report, feedback = audit_draft(draft, impact, self.max_revisions)
        rejected = report.verdict == AuditVerdict.REJECTED_REVISION_REQUIRED
        if not rejected:
            for f in impact.disparity_findings:
                yield _event(self, ctx, ui_event("equity_auditor", "finding", f"PARITY {f}"))
        pair = overlap_pair(draft)
        verdict = {"rejected_revision_required": "reject"}.get(report.verdict.value, report.verdict.value)
        label = "REJECT" if rejected else report.verdict.value.upper().replace("_", " ")
        yield _event(self, ctx, ui_event(
            "equity_auditor", "verdict", f"{label}: {report.auditor_summary.split('. ')[0]}.",
            verdict=verdict, state_key=STATE_REVISION_REQUIRED if rejected else STATE_AUDIT_REPORT,
            draft_index=len(s.get(STATE_REVISION_HISTORY) or []) - 1,
            conflict_ranks=[pair[0].stop_rank, pair[1].stop_rank] if rejected and pair else None),
            state={STATE_AUDIT_REPORT: report.model_dump(mode="json"), STATE_REVISION_REQUIRED: rejected,
                   STATE_NON_DEMOGRAPHIC_FEEDBACK: feedback})
        if rejected:
            yield _event(self, ctx, ui_event("equity_auditor", "state_write",
                                             f"{len(feedback)} non-demographic defect(s) sent back",
                                             state_key=STATE_NON_DEMOGRAPHIC_FEEDBACK))


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


def build_graph(settings: Settings, repo: BigQueryRepo) -> SequentialAgent:
    return SequentialAgent(name="carebridge", sub_agents=[
        ParallelAgent(name="evidence", sub_agents=[
            HealthAccessStandIn(name="health_access", repo=repo),
            TransitCommunityStandIn(name="transit_community", repo=repo),
        ]),
        EvidenceValidatorStandIn(name="evidence_validator", repo=repo),
        LoopAgent(name="plan_audit_loop", max_iterations=settings.max_audit_revisions + 1, sub_agents=[
            build_planner(settings),
            EquityAuditorStandIn(name="equity_auditor", repo=repo, max_revisions=settings.max_audit_revisions),
            AuditGate(name="gate"),
        ]),
        CommunicationsStandIn(name="communications", repo=repo),
    ])
