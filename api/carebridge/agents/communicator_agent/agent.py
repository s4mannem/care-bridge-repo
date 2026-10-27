"""ADK LlmAgent, grounded outreach drafter tool, and post-model guardrail for Plan 08."""

from __future__ import annotations

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

from carebridge.agents.communicator_agent.prompts import COMMUNICATOR_AGENT_INSTRUCTION
from carebridge.config import get_settings
from carebridge.contracts.outreach_models import (
    OutreachMessages,
    StopOutreachDraft,
    UnpickedNeighborhoodExplanation,
)
from carebridge.contracts.plan_models import DraftPlan
from carebridge.contracts.state_keys import (
    STATE_AUDIT_REPORT,
    STATE_DRAFT_PLAN,
    STATE_FINAL_PLAN,
    STATE_OUTREACH_MESSAGES,
    STATE_PLAN_REQUEST,
)
from carebridge.mocks.fulton_fixtures import build_mock_draft_plan
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

        def __init__(self, agent: LlmAgent, app_name: str = "carebridge") -> None:
            self.agent = agent
            self.app_name = app_name
            self.session_service = InMemorySessionService()

        def run(
            self,
            *,
            user_id: str,
            session_id: str,
            new_message: Any = None,
        ) -> Iterator[_RunnerEvent]:
            session = self.session_service.get_session_sync(
                app_name=self.app_name, user_id=user_id, session_id=session_id
            )
            if session is None:
                session = self.session_service.create_session_sync(
                    app_name=self.app_name, user_id=user_id, session_id=session_id
                )

            msg_str = ""
            if isinstance(new_message, str):
                msg_str = new_message
            elif hasattr(new_message, "parts") and getattr(new_message, "parts"):
                parts = getattr(new_message, "parts")
                msg_str = " ".join(str(getattr(p, "text", p)) for p in parts)
            elif new_message is not None:
                msg_str = str(new_message)

            result = self.agent.execute_with_state(session.state, user_message=msg_str)
            yield _RunnerEvent(author=self.agent.name, payload=result)

        async def run_async(
            self,
            *,
            user_id: str,
            session_id: str,
            new_message: Any = None,
        ):
            for ev in self.run(user_id=user_id, session_id=session_id, new_message=new_message):
                yield ev

    if "google.adk" not in sys.modules:
        _google_mod = sys.modules.setdefault("google", py_types.ModuleType("google"))
        _adk_mod = py_types.ModuleType("google.adk")
        _agents_mod = py_types.ModuleType("google.adk.agents")
        _tools_mod = py_types.ModuleType("google.adk.tools")
        _runners_mod = py_types.ModuleType("google.adk.runners")
        _sessions_mod = py_types.ModuleType("google.adk.sessions")

        setattr(_agents_mod, "LlmAgent", LlmAgent)
        setattr(_tools_mod, "FunctionTool", FunctionTool)
        setattr(_runners_mod, "InMemoryRunner", InMemoryRunner)
        setattr(_sessions_mod, "InMemorySessionService", InMemorySessionService)
        setattr(_sessions_mod, "Session", Session)

        setattr(_adk_mod, "agents", _agents_mod)
        setattr(_adk_mod, "tools", _tools_mod)
        setattr(_adk_mod, "runners", _runners_mod)
        setattr(_adk_mod, "sessions", _sessions_mod)
        setattr(_google_mod, "adk", _adk_mod)

        sys.modules["google.adk"] = _adk_mod
        sys.modules["google.adk.agents"] = _agents_mod
        sys.modules["google.adk.tools"] = _tools_mod
        sys.modules["google.adk.runners"] = _runners_mod
        sys.modules["google.adk.sessions"] = _sessions_mod


FORBIDDEN_BOOKING_PATTERNS = (
    "officially booked",
    "confirmed and booked",
    "confirmed parking",
    "guaranteed appointments",
    "appointment confirmed",
    "venue is officially confirmed",
    "site is officially confirmed",
    "reservado oficialmente",
    "confirmado y reservado",
    "citas garantizadas",
    "estacionamiento confirmado",
)

PROVISIONAL_QUALIFIER_PATTERNS_EN = (
    "proposed location",
    "proposed site",
    "pending host",
    "pending site confirmation",
    "provisional",
)

