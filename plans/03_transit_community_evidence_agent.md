# Plan 03 — Transit & Community Evidence Agent (Evidence Agent B · MCP)

> **Component Role**: Implements the **Transit & Community Agent** (`data-node="mobility"`) in Lane 01 (Parallel Evidence Collection) of the CareBridge AI architecture diagram.
> **ADK Primitive**: `LlmAgent` running as Branch B inside the Coordinator's `ParallelAgent` (`evidence_collection_parallel`), consuming BigQuery MCP tools and writing strictly to `session.state["mobility_evidence"]`.

---

## 1. Executive Summary & Architectural Purpose

From the CareBridge AI architecture diagram:
- **Responsibility**: *"Adds MARTA Saturday service and stop access; optionally enriches with USDA food access and candidate library hosts. Consumes teammate-created MARTA GTFS views: accessible Saturday stops, service and route metrics. Optional USDA retailer access and IMLS library host candidates enrich the siting decision."*
- **State Contract**:
  - **Reads**: `session.state["plan_request"]` (`county_fips`, `saturdays`, `include_optional_datasets`).
  - **Writes**: `output_key="mobility_evidence"` (`MobilityEvidence` JSON / Pydantic model).
- **Critical Domain Rules Enforced**:
  1. **Graceful Degradation on Optional Datasets**: The MARTA GTFS views (`v_tract_saturday_transit_access`), USDA food access (`external_food_access`), and IMLS public library candidate venues (`candidate_venues`) are dashed/optional integrations in the architecture diagram. If any view/table is missing or `include_optional_datasets=False`, the agent **never crashes**; it sets `marta_gtfs_available=False` / `usda_food_access_available=False` / `imls_venues_available=False` and populates fallback tract centroid candidates with explicit caveats.
  2. **Stop Proximity ≠ Journey Time**: Explicitly attaches the caveat that a nearby MARTA bus stop on Saturday does not measure door-to-door clinic travel time or multi-transfer burden.
  3. **No Invented Host Bookings**: Every `CandidateHostVenue` returned by this agent carries `host_permission_verified=False`.

---

## 2. File Ownership (Strict Isolation for Parallel Builds)

This plan owns **only** the following files:
```text
/Users/dvt112/Downloads/A4I/
├── carebridge/
│   └── agents/
│       └── mobility_agent/
│           ├── __init__.py
│           ├── prompts.py
│           ├── tools.py
│           └── agent.py
└── tests/
    └── test_03_mobility_agent.py
```

---

## 3. Step-by-Step Implementation Specification

### Step 3.1: System Prompt (`carebridge/agents/mobility_agent/prompts.py`)

```python
MOBILITY_AGENT_INSTRUCTION = """You are the CareBridge AI Transit & Community Evidence Agent (Evidence Agent B).
Your job is to retrieve Saturday public transit access metrics (MARTA GTFS), optional USDA food access flags,
and candidate community host venues (IMLS public libraries and community centers) for county_fips={plan_request?}.

STRICT OPERATIONAL & DATA GRAIN RULES:
1. Call `fetch_county_mobility_evidence` to query the BigQuery MCP mobility views.
2. If optional views (`v_tract_saturday_transit_access`, `external_food_access`, `candidate_venues`) are unavailable
   or disabled by the request, gracefully degrade by setting their availability booleans to False and recording
   the limitation in `caveats`. NEVER fail the pipeline due to an optional dataset gap.
3. Always state clearly that Saturday transit stop counts within 400m measure stop presence and scheduled frequency,
   NOT door-to-door resident travel time or transfer wait times.
4. Every candidate venue MUST have `host_permission_verified=False`. Never claim a library, station lot, or
   community center has approved mobile clinic parking.
5. Never include race, ethnicity, or personal contact PII.
"""
```

---

### Step 3.2: MCP Mobility & Venue Tool (`carebridge/agents/mobility_agent/tools.py`)

