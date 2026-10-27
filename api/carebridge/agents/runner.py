"""The seam between the API and the agents.

Routes call `AgentRunner.plan()` and never touch ADK directly, so the agent lane
can change its graph without changing the API. `CAREBRIDGE_AGENT_ENGINE` picks
the runner:

- `stub`: returns the recorded Fulton plan for the request's strategy and
          defect toggle, so the UI works end to end before the agents exist.
- `adk`:  the ADK multi-agent graph (coordinator, evidence, siting planner,
          equity auditor, communications), sharing one `session.state`.
"""
from typing import Protocol

from ..api.errors import GatewayError
from ..config import Settings
from ..contracts.api_models import PlanRequest, PlanResponse
from ..mocks.recorded import RECORDED_COUNTY_FIPS, recorded_plan


class AgentRunner(Protocol):
    name: str

    async def plan(self, request: PlanRequest, request_id: str) -> PlanResponse: ...


class StubRunner:
    name = "stub"

    async def plan(self, request: PlanRequest, request_id: str) -> PlanResponse:
        recorded = recorded_plan(request)
        if recorded is None:
            raise GatewayError(404, "county_not_available",
                               f"Only {RECORDED_COUNTY_FIPS} has a recorded plan (CAREBRIDGE_AGENT_ENGINE=stub).")
        # Keep the recording's telemetry (source=recorded_fixture) but answer with this request's id.
        return recorded.model_copy(update={"request_id": request_id})


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


def build_runner(settings: Settings) -> AgentRunner:
    if settings.agent_engine == "adk":
        return AdkRunner(settings)
    return StubRunner()
