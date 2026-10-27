"""ADK LlmAgent definition and race-blind callbacks for the CareBridge AI Siting Planner Agent."""

from __future__ import annotations

import copy
import inspect
import json
import re
import sys
import types as py_types
import uuid
from typing import Any, Callable, Dict, Iterator, List, Optional

try:
    from google.genai import types  # type: ignore
except ImportError:  # pragma: no cover
    from carebridge._compat import genai_types as types  # type: ignore

from carebridge.agents.planner_agent.prompts import PLANNER_AGENT_INSTRUCTION
from carebridge.config import get_settings
from carebridge.contracts.plan_models import DraftPlan
from carebridge.contracts.state_keys import (
    PLANNER_VISIBLE_STATE_KEYS,
    SANITIZED_LOOPBACK_STATE_KEYS,
    STATE_DRAFT_PLAN,
    STATE_ITERATION_COUNT,
    STATE_NON_DEMOGRAPHIC_FEEDBACK,
    STATE_PLAN_REQUEST,
    STATE_REVISION_HISTORY,
)
from carebridge.security.model_armor import default_vertex_safety_settings
from carebridge.security.owasp_guardrails import (
    after_model_guardrail_callback,
    after_tool_race_and_pii_callback,
    before_model_guardrail_callback,
    before_tool_guardrail_callback,
)
from carebridge.security.race_blind_guard import (
    PolicyViolationError,
    assert_no_pii_in_payload,
    assert_race_blind_planner_input,
)
from carebridge.telemetry.otel import record_structured_log, trace_span

try:
    from google.adk.agents import LlmAgent  # type: ignore
    from google.adk.tools import FunctionTool  # type: ignore
