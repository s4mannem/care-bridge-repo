"""Siting Planner Agent implementation, race-blind callbacks, and agent builder."""

from __future__ import annotations

import copy
from typing import Any, Callable, Dict, List, Optional
from carebridge.agents.planner_agent.prompts import PLANNER_AGENT_INSTRUCTION
from carebridge.config import get_settings
from carebridge.contracts.plan_models import DraftPlan
from carebridge.contracts.state_keys import (
    STATE_AUDIT_REPORT,
    STATE_DRAFT_PLAN,
    STATE_REVISION_HISTORY,
)
from carebridge.security.model_armor import default_vertex_safety_settings
from carebridge.security.owasp_guardrails import before_model_guardrail_callback
from carebridge.security.race_blind_guard import (
    PolicyViolationError,
    assert_race_blind_planner_input,
)
from carebridge.telemetry.otel import trace_span

try:
    from google.adk.agents import LlmAgent
    from google.adk.tools import FunctionTool
    from google.genai import types as genai_types
except ImportError:
    from carebridge._compat import genai_types  # type: ignore

    class LlmAgent:  # type: ignore
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs
            for k, v in kwargs.items():
                setattr(self, k, v)

    class FunctionTool:  # type: ignore
        def __init__(self, func: Any, **kwargs: Any) -> None:
            self.func = func
            self.kwargs = kwargs


def planner_race_blind_before_model_callback(
    callback_context: Any,
    llm_request: Any,
) -> Optional[Any]:
    """ADK `before_model_callback`: enforces strict race-blind boundary for Siting Planner.

    Ensures that session.state['audit_report'] is never passed to Planner context
    and that no demographic tokens cross into prompt.
    """
    # 1. First run global OWASP injection & PII screening
    before_model_guardrail_callback(callback_context, llm_request)

    # 2. Check session state if accessible through callback_context
    session = getattr(callback_context, "session", None)
    if session is not None:
        state = getattr(session, "state", {})
        if isinstance(state, dict) and STATE_AUDIT_REPORT in state:
            raise PolicyViolationError(
                f"Boundary violation: '{STATE_AUDIT_REPORT}' detected in Planner session state context."
            )

    # 3. Check request string for race/ethnicity/SVI Theme 3 tokens
    req_text = str(llm_request)
    assert_race_blind_planner_input(req_text)
    return None


def planner_after_model_callback(
    callback_context: Any,
    llm_response: Any,
) -> Optional[Any]:
    """ADK `after_model_callback`: verifies DraftPlan and tracks revision history in state."""
    # Handle response or output_key retrieval
    session = getattr(callback_context, "session", None)
    state = getattr(session, "state", None) if session else None

    draft_plan_data: Optional[DraftPlan] = None
    if state and isinstance(state, dict) and STATE_DRAFT_PLAN in state:
        raw_draft = state[STATE_DRAFT_PLAN]
        if isinstance(raw_draft, DraftPlan):
            draft_plan_data = raw_draft
        elif isinstance(raw_draft, dict):
            draft_plan_data = DraftPlan.model_validate(raw_draft)

    # If draft_plan_data is available, enforce safety and append to revision_history
    if draft_plan_data:
        # Enforce host_verified=False and provisional warning
        for stop in draft_plan_data.stops:
            if stop.host_verified is not False:
                stop.host_verified = False

        if state is not None and isinstance(state, dict):
            history: List[Any] = state.setdefault(STATE_REVISION_HISTORY, [])
            history.append(draft_plan_data.model_copy(deep=True))

        with trace_span("agent.siting_planner.plan") as span:
            span.set_attribute("revision_number", draft_plan_data.revision_number)
            span.set_attribute("status", draft_plan_data.status)
            span.set_attribute(
                "stop_geoids", [s.primary_tract_geoid for s in draft_plan_data.stops]
            )

    return None


def build_siting_planner_agent(
    optimizer_tool_func: Optional[Callable[..., Any]] = None,
) -> LlmAgent:
    """Builds the race-blind Siting Planner LlmAgent with coverage optimizer tool."""
    settings = get_settings()
    if optimizer_tool_func is None:
        from carebridge.tools.optimizer.tool import optimize_four_clinic_stops
        optimizer_tool_func = optimize_four_clinic_stops

    config = getattr(genai_types, "GenerateContentConfig", None)
    gen_config = (
        config(
            temperature=0.1,
            safety_settings=default_vertex_safety_settings(),
        )
        if config else None
    )

    return LlmAgent(
        name="siting_planner_agent",
        model=settings.gemini_model_reasoning,
        description=(
            "Race-blind Siting Planner Agent: Invokes the deterministic Four-Stop Coverage Optimizer "
            "and produces source-backed, grain-aware rationales for 4 Saturday mobile clinic stops."
        ),
        instruction=PLANNER_AGENT_INSTRUCTION,
        tools=[FunctionTool(func=optimizer_tool_func)],
        output_key=STATE_DRAFT_PLAN,
        output_schema=DraftPlan,
        generate_content_config=gen_config,
        before_model_callback=planner_race_blind_before_model_callback,
        after_model_callback=planner_after_model_callback,
    )
