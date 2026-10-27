"""The seam between the API and the agents.

Routes call `AgentRunner.plan()` and never touch ADK directly, so the agent lane
can change its graph without changing the API. `CAREBRIDGE_AGENT_ENGINE` picks
the runner:

- `stub`: returns the recorded Fulton plan for the request's strategy and
          defect toggle, so the UI works end to end before the agents exist.
          `stream()` replays the run's events at their recorded pace.
- `adk`:  the ADK multi-agent graph (coordinator, evidence, siting planner,
          equity auditor, communications), sharing one `session.state`.
"""
import asyncio
from collections.abc import AsyncIterator
from typing import Protocol

from ..api.errors import GatewayError
from ..config import Settings
from ..contracts.api_models import PlanRequest, PlanResponse
from ..contracts.interaction_models import AgentEvent, AskRequest, AskResponse
from ..mocks.recorded import RECORDED_COUNTY_FIPS, recorded_plan
from .ask_stub import answer
from .trace import build_trace


class AgentRunner(Protocol):
    name: str

    async def plan(self, request: PlanRequest, request_id: str) -> PlanResponse: ...

    def stream(self, request: PlanRequest, request_id: str) -> AsyncIterator[AgentEvent | PlanResponse]:
        """Events as the agents produce them, then the PlanResponse last."""
        ...

    async def ask(self, request: AskRequest, request_id: str) -> AskResponse: ...


class StubRunner:
    name = "stub"

    def __init__(self, pace: float = 1.0):
        # 1.0 replays the recorded timing; 0 streams everything at once (tests).
        self.pace = pace

    async def stream(self, request: PlanRequest, request_id: str) -> AsyncIterator[AgentEvent | PlanResponse]:
        response = await self.plan(request, request_id)
        last = 0
        for event in build_trace(response, request):
            if self.pace:
                await asyncio.sleep((event.t_ms - last) / 1000 * self.pace)
            last = event.t_ms
            yield event
        yield response

    async def plan(self, request: PlanRequest, request_id: str) -> PlanResponse:
        recorded = recorded_plan(request)
        if recorded is None:
            raise GatewayError(404, "county_not_available",
                               f"Only {RECORDED_COUNTY_FIPS} has a recorded plan (CAREBRIDGE_AGENT_ENGINE=stub).")
        # Keep the recording's telemetry (source=recorded_fixture) but answer with this request's id.
        return recorded.model_copy(update={"request_id": request_id})

    async def ask(self, request: AskRequest, request_id: str) -> AskResponse:
        return answer(request.question, await self.plan(request.plan, request_id), request_id)


# Team agent names (ADK event authors) → the names the UI's graph and timeline use.
UI_AGENT = {
    "health_access_agent": "health_access",
    "transit_community_agent": "transit_community",
    "evidence_validator_agent": "evidence_validator",
    "siting_planner_agent": "siting_planner",
    "equity_rigor_auditor": "equity_auditor",
    "audit_loop_exit_gate": "coordinator",
    "community_communications_agent": "communications",
}
START_MESSAGE = {
    "health_access": "Querying v_burden_tracts, v_tract_access, care sites and disease via the data plane",
    "transit_community": "Querying MARTA Saturday transit, USDA food access and IMLS venue views",
    "evidence_validator": "Running the evidence validator's check() and note() rules",
    "equity_auditor": "Auditing the draft (no access to the planner's reasoning) + post-hoc demographics",
    "communications": "Drafting EN/ES notices from final_plan only",
}