except ImportError:  # pragma: no cover
    _TEMPLATE_VAR_RE = re.compile(r"\{([a-zA-Z0-9_]+)(\?)?\}")

    class CallbackContext:
        """ADK-compatible callback context."""

        def __init__(self, agent_name: str, state: Dict[str, Any]) -> None:
            self.agent_name = agent_name
            self.state = state

    class ToolContext(CallbackContext):
        """ADK-compatible tool context exposing `agent_name` and `state`."""

    class FunctionTool:  # type: ignore[no-redef]
        """ADK-compatible FunctionTool wrapper."""

        def __init__(self, func: Callable[..., Any]) -> None:
            self.func = func
            self.name = getattr(func, "__name__", "function_tool")
            self.description = inspect.getdoc(func) or ""

        def __call__(self, *args: Any, **kwargs: Any) -> Any:
            return self.func(*args, **kwargs)

    class LlmAgent:  # type: ignore[no-redef]
        """ADK-compatible LlmAgent supporting tool execution, callbacks, output_schema, and output_key."""

        def __init__(
            self,
            *,
            name: str,
            model: str,
            description: str = "",
            instruction: str = "",
            tools: Optional[List[Any]] = None,
            output_key: Optional[str] = None,
            output_schema: Optional[Any] = None,
            generate_content_config: Optional[Any] = None,
            before_model_callback: Optional[Callable[..., Any]] = None,
            after_model_callback: Optional[Callable[..., Any]] = None,
            before_tool_callback: Optional[Callable[..., Any]] = None,
            after_tool_callback: Optional[Callable[..., Any]] = None,
        ) -> None:
            self.name = name
            self.model = model
            self.description = description
            self.instruction = instruction
            self.tools = list(tools or [])
            self.output_key = output_key
            self.output_schema = output_schema
            self.generate_content_config = generate_content_config
            self.before_model_callback = before_model_callback
            self.after_model_callback = after_model_callback
            self.before_tool_callback = before_tool_callback
            self.after_tool_callback = after_tool_callback

        def render_instruction(self, state: Dict[str, Any]) -> str:
            """Renders instruction placeholders, supporting ADK's optional `{var?}` syntax."""

            def _replace(match: re.Match[str]) -> str:
                var_name = match.group(1)
                is_optional = match.group(2) == "?"
                if var_name in state:
                    return str(state[var_name])
                if is_optional:
                    return ""
                raise KeyError(f"Context variable not found: '{var_name}'")

            return _TEMPLATE_VAR_RE.sub(_replace, self.instruction)

        def execute_with_state(
            self,
            state: Dict[str, Any],
            user_message: str = "",
            tool_args_override: Optional[Dict[str, Any]] = None,
        ) -> Dict[str, Any]:
            """Runs the ADK LlmAgent lifecycle deterministically against `state`."""
            cb_ctx = CallbackContext(agent_name=self.name, state=state)
            rendered_prompt = f"{self.render_instruction(state)}\nUser: {user_message}".strip()

            if self.before_model_callback is not None:
                self.before_model_callback(cb_ctx, rendered_prompt)

            tool_result: Any = None
            for tool in self.tools:
                fn = getattr(tool, "func", tool)
                tool_ctx = ToolContext(agent_name=self.name, state=state)
                call_args: Dict[str, Any] = dict(tool_args_override or {})
                plan_req = state.get(STATE_PLAN_REQUEST)
                sig = inspect.signature(fn)
                if "county_fips" not in call_args and "county_fips" in sig.parameters:
                    if isinstance(plan_req, dict) and plan_req.get("county_fips"):
                        call_args["county_fips"] = str(plan_req["county_fips"])
                    else:
                        call_args["county_fips"] = "13121"

                if "strategy" not in call_args and "strategy" in sig.parameters:
                    if isinstance(plan_req, dict) and plan_req.get("strategy"):
                        call_args["strategy"] = str(plan_req["strategy"])

                if "revision_number" not in call_args and "revision_number" in sig.parameters:
                    has_feedback = bool(state.get(STATE_NON_DEMOGRAPHIC_FEEDBACK))
                    has_prior_draft = len(state.get(STATE_REVISION_HISTORY, []) or []) >= 1
                    iter_count = int(state.get(STATE_ITERATION_COUNT, 0) or 0)
                    if has_feedback or has_prior_draft or iter_count >= 1:
                        call_args["revision_number"] = 1
                    else:
                        call_args["revision_number"] = 0

                if self.before_tool_callback is not None:
                    self.before_tool_callback(tool, call_args, tool_ctx)

                if "tool_context" in sig.parameters:
                    tool_result = fn(**call_args, tool_context=tool_ctx)
                else:
                    tool_result = fn(**call_args)

                if self.after_tool_callback is not None:
                    self.after_tool_callback(tool, call_args, tool_ctx, tool_result)

            if self.output_schema is not None and tool_result is not None:
                validated = self.output_schema.model_validate(tool_result)
                output_payload = validated.model_dump()
                llm_response_text = validated.model_dump_json()
            else:
                output_payload = tool_result
                llm_response_text = str(tool_result)

            if self.output_key and output_payload is not None:
                state[self.output_key] = output_payload

            if self.after_model_callback is not None:
                self.after_model_callback(cb_ctx, llm_response_text)

            return output_payload

    class Session:
        """ADK-compatible in-memory Session object."""

        def __init__(
            self,
            app_name: str,
            user_id: str,
            session_id: Optional[str] = None,
            state: Optional[Dict[str, Any]] = None,
        ) -> None:
            self.app_name = app_name
            self.user_id = user_id
            self.id = session_id or f"sess-{uuid.uuid4().hex[:10]}"
            self.state: Dict[str, Any] = dict(state or {})

    class InMemorySessionService:
        """ADK-compatible InMemorySessionService."""

        def __init__(self) -> None:
            self._sessions: Dict[str, Session] = {}

        def create_session_sync(
            self,
            *,
            app_name: str,
            user_id: str,
            session_id: Optional[str] = None,
            state: Optional[Dict[str, Any]] = None,
        ) -> Session:
            session = Session(
                app_name=app_name, user_id=user_id, session_id=session_id, state=state
            )
            self._sessions[session.id] = session
            return session

        async def create_session(
            self,
            *,
            app_name: str,
            user_id: str,
            session_id: Optional[str] = None,
            state: Optional[Dict[str, Any]] = None,
        ) -> Session:
            return self.create_session_sync(
                app_name=app_name, user_id=user_id, session_id=session_id, state=state
            )

        def get_session_sync(
            self, *, app_name: str, user_id: str, session_id: str
        ) -> Optional[Session]:
            return self._sessions.get(session_id)

        async def get_session(
            self, *, app_name: str, user_id: str, session_id: str
        ) -> Optional[Session]:
            return self._sessions.get(session_id)

    class _RunnerEvent:
        def __init__(self, author: str, payload: Any) -> None:
            self.author = author
            self.payload = payload

        def is_final_response(self) -> bool:
            return True

    class InMemoryRunner:
        """ADK-compatible InMemoryRunner for standalone and integration agent execution."""

        def __init__(self, agent: Any, app_name: str = "carebridge") -> None:
            self.agent = agent
            self.app_name = app_name
            self.session_service = InMemorySessionService()

        def run(
            self,
            *,
            user_id: str = "test-user",
            session_id: str,
            new_message: Any = "",
        ) -> Iterator[_RunnerEvent]:
            session = self.session_service.get_session_sync(
                app_name=self.app_name, user_id=user_id, session_id=session_id
            )
            if session is None:
                session = self.session_service.create_session_sync(
                    app_name=self.app_name, user_id=user_id, session_id=session_id
                )
            msg_str = str(new_message) if new_message is not None else ""
            result = self.agent.execute_with_state(session.state, user_message=msg_str)
            yield _RunnerEvent(author=self.agent.name, payload=result)

        async def run_async(
            self,
            *,
            user_id: str = "test-user",
            session_id: str,
            new_message: Any = "",
        ):
            for event in self.run(user_id=user_id, session_id=session_id, new_message=new_message):
                yield event

    if "google.adk" not in sys.modules:
        google_pkg = sys.modules.get("google") or py_types.ModuleType("google")
        sys.modules["google"] = google_pkg

        adk_pkg = py_types.ModuleType("google.adk")
        adk_agents = py_types.ModuleType("google.adk.agents")
        adk_tools = py_types.ModuleType("google.adk.tools")
        adk_runners = py_types.ModuleType("google.adk.runners")
        adk_sessions = py_types.ModuleType("google.adk.sessions")

        adk_agents.LlmAgent = LlmAgent  # type: ignore[attr-defined]
        adk_tools.FunctionTool = FunctionTool  # type: ignore[attr-defined]
        adk_tools.ToolContext = ToolContext  # type: ignore[attr-defined]
        adk_runners.InMemoryRunner = InMemoryRunner  # type: ignore[attr-defined]
        adk_sessions.InMemorySessionService = InMemorySessionService  # type: ignore[attr-defined]
        adk_sessions.Session = Session  # type: ignore[attr-defined]

        adk_pkg.agents = adk_agents  # type: ignore[attr-defined]
        adk_pkg.tools = adk_tools  # type: ignore[attr-defined]
        adk_pkg.runners = adk_runners  # type: ignore[attr-defined]
        adk_pkg.sessions = adk_sessions  # type: ignore[attr-defined]
        google_pkg.adk = adk_pkg  # type: ignore[attr-defined]

        sys.modules["google.adk"] = adk_pkg
        sys.modules["google.adk.agents"] = adk_agents
        sys.modules["google.adk.tools"] = adk_tools
        sys.modules["google.adk.runners"] = adk_runners
        sys.modules["google.adk.sessions"] = adk_sessions


