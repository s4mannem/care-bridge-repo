"""The two steps the API's runner does around the graph, as agents, for `adk web`.

- `PlanIntake` turns the chat message into `plan_request` (JSON fields of
  PlanRequest, or the Fulton defaults for any other text) and seeds the state
  the graph expects, as `api/carebridge/agents/runner.py` does.
- `PlanFinalizer` assembles the team's PlanResponse from the final state and
  writes it under `plan_response`, with a one-paragraph answer in the chat.

One plan per session: start a new session for the next request.
"""
from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator

from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.genai import types

from carebridge.agents.coordinator.runner import assemble_plan_response_from_state
from carebridge.contracts.api_models import PlanRequest


def _text(ctx: InvocationContext) -> str:
    parts = ctx.user_content.parts if ctx.user_content and ctx.user_content.parts else []
    return "".join(p.text or "" for p in parts).strip()


def _say(ctx: InvocationContext, author: str, text: str, delta: dict) -> Event:
    return Event(author=author, invocation_id=ctx.invocation_id, branch=ctx.branch,
                 content=types.Content(role="model", parts=[types.Part(text=text)]),
                 actions=EventActions(state_delta=delta))


class PlanIntake(BaseAgent):
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        if ctx.session.state.get("plan_request"):
            yield _say(ctx, self.name, "This session already has a plan request; start a new session for another.", {})
            return
        text = _text(ctx)
        try:
            fields = json.loads(text) if text.startswith("{") else {}
        except json.JSONDecodeError:
            fields = {}
        req = PlanRequest(**fields)
        yield _say(ctx, self.name,
                   f"Planning four Saturday stops for {req.county_name} County ({req.county_fips}), "
                   f"strategy {req.strategy}" + (", with the draft-0 defect simulated." if req.simulate_first_draft_defect else "."),
                   {"plan_request": req.model_dump(mode="json"), "request_id": f"adk-{uuid.uuid4().hex[:12]}",
                    "revision_history": []})


class PlanFinalizer(BaseAgent):
    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        state = dict(ctx.session.state)
        req = PlanRequest(**(state.get("plan_request") or {}))
        resp = assemble_plan_response_from_state(req, state, state.get("request_id") or "adk")
        data = resp.model_dump(mode="json")
        stops = (data.get("final_plan") or {}).get("stops") or []
        where = "; ".join(f"#{s.get('stop_rank')} {s.get('assigned_saturday')} tract {s.get('primary_tract_geoid')}"
                          for s in stops)
        yield _say(ctx, self.name,
                   f"Plan {data['status']} (needs human review: {str(data['needs_human_review']).lower()}). "
                   f"{len(data.get('revision_history') or [])} draft(s). Stops: {where or 'none'}. "
                   "The full PlanResponse is in session state under plan_response.",
                   {"plan_response": data})
