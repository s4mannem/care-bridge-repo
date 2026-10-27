"""Runs the team's coordinator workflow on real ADK (google-adk 2.11).

`workflow.py` drives agents through `execute_with_state()`, which exists only on
the package's stand-in `LlmAgent` used when ADK isn't installed. With real ADK
those agents are never called. This module builds the same graph from the same
builders on ADK's own classes:

    SequentialAgent carebridge_coordinator
     ├─ ParallelAgent evidence_collection_parallel: health_access ║ transit_community
     ├─ evidence_validator
     ├─ LoopAgent plan_audit_loop (max 2): siting_planner → equity_rigor_auditor → exit gate
     └─ community_communications

Per agent, two changes, nothing else:
- The tool reads its inputs from session state (as it already does when state
  is a dict) and its result is written back under the agent's own state key.
  Real ADK hands tools a `State` object, so the tools' `isinstance(state, dict)`
  writes were skipped.
- No `output_schema`: Gemini decides to call the tool, then answers with a short
  summary under `<agent>_summary` instead of retyping hundreds of records as JSON.

The planner's race-blind check inspects what the model is sent, not the shared
session state (which legitimately holds `audit_report` by the revision).
The exit gate's logic is the team's `AuditLoopExitGate.evaluate_state`, unchanged.
"""
from __future__ import annotations

import copy
import inspect
import re
from collections.abc import AsyncGenerator
from typing import Any, Callable

from google.adk.agents import BaseAgent, LlmAgent, LoopAgent, ParallelAgent, SequentialAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events import Event, EventActions
from google.adk.tools import FunctionTool, ToolContext
from google.genai import types

from carebridge.agents.auditor_agent.agent import build_equity_rigor_auditor_agent
from carebridge.agents.communicator_agent.agent import build_community_communications_agent
from carebridge.agents.coordinator.exit_gate import AuditLoopExitGate
from carebridge.agents.coordinator.pacing import pace_model_call
from carebridge.agents.health_agent.agent import build_health_access_agent
from carebridge.agents.mobility_agent.agent import build_transit_community_agent
from carebridge.agents.planner_agent.agent import build_siting_planner_agent
from carebridge.agents.validator_agent.agent import build_evidence_validator_agent
from carebridge.config import get_settings
from carebridge.contracts.state_keys import (
    STATE_AUDIT_REPORT,
    STATE_DRAFT_PLAN,
    STATE_EVIDENCE_REPORT,
    STATE_HEALTH_EVIDENCE,
    STATE_ITERATION_COUNT,
    STATE_MOBILITY_EVIDENCE,
    STATE_OUTREACH_MESSAGES,
    STATE_PLAN_REQUEST,
    STATE_REVISION_HISTORY,
)
from carebridge.security.owasp_guardrails import before_model_guardrail_callback
from carebridge.security.race_blind_guard import assert_race_blind_planner_input

# State values too large to paste into a prompt (hundreds of tract records each);
# the tools read them from session state directly.
LARGE_STATE_KEYS = (STATE_HEALTH_EVIDENCE, STATE_MOBILITY_EVIDENCE)

SUMMARY_NOTE = """

The tool stores its full result in session state for the next agents. After calling it,
reply with a 2-4 sentence summary for the outreach lead. Do not repeat the data as JSON."""


class _DictToolContext:
    """What the team's tools expect: `.state` as a plain dict and `.agent_name`."""

    def __init__(self, state: dict, agent_name: str):
        self.state = state
        self.agent_name = agent_name


def _jsonable(v: Any) -> Any:
    return v.model_dump(mode="json") if hasattr(v, "model_dump") else v


def _revision(state: dict) -> int:
    return int(state.get("current_revision_number", state.get(STATE_ITERATION_COUNT, 0)) or 0)


def _summary(payload: Any) -> dict:
    """A short view of a tool result for the model; the full result lives in state."""
    if not isinstance(payload, dict):
        return {"result": str(payload)[:500]}
    out = {}
    for k, v in payload.items():
        if isinstance(v, (str, int, float, bool)) or v is None:
            out[k] = v
        elif isinstance(v, list):
            out[k] = f"{len(v)} items"
        elif isinstance(v, dict):
            out[k] = f"{len(v)} fields"
    return out