def planner_race_blind_before_model_callback(
    callback_context: Any,
    llm_request: Any,
) -> Optional[Any]:
    """Pre-model guardrail for `siting_planner_agent` enforcing strict race-blind isolation.

    Scans the outgoing `llm_request` and visible state inputs and raises `PolicyViolationError`
    if any demographic token (`rpl_theme3`, `pct_black`, `pct_hispanic`, `demographic_impact`,
    `external_demographic_audit`, etc.) or `audit_report` leakage appears.
    """
    before_model_guardrail_callback(callback_context, llm_request)
    request_str = str(llm_request)
    assert_race_blind_planner_input(request_str)
    assert_no_pii_in_payload(request_str)

    if re.search(r"\baudit_report\b", request_str, re.I):
        raise PolicyViolationError(
            "Race-blind boundary violation: 'audit_report' cannot be injected into siting_planner_agent prompt."
        )

    state = getattr(callback_context, "state", None)
    if isinstance(state, dict):
        for key in (*PLANNER_VISIBLE_STATE_KEYS, *SANITIZED_LOOPBACK_STATE_KEYS):
            if key in state and state[key] is not None:
                assert_race_blind_planner_input(state[key])
                assert_no_pii_in_payload(state[key])

    return None


# Alias matching Plan 06 Step 3.2 heading
planner_before_model_callback = planner_race_blind_before_model_callback