class AdkRunner:
    """Runs the team's coordinator workflow (`agents/coordinator`) on ADK, one in-memory session per request."""

    name = "adk"

    def __init__(self, settings: Settings):
        try:
            from google.adk.runners import Runner
            from google.adk.sessions import InMemorySessionService
        except ImportError as exc:
            raise RuntimeError("CAREBRIDGE_AGENT_ENGINE=adk needs `pip install -e '.[agents]'`") from exc
        from .coordinator.adk_adapter import build_adk_coordinator_workflow

        self.settings = settings
        self.sessions = InMemorySessionService()
        self.runner = Runner(app_name="carebridge", agent=build_adk_coordinator_workflow(),
                             session_service=self.sessions)
        self._plans: dict[str, PlanResponse] = {}

    async def stream(self, request: PlanRequest, request_id: str) -> AsyncIterator[AgentEvent | PlanResponse]:
        import time

        from google.genai import types

        from ..contracts.audit_models import AuditReport
        from ..contracts.evidence_models import EvidenceReport, HealthEvidence, MobilityEvidence
        from ..contracts.plan_models import DraftPlan
        from .coordinator.runner import assemble_plan_response_from_state
        from .trace import STRATEGY_LABELS, overlap_pair, tract_label

        if request.county_fips != self.settings.default_county_fips:
            raise GatewayError(404, "county_not_available",
                               f"Only {self.settings.default_county_fips} is loaded in BigQuery.")
        t0 = time.monotonic()

        def ev(agent: str, kind: str, message: str, **kw) -> AgentEvent:
            return AgentEvent(t_ms=int((time.monotonic() - t0) * 1000), agent=agent, kind=kind,
                              message=message[:400], **kw)

        session = await self.sessions.create_session(
            app_name="carebridge", user_id="outreach_lead",
            state={"plan_request": request.model_dump(mode="json"), "request_id": request_id,
                   "revision_history": []})
        yield ev("coordinator", "start",
                 f"POST /v1/plan · {request.county_name} · {STRATEGY_LABELS.get(request.strategy, request.strategy)}"
                 + (" · simulate draft-0 defect" if request.simulate_first_draft_defect else ""),
                 state_key="plan_request")
        started: set[str] = set()
        drafts = 0
        prompt = (f"Generate a 4-stop Saturday mobile health clinic plan for {request.county_name} County "
                  f"(FIPS {request.county_fips}, strategy={request.strategy}).")
        message = types.Content(role="user", parts=[types.Part(text=prompt)])
        async for e in self.runner.run_async(user_id="outreach_lead", session_id=session.id, new_message=message):
            agent = UI_AGENT.get(e.author)
            if agent is None:
                continue
            parallel = agent in ("health_access", "transit_community")
            for call in e.get_function_calls():
                if agent == "siting_planner":
                    yield ev(agent, "start", "Race-blind planning" if drafts == 0
                             else "Revising with non_demographic_feedback only")
                    yield ev("optimizer", "tool", f"{call.name}(revision={drafts})")
                elif agent not in started or agent == "equity_auditor":
                    yield ev(agent, "start", START_MESSAGE.get(agent, call.name), parallel=parallel)
                started.add(agent)
            delta = e.actions.state_delta if e.actions else {}
            if "health_evidence" in delta:
                h = HealthEvidence.model_validate(delta["health_evidence"])
                yield ev(agent, "state_write", f"{len(h.tracts)} tracts with burden and two distances",
                         parallel=True, state_key="health_evidence")
            if "mobility_evidence" in delta:
                m = MobilityEvidence.model_validate(delta["mobility_evidence"])
                venues = sum(len(t.candidate_venues) for t in m.tract_mobility)
                yield ev(agent, "state_write" if m.marta_gtfs_available else "skip",
                         f"{len(m.tract_mobility)} tracts with Saturday MARTA service · {venues} candidate venues"
                         if m.marta_gtfs_available else "MARTA / USDA / IMLS views unavailable",
                         parallel=True, state_key="mobility_evidence")
            if "evidence_report" in delta:
                r = EvidenceReport.model_validate(delta["evidence_report"])
                for c in r.checks:
                    if c.verdict != "PASS":
                        yield ev(agent, "finding", f"{c.verdict} {c.check_name}: {c.detail}")
                yield ev(agent, "state_write",
                         f"{sum(c.verdict == 'PASS' for c in r.checks)} checks passed · core tables "
                         f"{'ready' if r.core_tables_ready else 'NOT ready'}", state_key="evidence_report")
            if "draft_plan" in delta:
                d = DraftPlan.model_validate(delta["draft_plan"])
                yield ev("siting_planner", "state_write",
                         f"Draft {d.revision_number}: " + ", ".join(tract_label(x.primary_tract_geoid) for x in d.stops),
                         state_key="draft_plan", draft_index=drafts, draft=d)
                drafts += 1
            if "audit_report" in delta:
                a = AuditReport.model_validate(delta["audit_report"])
                v = a.verdict.value if hasattr(a.verdict, "value") else str(a.verdict)
                rejected = v == "rejected_revision_required"
                ranks = sorted({n for d in a.non_demographic_defects for n in d.affected_stop_ranks})[:2]
                if rejected and len(ranks) < 2:
                    draft = DraftPlan.model_validate(delta.get("draft_plan") or
                                                     (await self._state(session.id)).get("draft_plan"))
                    pair = overlap_pair(draft)
                    ranks = [pair[0].stop_rank, pair[1].stop_rank] if pair else ranks
                if not rejected:
                    for f in a.demographic_impact.disparity_findings:
                        yield ev(agent, "finding", f"PARITY {f}")
                label = "REJECT" if rejected else v.upper().replace("_", " ")
                yield ev(agent, "verdict", f"{label}: {a.auditor_summary.split('. ')[0]}.",
                         verdict="reject" if rejected else v,
                         state_key="revision_required" if rejected else "audit_report",
                         draft_index=drafts - 1, conflict_ranks=ranks if rejected and len(ranks) == 2 else None)
                if rejected:
                    yield ev(agent, "state_write",
                             f"{len(a.non_demographic_defects)} non-demographic defect(s) sent back",
                             state_key="non_demographic_feedback")
            if "outreach_messages" in delta:
                o = delta["outreach_messages"]
                yield ev(agent, "state_write",
                         f"{len(o.get('stop_notices', []))} stop notices · "
                         f"{len(o.get('unpicked_neighborhood_explanations', []))} \"why not here\" notes",
                         state_key="outreach_messages")
            if agent == "siting_planner" and e.is_final_response() and e.content and e.content.parts \
                    and e.content.parts[0].text:
                yield ev(agent, "finding", e.content.parts[0].text.strip())

        state = await self._state(session.id)
        response = assemble_plan_response_from_state(request, state, request_id)
        response.telemetry_summary.update({"source": "adk", "model": self.settings.gemini_model_reasoning,
                                           "iterations": len(response.revision_history),
                                           "elapsed_ms": int((time.monotonic() - t0) * 1000)})
        if state.get("final_plan"):
            yield ev("coordinator", "state_write",
                     f"final_plan · status={response.status} · needs_human_review="
                     f"{str(response.needs_human_review).lower()}", state_key="final_plan")
        yield ev("coordinator", "done",
                 "Plan ready, pending human review" if response.needs_human_review else "Plan ready")
        self._plans[request_id] = response
        yield response

    async def _state(self, session_id: str) -> dict:
        s = await self.sessions.get_session(app_name="carebridge", user_id="outreach_lead", session_id=session_id)
        return s.state

    async def plan(self, request: PlanRequest, request_id: str) -> PlanResponse:
        result = None
        async for item in self.stream(request, request_id):
            result = item
        return result

    async def ask(self, request: AskRequest, request_id: str) -> AskResponse:
        plan = self._plans.get(request.plan_request_id or "")
        if plan is None:
            plan = await self.plan(request.plan, request_id)
        return answer(request.question, plan, request_id)


def build_runner(settings: Settings) -> AgentRunner:
    if settings.agent_engine == "adk":
        return AdkRunner(settings)
    return StubRunner(pace=settings.stub_stream_pace)