def _state_tool(func: Callable, agent_name: str, state_key: str, extra: Callable[[dict], dict] | None = None):
    """Wrap a team tool so it runs on a dict view of session state and writes back what changed."""

    def run(tool_context: ToolContext) -> dict:
        before = copy.deepcopy(tool_context.state.to_dict())
        view = copy.deepcopy(before)
        req = view.get(STATE_PLAN_REQUEST) or {}
        kwargs = {"tool_context": _DictToolContext(view, agent_name)}
        if "county_fips" in func.__code__.co_varnames:
            kwargs["county_fips"] = req.get("county_fips", "13121")
        if "include_optional_datasets" in func.__code__.co_varnames:
            kwargs["include_optional_datasets"] = bool(req.get("include_optional_datasets", True))
        if extra:
            kwargs.update(extra(view))
        payload = _jsonable(func(**_accepted(func, kwargs)))
        for k, v in view.items():
            if k.startswith("_"):
                continue
            if before.get(k) != v:
                tool_context.state[k] = _jsonable(v)
        if payload is not None:
            tool_context.state[state_key] = payload
        return _summary(payload)

    # Name and docstring only: ADK must see this wrapper's signature (tool_context), not the original's.
    run.__name__, run.__doc__ = func.__name__, func.__doc__
    return run


def _accepted(func: Callable, kwargs: dict) -> dict:
    """Only the arguments `func` declares (all of them if it takes **kwargs)."""
    params = inspect.signature(func).parameters
    if any(p.kind is p.VAR_KEYWORD for p in params.values()):
        return kwargs
    return {k: v for k, v in kwargs.items() if k in params}


def _planner_extra(view: dict) -> dict:
    req = view.get(STATE_PLAN_REQUEST) or {}
    return {
        STATE_HEALTH_EVIDENCE: view.get(STATE_HEALTH_EVIDENCE),
        STATE_MOBILITY_EVIDENCE: view.get(STATE_MOBILITY_EVIDENCE),
        STATE_PLAN_REQUEST: req,
        STATE_EVIDENCE_REPORT: view.get(STATE_EVIDENCE_REPORT),
        "non_demographic_feedback": view.get("non_demographic_feedback") or None,
        "revision_number": _revision(view),
        "strategy": req.get("strategy", "balanced_uninsured_safety_net_gap"),
        "simulate_first_draft_defect": bool(req.get("simulate_first_draft_defect")),
        "saturdays": req.get("saturdays"),
    }


def _planner_tool(func: Callable) -> Callable:
    base = _state_tool(func, "siting_planner_agent", STATE_DRAFT_PLAN, _planner_extra)

    def run(tool_context: ToolContext) -> dict:
        result = base(tool_context)
        draft = tool_context.state.get(STATE_DRAFT_PLAN)
        history = list(tool_context.state.get(STATE_REVISION_HISTORY) or [])
        if draft is not None and (not history or history[-1] != draft):
            tool_context.state[STATE_REVISION_HISTORY] = history + [draft]
        return result

    run.__name__, run.__doc__ = base.__name__, base.__doc__
    return run


def _ensure_planner_ran(callback_context: Any) -> None:
    """If the model answered without calling the tool on this revision, run the optimizer anyway."""
    s = callback_context.state
    draft = s.get(STATE_DRAFT_PLAN)
    if draft is None or int(draft.get("revision_number", -1)) != _revision(s.to_dict()):
        from carebridge.tools.optimizer.tool import optimize_four_clinic_stops

        view = s.to_dict()
        kwargs = {"tool_context": _DictToolContext(view, "siting_planner_agent"), **_planner_extra(view)}
        d = _jsonable(optimize_four_clinic_stops(**_accepted(optimize_four_clinic_stops, kwargs)))
        s[STATE_DRAFT_PLAN] = d
        s[STATE_REVISION_HISTORY] = list(s.get(STATE_REVISION_HISTORY) or []) + [d]


