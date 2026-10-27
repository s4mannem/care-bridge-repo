# Plan 02 — Health & Access Evidence Agent (Evidence Agent A · MCP)

> **Component Role**: Implements the **Health & Access Agent** (`data-node="health"`) in Lane 01 (Parallel Evidence Collection) of the CareBridge AI architecture diagram.
> **ADK Primitive**: `LlmAgent` running as Branch A inside the Coordinator's `ParallelAgent` (`evidence_collection_parallel`), consuming BigQuery MCP tools and writing strictly to `session.state["health_evidence"]`.

---

## 1. Executive Summary & Architectural Purpose

From the CareBridge AI architecture specification and `c5_01_load_explore.ipynb`:
- **Responsibility**: *"Joins tract healthcare burden and safety-net distances; reads facility coverage and shortage designations. Reads the notebook’s core BigQuery tables. It distinguishes CDC PLACES modeled prevalence from observed counts and straight-line distance to federally recognized sites from actual travel time."*
- **State Contract**:
  - **Reads**: `session.state["plan_request"]` (specifically `county_fips`, `county_name`, `strategy`).
  - **Writes**: `output_key="health_evidence"` (`HealthEvidence` JSON / Pydantic model).
- **Critical Domain Rules Enforced**:
  1. **Two Uninsured Columns (`pct_uninsured` vs `pct_uninsured_all_ages`)**: Explicitly reports `pct_uninsured` (CDC PLACES adults 18–64) as the primary uninsured metric while recording `pct_uninsured_all_ages` (CDC SVI civilian population) and their difference as an age-structure/Medicare signal.
  2. **Two HPSA Layers (`shortage_areas` vs `shortage_facilities`)**: Never confuses `shortage_areas` (where need is — `0` designated in Fulton County) with `shortage_facilities` (where care already is — `6` in Fulton County). Reporting `0` designated shortage areas in Fulton alongside `135` tracts with a safety-net gap is a key analytical finding.
  3. **Multi-County Health Service Area (`disease_weekly`)**: Tags `disease_weekly` respiratory trends (`percent_visits_covid`, `percent_visits_influenza`, `percent_visits_rsv`) with `SpatialGrain.MULTI_COUNTY_HSA` and never attributes them to an individual census tract.
  4. **PM2.5 Air Quality Scale**: Never ranks census tracts by mean PM2.5 (`12 km` grid resolution wearing an `11-char` tract ID); uses tail days above threshold (`> 20 ug/m3`) or county-level context only.
  5. **Race-Blind & PII-Free**: Never queries or outputs SVI Theme 3 (`RPL_THEME3`), `RPL_THEMES`, or `FQHC_ADMIN_CONTACT_*`.

---

## 2. File Ownership (Strict Isolation for Parallel Builds)

This plan owns **only** the following files:
```text
/Users/dvt112/Downloads/A4I/
├── carebridge/
│   └── agents/
│       └── health_agent/
│           ├── __init__.py
│           ├── prompts.py
│           ├── tools.py
│           └── agent.py
└── tests/
    └── test_02_health_agent.py
```

---

## 3. Step-by-Step Implementation Specification

### Step 3.1: System Prompt (`carebridge/agents/health_agent/prompts.py`)

```python
HEALTH_AGENT_INSTRUCTION = """You are the CareBridge AI Health & Access Evidence Agent (Evidence Agent A).
Your job is to retrieve and structure public-health burden, safety-net access distances, HRSA shortage designations,
air exposure tail metrics, and regional respiratory surveillance for county_fips={plan_request?}.

STRICT SCIENTIFIC & DATA GRAIN RULES:
1. CDC PLACES metrics (pct_uninsured_18_64, pct_asthma, pct_copd, pct_diabetes, pct_bphigh, pct_checkup) are
   MODELED small-area estimates (with 95% confidence intervals), not direct patient headcounts. Always tag them as
   modeled_small_area_estimate and populate `pct_checkup_gap` as `100.0 - pct_checkup` (because low routine checkup
   is bad—it must be inverted so higher values indicate greater preventive gap).
2. Report `pct_uninsured_18_64` (PLACES adults 18-64) as the primary uninsured measure and `pct_uninsured_all_ages`
   (SVI all ages) separately, noting their difference reflects Medicare coverage among adults 65+.
3. `km_to_any_care` and `km_to_safety_net` in `tract_access` are STRAIGHT-LINE Euclidean UPPER-BOUND distances to
   federally-recognized facilities (`care_sites`) inside the county line (`care_sites_state` checks cross-border
   proximity)—NOT road or transit travel times, and NOT inclusive of non-federal free/charitable clinics, county health
   departments, pharmacies (NPPES excluded due to practitioner PII), or unlicensed mobile clinics. Read HRSA
   `TOT_OPER_HR_PER_WEEK` from `care_sites` to report actual federal facility operating hours.
4. Distinguish `shortage_areas` (Layer 11 polygons = underserved areas; 0 active in Fulton because all 99 are
   `Proposed For Withdrawal`) from `shortage_facilities` (Layer 9 points = 6 existing clinics serving underserved
   populations). Reporting 0 active shortage areas alongside 135 tracts with a safety-net gap is a key finding.
5. `disease_weekly` (NSSP ED visits for COVID, Influenza, RSV) is measured at the 4-county Health Service Area
   (HSA: Fulton, DeKalb, Clayton, Gwinnett) level. NEVER claim COVID/flu/RSV is rising in a specific census tract or
   neighborhood. If values are NULL, report `data_unavailable=True` ("we cannot tell"), never "no increase".
6. NEVER include race, ethnicity, SVI Theme 3, or individual contact PII (`FQHC_ADMIN_CONTACT_*`).

Call `fetch_county_health_evidence` to gather the structured `HealthEvidence` payload and return it as valid JSON
matching the `HealthEvidence` schema.
"""
```

