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


class AdkRunner:
    """Runs the ADK graph in-process: one in-memory session per request."""

    name = "adk"

    def __init__(self, settings: Settings):
        try:
            from google.adk.runners import Runner
            from google.adk.sessions import InMemorySessionService
        except ImportError as exc:
            raise RuntimeError("CAREBRIDGE_AGENT_ENGINE=adk needs `pip install -e '.[agents]'`") from exc
        from ..data.bigquery import BigQueryRepo
        from .graph import build_graph

        self.settings = settings
        self.sessions = InMemorySessionService()
        self.runner = Runner(app_name="carebridge", agent=build_graph(settings, BigQueryRepo(settings)),
                             session_service=self.sessions)
        # Finished plans by request id, for Ask. Per instance; Ask falls back to
        # answering from a fresh run's recorded twin if the plan isn't here.
        self._plans: dict[str, PlanResponse] = {}

    async def stream(self, request: PlanRequest, request_id: str) -> AsyncIterator[AgentEvent | PlanResponse]:
        import time

        from google.genai import types

        from ..contracts.state_keys import (
            STATE_DRAFT_PLAN,
            STATE_FINAL_PLAN,
            STATE_PLAN_REQUEST,
            STATE_REQUEST_ID,
            STATE_REVISION_HISTORY,
        )
        from ..contracts.plan_models import DraftPlan
        from .graph import UI_EVENT
        from .response import build_plan_response
        from .trace import STRATEGY_LABELS, tract_label

        if request.county_fips != self.settings.default_county_fips:
            raise GatewayError(404, "county_not_available",
                               f"Only {self.settings.default_county_fips} is loaded in BigQuery.")
        t0 = time.monotonic()

        def ev(agent: str, kind: str, message: str, **kw) -> AgentEvent:
            return AgentEvent(t_ms=int((time.monotonic() - t0) * 1000), agent=agent, kind=kind, message=message, **kw)

        session = await self.sessions.create_session(
            app_name="carebridge", user_id="outreach_lead",
            state={STATE_PLAN_REQUEST: request.model_dump(mode="json"), STATE_REQUEST_ID: request_id})
        yield ev("coordinator", "start",
                 f"POST /v1/plan · {request.county_name} · {STRATEGY_LABELS.get(request.strategy, request.strategy)}"
                 + (" · simulate draft-0 defect" if request.simulate_first_draft_defect else ""),
                 state_key="plan_request")
        drafts = 0
        message = types.Content(role="user", parts=[types.Part(text="Plan the four Saturday stops.")])
        async for e in self.runner.run_async(user_id="outreach_lead", session_id=session.id, new_message=message):
            ui = (e.custom_metadata or {}).get(UI_EVENT)
            if ui:
                yield AgentEvent(t_ms=int((time.monotonic() - t0) * 1000), **ui)
            delta = e.actions.state_delta if e.actions else {}
            if e.author != "siting_planner" and STATE_DRAFT_PLAN not in delta:
                continue
            for call in e.get_function_calls():
                yield ev("siting_planner", "start",
                         "Race-blind planning" if drafts == 0 else "Revising with non_demographic_feedback only")
                yield ev("optimizer", "tool", f"{call.name} → optimize_four_clinic_stops(revision={drafts})")
            if STATE_DRAFT_PLAN in delta:
                d = DraftPlan.model_validate(delta[STATE_DRAFT_PLAN])
                yield ev("siting_planner", "state_write",
                         f"Draft {d.revision_number}: " + ", ".join(tract_label(x.primary_tract_geoid) for x in d.stops),
                         state_key="draft_plan", draft_index=drafts, draft=d)
                drafts += 1
            if e.is_final_response() and e.content and e.content.parts and e.content.parts[0].text:
                yield ev("siting_planner", "finding", e.content.parts[0].text.strip())

        state = (await self.sessions.get_session(app_name="carebridge", user_id="outreach_lead",
                                                 session_id=session.id)).state
        response = build_plan_response(request_id, request, state, (time.monotonic() - t0) * 1000,
                                       self.settings.gemini_model_reasoning)
        if state.get(STATE_FINAL_PLAN):
            yield ev("coordinator", "state_write",
                     f"final_plan · status={response.status} · needs_human_review="
                     f"{str(response.needs_human_review).lower()}", state_key="final_plan")
        yield ev("coordinator", "done",
                 "Plan ready, pending human review" if response.needs_human_review else "Plan ready")
        self._plans[request_id] = response
        yield response

    async def plan(self, request: PlanRequest, request_id: str) -> PlanResponse:
        result = None
        async for item in self.stream(request, request_id):
            result = item
        return result

    async def ask(self, request: AskRequest, request_id: str) -> AskResponse:
        plan = self._plans.get(request.plan_request_id or "")
        if plan is None:
            # Not on this instance: answer from a fresh deterministic run of the same request.
            plan = await self.plan(request.plan, request_id)
        return answer(request.question, plan, request_id)


def build_runner(settings: Settings) -> AgentRunner:
    if settings.agent_engine == "adk":
        return AdkRunner(settings)
    return StubRunner(pace=settings.stub_stream_pace)
