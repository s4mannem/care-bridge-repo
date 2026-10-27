"""`POST /v1/ask`: the outreach lead's conversation about a plan, or about making one.

The answer names the grain it rests on and refuses claims the data can't
support. Questions are screened for prompt injection before any agent sees them.

Ask answers from the plan the gateway stored when it finished (`PlanStore`), so
a question never runs the agents again. With `CAREBRIDGE_ASK_ENGINE=gemini` it
is a conversation (`agents/chat.py`) that can also propose a plan; otherwise,
or when the model call fails, the rule-based `ask_stub` answers.
"""
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from ...agents import chat
from ...agents.runner import AgentRunner
from ...config import Settings
from ...contracts.api_models import PlanResponse
from ...contracts.interaction_models import AskRequest, AskResponse
from ...data.plans import PlanStore
from ...security import ModelArmorScreener
from ..deps import get_app_settings, get_plan_store, get_runner
from ..errors import GatewayError

router = APIRouter(tags=["ask"])


async def _plan_for(body: AskRequest, rid: str, runner: AgentRunner, plans: PlanStore,
                    settings: Settings) -> PlanResponse | None:
    if body.plan_request_id:
        try:
            if (stored := plans.get(body.plan_request_id)) is not None:
                return stored
        except Exception:  # noqa: BLE001 - a store outage degrades to "no plan", never a 500
            pass
    # The stub's plans are recordings, so fetching one is instant; the rule-based
    # Ask has always answered from them. The conversation gets one only for a plan
    # the UI actually has, so it never talks about a draft nobody has seen. The ADK
    # runner's plans cost a full agent run, which Ask never triggers.
    if runner.name == "stub" and (body.plan_request_id or settings.ask_engine == "rules"):
        return await runner.plan(body.plan, rid)
    return None


@router.post("/ask", response_model=AskResponse)
async def ask(body: AskRequest, request: Request,
              runner: Annotated[AgentRunner, Depends(get_runner)],
              plans: Annotated[PlanStore, Depends(get_plan_store)],
              settings: Annotated[Settings, Depends(get_app_settings)]) -> AskResponse:
    screener = ModelArmorScreener()
    for text in (body.question, body.plan.county_name, *(t.text for t in body.history if t.role == "user")):
        ok, reason = screener.screen_input(text)
        if not ok:
            raise GatewayError(400, "blocked_input", reason)
    rid = request.state.request_id
    plan = await _plan_for(body, rid, runner, plans, settings)
    if settings.ask_engine == "gemini":
        return await chat.converse(body, plan, rid, settings)
    return chat.rules_answer(body, plan, rid)
