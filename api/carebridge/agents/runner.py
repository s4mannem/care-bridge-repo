"""The seam between the API and the agents.

Routes call `AgentRunner.plan()` and never touch ADK directly, so the agent lane
can change its graph without changing the API. `CAREBRIDGE_AGENT_ENGINE` picks
the runner:

- `stub`: answers 501. Lets the API and UI wiring be tested before agents exist.
- `adk`:  the ADK multi-agent graph (coordinator, evidence, siting planner,
          equity auditor, communications), sharing one `session.state`.
"""
from typing import Any, Protocol

from ..api.errors import GatewayError
from ..config import Settings


class AgentRunner(Protocol):
    name: str

    async def plan(self, request: dict[str, Any]) -> dict[str, Any]: ...


class StubRunner:
    name = "stub"

    async def plan(self, request: dict[str, Any]) -> dict[str, Any]:
        raise GatewayError(501, "not_implemented", "No agent runner is configured yet (CAREBRIDGE_AGENT_ENGINE=stub).")


class AdkRunner:
    name = "adk"

    def __init__(self, settings: Settings):
        try:
            import google.adk  # noqa: F401
        except ImportError as exc:
            raise RuntimeError("CAREBRIDGE_AGENT_ENGINE=adk needs `pip install -e '.[agents]'`") from exc
        self.settings = settings

    async def plan(self, request: dict[str, Any]) -> dict[str, Any]:
        # Next step: build the Workflow in carebridge/agents/graph.py, run it with
        # InMemoryRunner, and map session.state["final_plan"] etc. to the response.
        raise GatewayError(501, "not_implemented", "ADK graph is not built yet.")


def build_runner(settings: Settings) -> AgentRunner:
    if settings.agent_engine == "adk":
        return AdkRunner(settings)
    return StubRunner()
