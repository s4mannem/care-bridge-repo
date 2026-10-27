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
    name = "adk"

    def __init__(self, settings: Settings):
        try:
            import google.adk  # noqa: F401
        except ImportError as exc:
            raise RuntimeError("CAREBRIDGE_AGENT_ENGINE=adk needs `pip install -e '.[agents]'`") from exc
        self.settings = settings

    async def plan(self, request: PlanRequest, request_id: str) -> PlanResponse:
        # Next step: build the Workflow in carebridge/agents/graph.py, run it with
        # InMemoryRunner, and map session.state["final_plan"] etc. to the response.
        raise GatewayError(501, "not_implemented", "ADK graph is not built yet.")

    async def stream(self, request: PlanRequest, request_id: str) -> AsyncIterator[AgentEvent | PlanResponse]:
        # Will forward CareBridgeTelemetryPlugin events as the graph runs.
        raise GatewayError(501, "not_implemented", "ADK graph is not built yet.")
        yield  # pragma: no cover  (makes this an async generator)

    async def ask(self, request: AskRequest, request_id: str) -> AskResponse:
        raise GatewayError(501, "not_implemented", "ADK graph is not built yet.")


def build_runner(settings: Settings) -> AgentRunner:
    if settings.agent_engine == "adk":
        return AdkRunner(settings)
    return StubRunner(pace=settings.stub_stream_pace)
