# Plan 04 — Evidence Validator Agent (Independent Data-Quality Gate)

> **Component Role**: Implements the **Evidence Validator Agent** (`data-node="quality"`) in Lane 01 of the CareBridge AI architecture diagram.
> **ADK Primitive**: `LlmAgent` with deterministic validation rules (`check()` vs `note()` from `c5_01_load_explore.ipynb` Section 12), writing `session.state["evidence_report"]`.

---

## 1. Executive Summary & Architectural Purpose

From the CareBridge AI architecture diagram and `c5_01_load_explore.ipynb` Section 12:
- **Responsibility**: *"Checks schema joins and county codes, geographic granularity, missing source coverage, noncomparable units and prohibited or misleading claims before the planner acts. Writes `evidence_report` with validated evidence, caveats and availability statuses. Core failures block a plan, optional data gaps do not."*
- **Two-Verdict Validation Architecture (from `c5_01_load_explore.ipynb`)**:
  1. **`check()` (Pipeline Integrity — Fatal / Blocking)**:
     - `burden_tracts` is non-empty (`> 0` rows).
     - Every `geo_id` is exactly 11 characters (`LENGTH(geo_id) == 11`).
     - Every `geo_id` starts with `county_fips` (`STARTS_WITH(geo_id, '13121')`).
     - Zero duplicate tract IDs (`COUNT(*) == COUNT(DISTINCT geo_id)`).
     - Latitude is in `[17, 72]` degrees and longitude in `[-180, -60]` degrees.
     - `care_sites_count > 0` and every tract has a valid `km_to_any_care` and `km_to_safety_net`.
     - Zero race/ethnicity (`RPL_THEME3`, `RPL_THEMES`) or individual PII (`FQHC_ADMIN_CONTACT_*`) columns leaked into evidence.
  2. **`note()` (Publisher Data Nuances — Warns & Attaches Caveats, Escalates Only Above Threshold)**:
     - Impossible prevalences (`< 0` or `> 100`).
     - Zero-population or suppressed PLACES tracts (airports, parks, institutional tracts — warn under 5%, fail only above threshold).
     - `shortage_areas_count == 0` (e.g., Fulton County has `0` designated primary-care HPSA shortage areas despite `135` tracts having a safety-net gap — recorded as a key finding, NOT an error).
     - `disease_weekly` grain check (`Tract != HSA`) and missingness check (`data_unavailable` weeks).
     - Optional dataset status (`marta_gtfs_available`, `usda_food_access_available`, `imls_venues_available` — missing optional datasets produce a `WARN` caveat, NEVER a blocking failure).

---

## 2. File Ownership (Strict Isolation for Parallel Builds)

This plan owns **only** the following files:
```text
/Users/dvt112/Downloads/A4I/
├── carebridge/
│   └── agents/
│       └── validator_agent/
│           ├── __init__.py
│           ├── prompts.py
│           ├── rules.py
│           └── agent.py
└── tests/
    └── test_04_validator_agent.py
```

---

## 3. Step-by-Step Implementation Specification

### Step 3.1: Deterministic `check()` & `note()` Rule Engine (`carebridge/agents/validator_agent/rules.py`)

Implement `evaluate_evidence_quality(health_evidence: HealthEvidence, mobility_evidence: MobilityEvidence) -> EvidenceReport`:
- Runs sequentially **after** `ParallelAgent` (`health_access_agent` + `transit_community_agent`) completes in Lane 01.
- Runs all pipeline `check()` rules and publisher `note()` rules deterministically in Python.
- Enforces the **4 spatial resolutions** (`11-char Tract`, `12km PM2.5 Grid`, `Facility Point`, `4-County HSA`) and all **7 "Questions that need more than we gave you"** boundaries:
  - Verifies `health_evidence.regional_disease.spatial_grain == SpatialGrain.MULTI_COUNTY_HSA`.
  - Verifies `pct_checkup_gap == round(100.0 - pct_checkup, 2)` so routine checkup is properly inverted (`100 - pct_checkup`).
  - Injects mandatory caveats into `EvidenceReport.caveats`:
    1. `"4 SPATIAL RESOLUTIONS (TRACT != 12KM GRID != FACILITY POINT != 4-COUNTY HSA): Weekly respiratory ED trends (NSSP) represent the 4-county Health Service Area (Fulton, DeKalb, Clayton, Gwinnett), never an individual census tract; PM2.5 is a 12km grid (`p90/p10=1.05x`) and cannot rank neighborhoods."`
    2. `"DISTANCE != JOURNEY TIME: km_to_any_care and km_to_safety_net are straight-line Euclidean upper-bound distances to federally recognized facilities, not bus transfer or road travel times. Access Across America transit matrices are excluded (CC BY-NC)."`.
    3. `"PLACES MODELED ESTIMATES & 95% CI: Tract health prevalences are small-area modeled estimates (not patient headcounts); minor percentage-point differences (<1-2%) fall within overlapping 95% confidence intervals."`
    4. `"UPPER-BOUND FEDERAL FACILITY BOUNDARY & PII EXCLUSIONS: Non-federal free clinics, county health departments, pharmacies (NPPES excluded due to practitioner PII), FQHC_ADMIN_CONTACT_* fields, and unlicensed mobile clinics are excluded; distances represent upper bounds on distance to care."`