---

### Step 3.2: MCP-Backed Evidence Tool (`carebridge/agents/health_agent/tools.py`)

Wraps the BigQuery MCP named queries from `carebridge.data_plane.bq_mcp_client` (with automatic fallback to `carebridge.mocks.fulton_fixtures` when testing offline or in parallel before Plan 01 is live):
- Executes:
  1. `mcp_query_tract_burden_and_access(county_fips)`
  2. `mcp_query_care_sites_and_shortages(county_fips)`
  3. `mcp_query_regional_disease_weekly(county_fips)`
  4. `mcp_query_air_exposure_tail(county_fips)`
- Validates every output record through `HealthEvidence.model_validate(...)` and `assert_race_blind_planner_input(...)`.
- Stores the validated `HealthEvidence` dict directly into `tool_context.state["health_evidence"]` in addition to returning it to the `LlmAgent`, guaranteeing deterministic state structure even if the LLM summarizes its text response.

---

### Step 3.3: ADK `LlmAgent` Definition (`carebridge/agents/health_agent/agent.py`)

```python
from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool
from google.genai import types

from carebridge.config import get_settings
from carebridge.contracts.state_keys import STATE_HEALTH_EVIDENCE
from carebridge.contracts.evidence_models import HealthEvidence
from carebridge.security.model_armor import default_vertex_safety_settings
from carebridge.security.owasp_guardrails import (
    before_model_guardrail_callback,
    after_model_guardrail_callback,
    before_tool_guardrail_callback,
    after_tool_race_and_pii_callback,
)
from carebridge.agents.health_agent.prompts import HEALTH_AGENT_INSTRUCTION
from carebridge.agents.health_agent.tools import fetch_county_health_evidence


def build_health_access_agent() -> LlmAgent:
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
```

---

## 4. Security, Guardrails & Telemetry

- **Unique `output_key`**: Writes strictly to `STATE_HEALTH_EVIDENCE` (`"health_evidence"`), preventing parallel state collision with `mobility_evidence` inside ADK `ParallelAgent`.
- **Optional Context Variable Syntax**: Uses `{plan_request?}` in `instruction` so ADK never crashes with `KeyError: 'Context variable not found'` during standalone unit runs.
- **Race-Blind & PII Enforcement**: `after_tool_race_and_pii_callback` inspects the returned `HealthEvidence` dict and blocks execution if any prohibited column (`rpl_theme3`, `fqhc_admin_contact_*`) is present.
- **OpenTelemetry Instrumentation**: Emits span `agent.health_access.fetch_evidence` recording `tracts_loaded`, `shortage_areas_count`, `shortage_facilities_count`, and `hsa_data_unavailable`.

---

## 5. Verification & Unit Tests (`tests/test_02_health_agent.py`)

Run standalone (without needing Plans 01 or 03–11 completed):
```bash
pytest tests/test_02_health_agent.py -v
```
Tests must verify:
1. `fetch_county_health_evidence` returns a valid `HealthEvidence` instance for Fulton County (`13121`) using mock fixtures.
2. `shortage_areas_count == 0` and `shortage_facilities_count == 6` for Fulton County are preserved with an explicit lineage flag noting the federal shortage designation gap.
3. `regional_disease.spatial_grain == SpatialGrain.MULTI_COUNTY_HSA` and `grain_warning` is populated.
4. Running `build_health_access_agent()` via `InMemoryRunner` populates `session.state["health_evidence"]` and passes `assert_race_blind_planner_input`.

---

## 6. Antigravity Execution Prompt

> **Copy-paste into Antigravity to execute Plan 02:**
> "Execute `/Users/dvt112/Downloads/A4I/plans/02_health_access_evidence_agent.md`. Create `carebridge/agents/health_agent/` (`__init__.py`, `prompts.py`, `tools.py`, `agent.py`) and `tests/test_02_health_agent.py`. Ensure it uses `carebridge/contracts/` and `carebridge/security/` from Plan 00. Run `pytest tests/test_02_health_agent.py -v` and verify all tests pass."