PROVISIONAL_QUALIFIER_PATTERNS_ES = (
    "ubicación propuesta",
    "ubicacion propuesta",
    "sitio propuesto",
    "pendiente de confirmación",
    "pendiente de confirmacion",
    "provisional",
)

REGIONAL_SURVEILLANCE_NOTE_EN = (
    "Note: Weekly respiratory virus updates (COVID-19, flu, and RSV) are tracked across the "
    "4-county Atlanta Health Service Area (HSA: Fulton, DeKalb, Clayton, and Gwinnett), "
    "not by individual street or neighborhood."
)

REGIONAL_SURVEILLANCE_NOTE_ES = (
    "Nota: Las actualizaciones semanales de virus respiratorios (COVID-19, gripe y VRS) se miden "
    "en el Área de Servicio de Salud (HSA) de 4 condados de Atlanta (Fulton, DeKalb, Clayton y Gwinnett), "
    "no por calle o vecindario individual."
)


def _resolve_final_plan(state: Dict[str, Any], county_fips: str = "13121") -> DraftPlan:
    """Extracts `final_plan` (or `draft_plan` fallback) from `session.state`."""
    raw_plan = state.get(STATE_FINAL_PLAN) or state.get(STATE_DRAFT_PLAN)
    if isinstance(raw_plan, DraftPlan):
        return raw_plan
    if isinstance(raw_plan, dict):
        return DraftPlan.model_validate(raw_plan)
    return build_mock_draft_plan(county_fips=county_fips)


def format_outreach_messages_from_plan(
    final_plan: DraftPlan,
    county_name: str = "Fulton",
) -> OutreachMessages:
    """Deterministically formats grounded 6th-grade EN/ES outreach notices from `final_plan`."""
    stop_notices: List[StopOutreachDraft] = []
    stop_venue_by_rank: Dict[int, str] = {}

    for stop in final_plan.stops:
        stop_venue_by_rank[stop.stop_rank] = stop.candidate_venue_name
        en_notice = (
            f"PROPOSED LOCATION — Pending host site confirmation before public release: "
            f"Our mobile health van is proposed to visit near {stop.candidate_venue_name} "
            f"(neighborhood tract {stop.primary_tract_geoid}) on Saturday, {stop.assigned_saturday}. "
            f"Neighbors can stop by for free blood pressure, diabetes, asthma, and routine wellness checkups "
            f"near Saturday bus routes."
        )
        es_notice = (
            f"UBICACIÓN PROPUESTA — Pendiente de confirmación del sitio antes del anuncio público: "
            f"Nuestra clínica móvil de salud propone visitar cerca de {stop.candidate_venue_name} "
            f"(sector {stop.primary_tract_geoid}) el sábado {stop.assigned_saturday}. "
            f"Los vecinos podrán recibir chequeos gratuitos de presión arterial, diabetes, asma y salud preventiva "
            f"cerca de las rutas de autobús del sábado."
        )
        why_chosen = (
            f"We prioritized the area around {stop.candidate_venue_name} (Stop #{stop.stop_rank}) because "
            f"many residents live far from a sliding-scale safety-net clinic, many households do not have a car, "
            f"and routine checkup and chronic care needs are high."
        )
        stop_notices.append(
            StopOutreachDraft(
                stop_rank=stop.stop_rank,
                assigned_saturday=stop.assigned_saturday,
                candidate_venue_name=stop.candidate_venue_name,
                english_notice=en_notice,
                spanish_notice=es_notice,
                why_chosen_explanation=why_chosen,
                provisional_disclaimer_included=True,
            )
        )

    unpicked_explanations: List[UnpickedNeighborhoodExplanation] = []
    for ru in final_plan.runner_up_tracts:
        nearest_rank = ru.covered_by_stop_rank or 1
        nearest_venue = stop_venue_by_rank.get(nearest_rank, f"Stop #{nearest_rank}")
        dist_km = round(float(ru.distance_to_nearest_selected_stop_km), 1)
        en_exp = (
            f"We know your neighborhood (tract {ru.tract_geoid}, ranked #{ru.need_rank} in health need) "
            f"needs convenient care. Because our mobile van only has four Saturdays this month, we proposed "
            f"Stop #{nearest_rank} just {dist_km} km away near {nearest_venue} so one Saturday location can "
            f"serve both neighborhoods without overlapping two vans in the same area. You are warmly invited to "
            f"visit Stop #{nearest_rank} once the host site is confirmed!"
        )
        es_exp = (
            f"Sabemos que su vecindario (sector {ru.tract_geoid}, puesto #{ru.need_rank} en necesidad de salud) "
            f"necesita atención médica cercana. Como nuestra unidad móvil solo cuenta con cuatro sábados este mes, "
            f"propusimos la Parada #{nearest_rank} a solo {dist_km} km cerca de {nearest_venue} para atender a ambos "
            f"vecindarios sin duplicar dos unidades en la misma zona. ¡Les invitamos cordialmente a la Parada #{nearest_rank} "
            f"una vez que se confirme el lugar!"
        )
        unpicked_explanations.append(
            UnpickedNeighborhoodExplanation(
                tract_geoid=ru.tract_geoid,
                need_rank=ru.need_rank,
                nearest_selected_stop_rank=nearest_rank,
                distance_to_selected_stop_km=dist_km,
                english_explanation=en_exp,
                spanish_explanation=es_exp,
            )
        )

    return OutreachMessages(
        county_name=county_name,
        stop_notices=stop_notices,
        unpicked_neighborhood_explanations=unpicked_explanations,
        regional_surveillance_note_en=REGIONAL_SURVEILLANCE_NOTE_EN,
        regional_surveillance_note_es=REGIONAL_SURVEILLANCE_NOTE_ES,
    )