- Sets `core_tables_ready = (len(blocking_failures) == 0)`.

---

### Step 3.2: System Prompt (`carebridge/agents/validator_agent/prompts.py`)

```python
VALIDATOR_AGENT_INSTRUCTION = """You are the CareBridge AI Evidence Validator Agent (Independent Data-Quality Gate).
Your role is to audit the collected health and mobility evidence before the Siting Planner Agent is allowed to act.

Inputs from session.state:
- health_evidence: {health_evidence?}
- mobility_evidence: {mobility_evidence?}

RULES:
1. Call `validate_collected_evidence` to execute the deterministic `check()` (pipeline fatal) and `note()`
   (publisher warning) suite.
2. Core failures (empty burden_tracts, wrong county FIPS prefix, invalid 11-char tract IDs, missing coordinates,
   or leaked race/PII columns) MUST set `core_tables_ready=False` and block planning.
3. Optional data gaps (missing MARTA GTFS views, USDA food access, or IMLS library venues) MUST NOT block planning;
   record them in `optional_datasets_status` and `caveats`.
4. Enforce `Tract != HSA` and `Distance != journey time` caveats on every report.
"""
```

---

### Step 3.3: ADK `LlmAgent` Definition (`carebridge/agents/validator_agent/agent.py`)

```python
from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool
from google.genai import types

from carebridge.config import get_settings
from carebridge.contracts.state_keys import STATE_EVIDENCE_REPORT
from carebridge.contracts.evidence_models import EvidenceReport
from carebridge.security.model_armor import default_vertex_safety_settings
from carebridge.security.owasp_guardrails import (
    before_model_guardrail_callback,
    after_model_guardrail_callback,
    before_tool_guardrail_callback,
    after_tool_race_and_pii_callback,
)
from carebridge.agents.validator_agent.prompts import VALIDATOR_AGENT_INSTRUCTION
from carebridge.agents.validator_agent.rules import validate_collected_evidence_tool


def build_evidence_validator_agent() -> LlmAgent:
    settings = get_settings()
    return LlmAgent(
        name="evidence_validator_agent",
        model=settings.gemini_model_fast,
        description=(
            "Independent Data-Quality Gate: Validates schema joins, 11-char county tract IDs, "
            "spatial granularity (Tract != HSA, Distance != journey time), and blocks unsupported claims."
        ),
        instruction=VALIDATOR_AGENT_INSTRUCTION,
        tools=[FunctionTool(func=validate_collected_evidence_tool)],
        output_key=STATE_EVIDENCE_REPORT,
        output_schema=EvidenceReport,
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

- **Data Poisoning / Integrity Defense (OWASP LLM03 / LLM09)**: Prevents corrupted tract IDs, out-of-county rows (e.g., `13221` instead of `13121`), or impossible prevalence percentages (`>100%`) from poisoning the downstream optimizer.
- **Telemetry**: Emits OpenTelemetry span `agent.evidence_validator.validate` with attributes `core_tables_ready`, `pass_count`, `warn_count`, `fail_count`, and `validated_tract_count`.

---

## 5. Verification & Unit Tests (`tests/test_04_validator_agent.py`)

Run standalone:
```bash
pytest tests/test_04_validator_agent.py -v
```
Tests must verify:
1. Valid Fulton County (`13121`) fixtures pass with `core_tables_ready=True` and `blocking_failures == []`.
2. A tract with a 10-character `geo_id` or wrong county prefix (`13089...` DeKalb inside a Fulton `13121` pull) triggers a `FAIL` `check()` and sets `core_tables_ready=False`.
3. Missing optional datasets (`marta_gtfs_available=False`) produce a `WARN` `note()` and keep `core_tables_ready=True`.
4. `Tract != HSA` and `Distance != journey time` caveats are always present in `EvidenceReport.caveats`.

---

## 6. Antigravity Execution Prompt

> **Copy-paste into Antigravity to execute Plan 04:**
> "Execute `/Users/dvt112/Downloads/A4I/plans/04_evidence_validator_agent.md`. Create `carebridge/agents/validator_agent/` (`__init__.py`, `prompts.py`, `rules.py`, `agent.py`) and `tests/test_04_validator_agent.py`. Run `pytest tests/test_04_validator_agent.py -v` and confirm all tests pass."