def _planner_race_blind(callback_context: Any, llm_request: Any) -> None:
    before_model_guardrail_callback(callback_context, llm_request)
    assert_race_blind_planner_input(str(llm_request.contents))


def _adapt(agent: LlmAgent, state_key: str, tool: Callable, **overrides: Any) -> LlmAgent:
    settings = get_settings()
    fields = dict(
        name=agent.name,
        model=settings.gemini_model_reasoning,
        description=agent.description,
        instruction=_slim(agent.instruction or "") + SUMMARY_NOTE,
        tools=[FunctionTool(func=tool)],
        output_key=f"{agent.name}_summary",
        include_contents="none",
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
        generate_content_config=_with_retry(agent.generate_content_config),
        before_model_callback=agent.before_model_callback,
    )
    fields.update(overrides)
    own = fields["before_model_callback"]
    fields["before_model_callback"] = [pace_model_call, *(own if isinstance(own, list) else [own] if own else [])]
    return LlmAgent(**fields)


def _with_retry(config: Any) -> types.GenerateContentConfig:
    """Back off and retry on 429/503: the lab project's Gemini per-minute quota is tight."""
    cfg = config.model_copy() if config is not None else types.GenerateContentConfig()
    cfg.http_options = types.HttpOptions(retry_options=types.HttpRetryOptions(
        attempts=6, initial_delay=4.0, max_delay=40.0, exp_base=2.0, http_status_codes=[429, 503]))
    return cfg


def _slim(instruction: str) -> str:
    for key in LARGE_STATE_KEYS:
        instruction = re.sub(r"\{" + key + r"\??\}", f"[{key}: in session state; your tool reads it]", instruction)
    return instruction


def _tool_func(agent: Any) -> Callable:
    t = agent.tools[0]
    return getattr(t, "func", t)


class ExitGate(BaseAgent):
    """ADK wrapper around the team's `AuditLoopExitGate.evaluate_state`."""

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Event, None]:
        before = copy.deepcopy(ctx.session.state)
        view = copy.deepcopy(before)
        ev = AuditLoopExitGate(name=self.name).evaluate_state(view)
        delta = {k: _jsonable(v) for k, v in view.items() if not k.startswith("_") and before.get(k) != v}
        yield Event(author=self.name, invocation_id=ctx.invocation_id, branch=ctx.branch,
                    actions=EventActions(state_delta=delta, escalate=bool(ev.actions.escalate) or None))


def build_adk_coordinator_workflow() -> SequentialAgent:
    health = build_health_access_agent()
    mobility = build_transit_community_agent()
    validator = build_evidence_validator_agent()
    planner = build_siting_planner_agent()
    auditor = build_equity_rigor_auditor_agent()
    communicator = build_community_communications_agent()

    return SequentialAgent(
        name="carebridge_coordinator",
        description=getattr(health, "description", ""),
        sub_agents=[
            ParallelAgent(name="evidence_collection_parallel", sub_agents=[
                _adapt(health, STATE_HEALTH_EVIDENCE,
                       _state_tool(_tool_func(health), health.name, STATE_HEALTH_EVIDENCE)),
                _adapt(mobility, STATE_MOBILITY_EVIDENCE,
                       _state_tool(_tool_func(mobility), mobility.name, STATE_MOBILITY_EVIDENCE)),
            ]),
            _adapt(validator, STATE_EVIDENCE_REPORT,
                   _state_tool(_tool_func(validator), validator.name, STATE_EVIDENCE_REPORT)),
            LoopAgent(name="plan_audit_loop", max_iterations=2, sub_agents=[
                _adapt(planner, STATE_DRAFT_PLAN, _planner_tool(_tool_func(planner)),
                       before_model_callback=_planner_race_blind,
                       after_agent_callback=_ensure_planner_ran),
                _adapt(auditor, STATE_AUDIT_REPORT,
                       _state_tool(_tool_func(auditor), auditor.name, STATE_AUDIT_REPORT)),
                ExitGate(name="audit_loop_exit_gate"),
            ]),
            _adapt(communicator, STATE_OUTREACH_MESSAGES,
                   _state_tool(_tool_func(communicator), communicator.name, STATE_OUTREACH_MESSAGES)),
        ],
    )
