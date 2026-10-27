"""ADK LlmAgent definition for the CareBridge AI Health & Access Evidence Agent (Evidence Agent A)."""

from __future__ import annotations

import inspect
import re
import sys
import types as py_types
import uuid
from typing import Any, Callable, Dict, Iterator, List, Optional

from carebridge._compat import genai_types as types
from carebridge.agents.health_agent.prompts import HEALTH_AGENT_INSTRUCTION
from carebridge.agents.health_agent.tools import fetch_county_health_evidence
from carebridge.config import get_settings
from carebridge.contracts.evidence_models import HealthEvidence
from carebridge.contracts.state_keys import STATE_HEALTH_EVIDENCE, STATE_PLAN_REQUEST
from carebridge.security.model_armor import default_vertex_safety_settings
from carebridge.security.owasp_guardrails import (
    after_model_guardrail_callback,
    after_tool_race_and_pii_callback,
    before_model_guardrail_callback,
    before_tool_guardrail_callback,
)

try:
    from google.adk.agents import LlmAgent  # type: ignore
    from google.adk.tools import FunctionTool  # type: ignore

    HAS_NATIVE_ADK = True
except ImportError:  # pragma: no cover
    HAS_NATIVE_ADK = False

    _TEMPLATE_VAR_RE = re.compile(r"\{([a-zA-Z0-9_]+)(\?)?\}")

    class CallbackContext:
        """ADK-compatible callback context."""

        def __init__(self, agent_name: str, state: Dict[str, Any]) -> None:
            self.agent_name = agent_name
            self.state = state

    class ToolContext(CallbackContext):
        """ADK-compatible tool context exposing `agent_name` and `state`."""

    class FunctionTool:
        """ADK-compatible FunctionTool wrapper."""

        def __init__(self, func: Callable[..., Any]) -> None:
            self.func = func
            self.name = getattr(func, "__name__", "function_tool")
            self.description = inspect.getdoc(func) or ""

        def __call__(self, *args: Any, **kwargs: Any) -> Any:
            return self.func(*args, **kwargs)

    class LlmAgent:
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
                if "county_fips" not in call_args:
                    plan_req = state.get(STATE_PLAN_REQUEST)
                    if isinstance(plan_req, dict) and plan_req.get("county_fips"):
                        call_args["county_fips"] = str(plan_req["county_fips"])
                    else:
                        call_args["county_fips"] = "13121"

                if self.before_tool_callback is not None:
                    self.before_tool_callback(tool, call_args, tool_ctx)

                sig = inspect.signature(fn)
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

            if self.after_model_callback is not None:
                self.after_model_callback(cb_ctx, llm_response_text)

            if self.output_key and output_payload is not None:
                state[self.output_key] = output_payload

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
            session = Session(app_name=app_name, user_id=user_id, session_id=session_id, state=state)
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

    # Register fallback google.adk modules in sys.modules if not installed
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


def build_health_access_agent() -> LlmAgent:
    """Builds the ADK `LlmAgent` for Evidence Agent A (Health & Access Agent)."""
    settings = get_settings()
    return LlmAgent(
        name="health_access_agent",
        model=settings.gemini_model_fast,
        description=(
            "Evidence Agent A: Queries BigQuery MCP for tract health burden, safety-net distances, "
            "HRSA shortage areas vs facilities, and HSA-level weekly disease surveillance."
        ),
        instruction=HEALTH_AGENT_INSTRUCTION,
        tools=[FunctionTool(func=fetch_county_health_evidence)],
        output_key=STATE_HEALTH_EVIDENCE,
        output_schema=HealthEvidence,
        generate_content_config=types.GenerateContentConfig(
            temperature=0.0,
            safety_settings=default_vertex_safety_settings(),
        ),
        before_model_callback=before_model_guardrail_callback,
        after_model_callback=after_model_guardrail_callback,
        before_tool_callback=before_tool_guardrail_callback,
        after_tool_callback=after_tool_race_and_pii_callback,
    )
