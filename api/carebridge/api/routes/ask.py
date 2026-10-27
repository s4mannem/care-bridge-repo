"""`POST /v1/ask`: a follow-up question about a plan, answered by the agents.

The answer names the grain it rests on and refuses claims the data can't
support. Questions are screened for prompt injection before any agent sees them.
"""
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from ...agents.runner import AgentRunner
from ...contracts.interaction_models import AskRequest, AskResponse
from ...security import ModelArmorScreener
from ..deps import get_runner
from ..errors import GatewayError

router = APIRouter(tags=["ask"])


@router.post("/ask", response_model=AskResponse)
async def ask(body: AskRequest, request: Request,
              runner: Annotated[AgentRunner, Depends(get_runner)]) -> AskResponse:
    for text in (body.question, body.plan.county_name):
        ok, reason = ModelArmorScreener().screen_input(text)
        if not ok:
            raise GatewayError(400, "blocked_input", reason)
    return await runner.ask(body, request.state.request_id)