def draft_bilingual_outreach_messages(
    county_fips: str = "13121",
    tool_context: Optional[Any] = None,
    **kwargs: Any,
) -> Dict[str, Any]:
    """Drafts grounded English and Spanish community outreach notices and runner-up explanations.

    Reads `final_plan` and `audit_report` from `tool_context.state` and writes
    `tool_context.state["outreach_messages"]`.
    """
    state: Dict[str, Any] = {}
    if tool_context is not None and isinstance(getattr(tool_context, "state", None), dict):
        state = tool_context.state

    final_plan = _resolve_final_plan(state, county_fips=county_fips)
    settings = get_settings()

    with trace_span(
        "agent.communicator.draft_outreach",
        county_fips=final_plan.county_fips,
    ) as span:
        outreach = format_outreach_messages_from_plan(
            final_plan=final_plan,
            county_name=settings.default_county_name,
        )
        payload = outreach.model_dump()
        assert_no_pii_in_payload(payload)

        span.set_attribute("stops_drafted_count", len(outreach.stop_notices))
        span.set_attribute(
            "unpicked_explanations_count", len(outreach.unpicked_neighborhood_explanations)
        )
        span.set_attribute("languages", ["en", "es"])

        record_structured_log(
            component="community_communications_agent",
            event_type="draft_bilingual_outreach_messages",
            county_fips=final_plan.county_fips,
            stops_drafted_count=len(outreach.stop_notices),
            unpicked_explanations_count=len(outreach.unpicked_neighborhood_explanations),
            languages=["en", "es"],
        )

        if tool_context is not None and isinstance(getattr(tool_context, "state", None), dict):
            tool_context.state[STATE_OUTREACH_MESSAGES] = payload

        return payload


