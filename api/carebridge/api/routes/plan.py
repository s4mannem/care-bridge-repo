"""`POST /v1/plan` and `POST /v1/plan/stream`: run the agents and return the Clinic Plan.

The body and response are the plan 00 contracts; `ui/lib/models.dart` mirrors
them. Free-text input is screened before any agent sees it, and the response is
checked for personal data before it leaves the gateway.

The stream variant sends server-sent events: `agent` (an AgentEvent) as each
step happens, then one `plan` (the PlanResponse), or `error` if the run fails
after the stream has opened.
"""
import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from ...agents.runner import AgentRunner
from ...config import Settings
from ...contracts.api_models import PlanRequest, PlanResponse
from ...contracts.interaction_models import AgentEvent
from ...security import ModelArmorScreener, PolicyViolationError, assert_no_pii_in_payload
from ..deps import get_app_settings, get_runner
from ..errors import GatewayError

router = APIRouter(tags=["plan"])


def _screen(body: PlanRequest) -> None:
    # county_name is the only free text in the request; the rest is pattern-checked by the contract.
    ok, reason = ModelArmorScreener().screen_input(body.county_name)
    if not ok:
        raise GatewayError(400, "blocked_input", reason)


def _check_pii(response: PlanResponse) -> None:
    try:
        assert_no_pii_in_payload(response.model_dump())
    except PolicyViolationError as exc:
        raise GatewayError(502, "pii_in_response", f"Response withheld: {exc}")


@router.post("/plan", response_model=PlanResponse)
async def create_plan(
    body: PlanRequest,
    request: Request,
    runner: Annotated[AgentRunner, Depends(get_runner)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> PlanResponse:
    _screen(body)
    try:
        response = await asyncio.wait_for(runner.plan(body, request.state.request_id),
                                          timeout=settings.plan_timeout_s)
    except TimeoutError:
        raise GatewayError(504, "plan_timeout", f"Agents did not finish within {settings.plan_timeout_s:.0f} s.")
    _check_pii(response)
    return response


def _sse(event: str, data: str) -> str:
    return f"event: {event}\ndata: {data}\n\n"


@router.post("/plan/stream", response_class=StreamingResponse,
             responses={200: {"content": {"text/event-stream": {}}}})
async def stream_plan(
    body: PlanRequest,
    request: Request,
    runner: Annotated[AgentRunner, Depends(get_runner)],
    settings: Annotated[Settings, Depends(get_app_settings)],
) -> StreamingResponse:
    _screen(body)
    rid = request.state.request_id
    items = runner.stream(body, rid)
    # Pull the first item before answering, so a bad request (unknown county,
    # runner not built) is a normal HTTP error rather than a broken stream.
    first = await anext(items)

    async def events() -> AsyncIterator[str]:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + settings.plan_timeout_s
        item = first
        try:
            while True:
                if isinstance(item, AgentEvent):
                    yield _sse("agent", item.model_dump_json())
                else:
                    _check_pii(item)
                    yield _sse("plan", item.model_dump_json())
                    return
                item = await asyncio.wait_for(anext(items), timeout=max(0.0, deadline - loop.time()))
        except TimeoutError:
            yield _sse("error", json.dumps({"code": "plan_timeout", "request_id": rid,
                                            "message": f"Agents did not finish within {settings.plan_timeout_s:.0f} s."}))
        except GatewayError as exc:
            yield _sse("error", json.dumps({"code": exc.code, "message": exc.message, "request_id": rid}))

    # X-Accel-Buffering stops the UI's nginx proxy from holding events back.
    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