def _extract_draft_plan_dict(
    llm_response: Any,
    state: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Extracts a validated `DraftPlan` dict from `llm_response` or `state[STATE_DRAFT_PLAN]`."""
    candidate: Any = None
    if isinstance(llm_response, DraftPlan):
        return copy.deepcopy(llm_response.model_dump())
    if isinstance(llm_response, dict) and "county_fips" in llm_response and "status" in llm_response:
        candidate = llm_response
    elif isinstance(llm_response, str) and llm_response.strip().startswith("{"):
        try:
            parsed = json.loads(llm_response)
            if isinstance(parsed, dict) and "county_fips" in parsed and "status" in parsed:
                candidate = parsed
        except Exception:
            candidate = None

    if candidate is None and isinstance(state, dict) and state.get(STATE_DRAFT_PLAN) is not None:
        raw_state_plan = state[STATE_DRAFT_PLAN]
        if isinstance(raw_state_plan, DraftPlan):
            return copy.deepcopy(raw_state_plan.model_dump())
        if isinstance(raw_state_plan, dict):
            candidate = raw_state_plan

    if candidate is not None:
        validated = DraftPlan.model_validate(candidate)
        return copy.deepcopy(validated.model_dump())
    return None


def planner_after_model_callback(
    callback_context: Any,
    llm_response: Any,
) -> Optional[Any]:
    """Post-model callback for `siting_planner_agent`: screens output, records telemetry, and appends to `revision_history`."""
    after_model_guardrail_callback(callback_context, llm_response)
    response_str = str(llm_response)
    assert_race_blind_planner_input(response_str)
    assert_no_pii_in_payload(response_str)

    state = getattr(callback_context, "state", None)
    draft_dict = _extract_draft_plan_dict(llm_response, state if isinstance(state, dict) else None)

    if draft_dict is not None:
        assert_race_blind_planner_input(draft_dict)
        assert_no_pii_in_payload(draft_dict)
        revision_number = int(draft_dict.get("revision_number", 0))
        status = str(draft_dict.get("status", "ok"))
        stop_geoids = [
            str(s.get("primary_tract_geoid", ""))
            for s in (draft_dict.get("stops") or [])
            if isinstance(s, dict)
        ]

        if isinstance(state, dict):
            state[STATE_DRAFT_PLAN] = copy.deepcopy(draft_dict)
            history = state.get(STATE_REVISION_HISTORY)
            if not isinstance(history, list):
                history = []
                state[STATE_REVISION_HISTORY] = history
            history.append(copy.deepcopy(draft_dict))

        with trace_span(
            "agent.siting_planner.plan",
            revision_number=revision_number,
            status=status,
            stop_geoids=stop_geoids,
            output_token_estimate=max(1, len(response_str) // 4),
        ) as span:
            span.set_attribute("revision_number", revision_number)
            span.set_attribute("status", status)
            span.set_attribute("stop_geoids", stop_geoids)

        record_structured_log(
            component="siting_planner_agent",
            event_type="agent.siting_planner.plan",
            revision_number=revision_number,
            status=status,
            stop_geoids=stop_geoids,
        )

    return None


def _default_optimizer_tool_func() -> Callable[..., Dict[str, Any]]:
    """Loads `optimize_four_clinic_stops` from Plan 05 with a clean fallback if needed."""
    try:
        from carebridge.tools.optimizer.tool import optimize_four_clinic_stops

        return optimize_four_clinic_stops
    except ImportError:  # pragma: no cover
        def _fallback_optimize_four_clinic_stops(
            county_fips: str = "13121",
            strategy: str = "balanced_uninsured_safety_net_gap",
            revision_number: int = 0,
            tool_context: Optional[Any] = None,
            **kwargs: Any,
        ) -> Dict[str, Any]:
            state = getattr(tool_context, "state", {}) if tool_context is not None else {}
            plan = DraftPlan(
                county_fips=county_fips,
                strategy_used=strategy,
                status="insufficient_candidates",
                revision_number=min(1, max(0, revision_number)),
                stops=[],
                runner_up_tracts=[],
                sensitivity=None,
                planner_notes=["Fallback optimizer invoked because carebridge.tools.optimizer is unavailable."],
            ).model_dump()
            if isinstance(state, dict):
                state[STATE_DRAFT_PLAN] = plan
            return plan

        return _fallback_optimize_four_clinic_stops


def build_siting_planner_agent(
    optimizer_tool_func: Optional[Callable[..., Any]] = None,
) -> LlmAgent:
    """Constructs the CareBridge AI Siting Planner Agent (`siting_planner_agent`)."""
    settings = get_settings()
    if optimizer_tool_func is None:
        optimizer_tool_func = _default_optimizer_tool_func()

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
        generate_content_config=types.GenerateContentConfig(
            temperature=0.1,
            safety_settings=default_vertex_safety_settings(),
        ),
        before_model_callback=planner_race_blind_before_model_callback,
        after_model_callback=planner_after_model_callback,
        before_tool_callback=before_tool_guardrail_callback,
        after_tool_callback=after_tool_race_and_pii_callback,
    )


root_agent = build_siting_planner_agent()