Implement `fetch_county_mobility_evidence(county_fips: str = "13121", include_optional_datasets: bool = True, tool_context: ToolContext | None = None) -> dict`:
- Queries BigQuery MCP (`mcp_query_saturday_transit_and_venues`) if `include_optional_datasets=True` and not in mock mode; otherwise loads from `carebridge.mocks.fulton_fixtures` or degrades gracefully if BigQuery raises `NotFound`.
- Validates output via `MobilityEvidence.model_validate(...)`, enforces `assert_race_blind_planner_input(...)`, and writes the validated dictionary into `tool_context.state["mobility_evidence"]`.

---

### Step 3.3: ADK `LlmAgent` Definition (`carebridge/agents/mobility_agent/agent.py`)

```python
from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool
from google.genai import types

from carebridge.config import get_settings
from carebridge.contracts.state_keys import STATE_MOBILITY_EVIDENCE
from carebridge.contracts.evidence_models import MobilityEvidence
from carebridge.security.model_armor import default_vertex_safety_settings
from carebridge.security.owasp_guardrails import (
    before_model_guardrail_callback,
    after_model_guardrail_callback,
    before_tool_guardrail_callback,
    after_tool_race_and_pii_callback,
)
from carebridge.agents.mobility_agent.prompts import MOBILITY_AGENT_INSTRUCTION
from carebridge.agents.mobility_agent.tools import fetch_county_mobility_evidence


def build_transit_community_agent() -> LlmAgent:
    settings = get_settings()
    return LlmAgent(
        name="transit_community_agent",
        model=settings.gemini_model_fast,
        description=(
            "Evidence Agent B: Queries MARTA Saturday GTFS views, optional USDA food access, "
            "and IMLS candidate library/community venues with graceful degradation."
        ),
        instruction=MOBILITY_AGENT_INSTRUCTION,
        tools=[FunctionTool(func=fetch_county_mobility_evidence)],
        output_key=STATE_MOBILITY_EVIDENCE,
        output_schema=MobilityEvidence,
        generate_content_config=types.GenerateContentConfig(
            temperature=0.0,
            safety_settings=default_vertex_safety_settings(),
        ),
        before_model_callback=before_model_guardrail_callback,
        after_model_callback=after_model_guardrail_callback,
        before_tool_callback=before_tool_guardrail_callback,
        after_tool_callback=after_tool_race_and_pii_callback,
    )
```

---

## 4. Security, Guardrails & Telemetry

- **Parallel State Isolation**: Writes exclusively to `output_key="mobility_evidence"`, never touching `health_evidence`.
- **Anti-Hallucination Venue Guard**: `fetch_county_mobility_evidence` forces `host_permission_verified = False` on every `CandidateHostVenue` record regardless of source data.
- **OpenTelemetry Instrumentation**: Emits span `agent.transit_community.fetch_mobility` with attributes `marta_gtfs_available`, `imls_venues_available`, `usda_food_access_available`, and `candidate_venues_count`.

---

## 5. Verification & Unit Tests (`tests/test_03_mobility_agent.py`)

Run standalone:
```bash
pytest tests/test_03_mobility_agent.py -v
```
Tests must verify:
1. When optional datasets are enabled, `fetch_county_mobility_evidence` returns `MobilityEvidence` with Saturday MARTA stop metrics and candidate venues for Fulton County (`13121`).
2. When `include_optional_datasets=False` or BigQuery raises `NotFound`, `fetch_county_mobility_evidence` degrades gracefully without raising an exception and sets availability flags to `False`.
3. Every `CandidateHostVenue` has `host_permission_verified is False`.
4. Caveat `"A nearby Saturday bus stop measures stop presence, not door-to-door clinic journey time."` is always present.

---

## 6. Antigravity Execution Prompt

> **Copy-paste into Antigravity to execute Plan 03:**
> "Execute `/Users/dvt112/Downloads/A4I/plans/03_transit_community_evidence_agent.md`. Create `carebridge/agents/mobility_agent/` (`__init__.py`, `prompts.py`, `tools.py`, `agent.py`) and `tests/test_03_mobility_agent.py`. Run `pytest tests/test_03_mobility_agent.py -v` and confirm 100% pass rate."
