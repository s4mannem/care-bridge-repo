"""`POST /v1/plan`: hand a `PlanRequest` to the agent runner and return the Clinic Plan.

The body and response are the plan 00 contracts; `ui/lib/models.dart` mirrors
them. Free-text input is screened before any agent sees it, and the response is
checked for personal data before it leaves the gateway.
"""
import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from ...agents.runner import AgentRunner
from ...config import Settings
from ...contracts.api_models import PlanRequest, PlanResponse
from ...security import ModelArmorScreener, PolicyViolationError, assert_no_pii_in_payload
from ..deps import get_app_settings, get_runner
from ..errors import GatewayError

router = APIRouter(tags=["plan"])


@router.post("/plan", response_model=PlanResponse)
async def create_plan(
    body: PlanRequest,
    request: Request,
    runner: Annotated[AgentRunner, Depends(get_runner)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> PlanResponse:
    # county_name is the only free text in the request; the rest is pattern-checked by the contract.
    ok, reason = ModelArmorScreener().screen_input(body.county_name)
    if not ok:
        raise GatewayError(400, "blocked_input", reason)

    try:
        response = await asyncio.wait_for(runner.plan(body, request.state.request_id),
                                          timeout=settings.plan_timeout_s)
    except TimeoutError:
        raise GatewayError(504, "plan_timeout", f"Agents did not finish within {settings.plan_timeout_s:.0f} s.")

    try:
        assert_no_pii_in_payload(response.model_dump())
    except PolicyViolationError as exc:
        raise GatewayError(502, "pii_in_response", f"Response withheld: {exc}")
    return response
