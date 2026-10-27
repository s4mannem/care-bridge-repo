"""`POST /v1/plan`: hand a request to the agent runner and return the Clinic Plan.

The body is an untyped dict until the contracts land in `carebridge/contracts/`;
then it becomes `PlanRequest -> PlanResponse` (mirrored by `ui/lib/models.dart`).
"""
import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends

from ...agents.runner import AgentRunner
from ...config import Settings
from ..deps import get_app_settings, get_runner
from ..errors import GatewayError

router = APIRouter(tags=["plan"])


@router.post("/plan")
async def create_plan(
    request: Annotated[dict[str, Any], Body()],
    runner: Annotated[AgentRunner, Depends(get_runner)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> dict[str, Any]:
    try:
        return await asyncio.wait_for(runner.plan(request), timeout=settings.plan_timeout_s)
    except TimeoutError:
        raise GatewayError(504, "plan_timeout", f"Agents did not finish within {settings.plan_timeout_s:.0f} s.")
