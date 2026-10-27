from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool
from google.genai import types

from ...config import Settings
from ...data.bq_mcp import BigQueryMcp
from ...security.model_armor import default_vertex_safety_settings
from ...security.owasp_guardrails import (
    after_model_guardrail_callback,
    after_tool_race_and_pii_callback,
    before_model_guardrail_callback,
    before_tool_guardrail_callback,
)
from .prompts import HEALTH_AGENT_INSTRUCTION
from .tools import make_fetch_county_health_evidence


def build_health_access_llm(settings: Settings, mcp: BigQueryMcp) -> LlmAgent:
    """The model never gets raw `execute_sql_readonly`, only the named-query tool (OWASP LLM06).

    No output_key: the tool writes `health_evidence` itself, so the model's prose can't overwrite it.
    """
    return LlmAgent(
        name="health_access_agent",
        model=settings.gemini_model_fast,
        description="Evidence Agent A: tract burden, safety-net distances, HRSA shortage layers and the "
                    "HSA respiratory signal, via the Google-managed BigQuery MCP server.",
        instruction=HEALTH_AGENT_INSTRUCTION,
        tools=[FunctionTool(func=make_fetch_county_health_evidence(mcp))],
        include_contents="none",
        disallow_transfer_to_parent=True,
        disallow_transfer_to_peers=True,
        generate_content_config=types.GenerateContentConfig(
            temperature=0.0, safety_settings=default_vertex_safety_settings()),
        before_model_callback=before_model_guardrail_callback,
        after_model_callback=after_model_guardrail_callback,
        before_tool_callback=before_tool_guardrail_callback,
        after_tool_callback=after_tool_race_and_pii_callback,
    )
