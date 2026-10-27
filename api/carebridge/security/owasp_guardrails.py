"""OWASP LLM Top 10 callbacks for ADK LlmAgents (`before_model`, `after_model`, `before_tool`, `after_tool`)."""

from __future__ import annotations

import re
from typing import Any, Dict, Optional
from carebridge.security.model_armor import ModelArmorScreener
from carebridge.security.race_blind_guard import (
    PolicyViolationError,
    assert_no_pii_in_payload,
    assert_race_blind_planner_input,
)

_SCREENER = ModelArmorScreener()

READONLY_SQL_FORBIDDEN_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|REPLACE|MERGE|GRANT|REVOKE|CALL|EXECUTE)\b",
    re.I,
)

UNVERIFIED_BOOKING_CLAIM_REGEX = re.compile(
    r"\b(officially\s+booked|confirmed\s+parking|guaranteed\s+appointments|reservado\s+oficialmente)\b",
    re.I,
)


def sanitize_user_prompt(text: str) -> str:
    """Screens a user-supplied text input for prompt injection and individual PII."""
    is_clean, reason = _SCREENER.screen_input(text)
    if not is_clean:
        raise PolicyViolationError(reason)
    assert_no_pii_in_payload(text)
    return text


def assert_readonly_sql(sql_query: str) -> None:
    """Verifies a SQL query is strictly read-only (`SELECT` or `WITH`) and contains no DDL/DML."""
    stripped = re.sub(r"--[^\n]*", "", sql_query).strip()
    if not stripped.upper().startswith(("SELECT", "WITH")):
        raise PolicyViolationError("SQL query must start with SELECT or WITH (read-only policy).")
    if READONLY_SQL_FORBIDDEN_KEYWORDS.search(stripped):
        raise PolicyViolationError("SQL query contains forbidden DDL/DML keyword.")


def before_model_guardrail_callback(
    callback_context: Any,
    llm_request: Any,
) -> Optional[Any]:
    """ADK `before_model_callback`: screens outgoing LLM prompt for injection, PII, and race-blind isolation."""
    agent_name = getattr(callback_context, "agent_name", "") or ""
    request_str = str(llm_request)
    is_clean, reason = _SCREENER.screen_input(request_str)
    if not is_clean:
        raise PolicyViolationError(reason)
    assert_no_pii_in_payload(request_str)
    if agent_name in ("siting_planner_agent", "health_access_agent", "transit_community_agent"):
        assert_race_blind_planner_input(request_str)
    return None


def after_model_guardrail_callback(
    callback_context: Any,
    llm_response: Any,
) -> Optional[Any]:
    """ADK `after_model_callback`: ensures model output never leaks PII or fabricates confirmed bookings."""
    response_str = str(llm_response)
    assert_no_pii_in_payload(response_str)
    if UNVERIFIED_BOOKING_CLAIM_REGEX.search(response_str):
        raise PolicyViolationError(
            "OWASP LLM09: Model output claimed an unverified host site is officially booked/confirmed."
        )
    return None


def before_tool_guardrail_callback(
    tool: Any,
    args: Dict[str, Any],
    tool_context: Any,
) -> Optional[Dict[str, Any]]:
    """ADK `before_tool_callback`: enforces tool permission boundary (OWASP LLM06)."""
    tool_name = getattr(tool, "name", None) or getattr(tool, "__name__", str(tool))
    agent_name = getattr(tool_context, "agent_name", "") or ""
    if tool_name in ("mcp_query_posthoc_demographic_audit", "execute_independent_plan_audit"):
        if agent_name != "equity_rigor_auditor":
            raise PolicyViolationError(
                f"OWASP LLM06 Access Boundary Violation: Agent '{agent_name}' is not allowed to call '{tool_name}'."
            )
    assert_no_pii_in_payload(args)
    if agent_name != "equity_rigor_auditor":
        assert_race_blind_planner_input(args)
    return None


def after_tool_race_and_pii_callback(
    tool: Any,
    args: Dict[str, Any],
    tool_context: Any,
    tool_response: Any,
) -> Optional[Dict[str, Any]]:
    """ADK `after_tool_callback`: ensures tool outputs for Evidence/Planner agents are PII-free and race-blind."""
    agent_name = getattr(tool_context, "agent_name", "") or ""
    assert_no_pii_in_payload(tool_response)
    if agent_name != "equity_rigor_auditor":
        assert_race_blind_planner_input(tool_response)
    return None