def _extract_outreach_dict(llm_response: Any, state: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Extracts an `OutreachMessages` dictionary from `llm_response` or `state`."""
    if isinstance(llm_response, OutreachMessages):
        return llm_response.model_dump()
    if isinstance(llm_response, dict) and "stop_notices" in llm_response:
        return llm_response

    text = ""
    if isinstance(llm_response, str):
        text = llm_response
    elif hasattr(llm_response, "text") and getattr(llm_response, "text"):
        text = str(getattr(llm_response, "text"))
    elif hasattr(llm_response, "content"):
        content = getattr(llm_response, "content")
        if hasattr(content, "parts") and getattr(content, "parts"):
            text = " ".join(str(getattr(p, "text", p)) for p in getattr(content, "parts"))
        else:
            text = str(content)

    if text.strip().startswith("{"):
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict) and "stop_notices" in parsed:
                return parsed
        except Exception:
            pass

    state_outreach = state.get(STATE_OUTREACH_MESSAGES)
    if isinstance(state_outreach, OutreachMessages):
        return state_outreach.model_dump()
    if isinstance(state_outreach, dict) and "stop_notices" in state_outreach:
        return state_outreach
    return None


def communicator_after_model_guardrail(
    callback_context: Any,
    llm_response: Any,
) -> Optional[Any]:
    """Post-model guardrail blocking invented bookings, missing provisional disclaimers, or HSA grain omissions."""
    raw_text = str(llm_response)
    if hasattr(llm_response, "text") and getattr(llm_response, "text"):
        raw_text = str(getattr(llm_response, "text"))

    lowered_raw = raw_text.lower()
    for phrase in FORBIDDEN_BOOKING_PATTERNS:
        if phrase in lowered_raw:
            raise PolicyViolationError(
                f"Community Communications guardrail blocked unverified booking claim: '{phrase}'."
            )

    after_model_guardrail_callback(callback_context, llm_response)

    state: Dict[str, Any] = {}
    if callback_context is not None and isinstance(getattr(callback_context, "state", None), dict):
        state = callback_context.state

    outreach_dict = _extract_outreach_dict(llm_response, state)
    if outreach_dict is not None:
        assert_no_pii_in_payload(outreach_dict)
        outreach = OutreachMessages.model_validate(outreach_dict)

        for notice in outreach.stop_notices:
            if not notice.provisional_disclaimer_included:
                raise PolicyViolationError(
                    f"Stop #{notice.stop_rank} outreach draft is missing provisional_disclaimer_included=True."
                )
            en_low = notice.english_notice.lower()
            es_low = notice.spanish_notice.lower()
            if not notice.english_notice.strip() or not notice.spanish_notice.strip():
                raise PolicyViolationError(
                    f"Stop #{notice.stop_rank} outreach draft must include non-empty English and Spanish notices."
                )
            for phrase in FORBIDDEN_BOOKING_PATTERNS:
                if phrase in en_low or phrase in es_low:
                    raise PolicyViolationError(
                        f"Stop #{notice.stop_rank} notice contains forbidden booking claim: '{phrase}'."
                    )
            if not any(q in en_low for q in PROVISIONAL_QUALIFIER_PATTERNS_EN):
                raise PolicyViolationError(
                    f"Stop #{notice.stop_rank} English notice is missing a provisional/proposed site disclaimer."
                )
            if not any(q in es_low for q in PROVISIONAL_QUALIFIER_PATTERNS_ES):
                raise PolicyViolationError(
                    f"Stop #{notice.stop_rank} Spanish notice is missing a provisional/proposed site disclaimer."
                )

        # Verify regional surveillance notes mention the multi-county Health Service Area (HSA)
        en_hsa = outreach.regional_surveillance_note_en.lower()
        es_hsa = outreach.regional_surveillance_note_es.lower()
        if not any(tok in en_hsa for tok in ("health service area", "hsa", "4-county", "multi-county")):
            raise PolicyViolationError(
                "English regional surveillance note must explicitly reference the multi-county Health Service Area (HSA)."
            )
        if not any(
            tok in es_hsa
            for tok in ("área de servicio de salud", "area de servicio de salud", "hsa", "4 condados", "multicondado")
        ):
            raise PolicyViolationError(
                "Spanish regional surveillance note must explicitly reference the multi-county Health Service Area (HSA)."
            )

    return None


def build_community_communications_agent() -> LlmAgent:
    """Builds the ADK `LlmAgent` for the CareBridge AI Community Communications Agent (Plan 08)."""
    settings = get_settings()
    return LlmAgent(
        name="community_communications_agent",
        model=settings.gemini_model_fast,
        description=(
            "Community Communications Agent: Drafts grounded, 6th-grade reading level English and Spanish "
            "provisional outreach notices and plain-language siting explanations without inventing bookings."
        ),
        instruction=COMMUNICATOR_AGENT_INSTRUCTION,
        tools=[FunctionTool(func=draft_bilingual_outreach_messages)],
        output_key=STATE_OUTREACH_MESSAGES,
        output_schema=OutreachMessages,
        generate_content_config=types.GenerateContentConfig(
            temperature=0.2,
            safety_settings=default_vertex_safety_settings(),
        ),
        before_model_callback=before_model_guardrail_callback,
        after_model_callback=communicator_after_model_guardrail,
        before_tool_callback=before_tool_guardrail_callback,
        after_tool_callback=after_tool_race_and_pii_callback,
    )
