# Plan 06 — Siting Planner Agent (Race-Blind Inputs)

> **Component Role**: Implements the **Siting Planner Agent** (`data-node="planner"`) in Lane 02 (Decide, Optimize, Challenge) of the CareBridge AI architecture diagram.
> **ADK Primitive**: `LlmAgent` executing inside the Coordinator's `LoopAgent(max_iterations=2)`, calling the `Four-Stop Coverage Optimizer` deterministic tool and writing `session.state["draft_plan"]`.

---

## 1. Executive Summary & Architectural Purpose

From the CareBridge AI architecture diagram:
- **Responsibility**: *"Creates ranked tract and candidate-stop proposals using only permitted non-demographic attributes and deterministic scoring. It explains decisions in plain language and can respond to non-demographic audit defects. Writes `draft_plan`: four proposed distinct stops or an explicit `insufficient_candidates` status. Never consumes race/ethnicity data."*
- **State Contract**:
  - **Reads**:
    - `session.state["plan_request"]`
    - `session.state["health_evidence"]`
    - `session.state["mobility_evidence"]`
    - `session.state["evidence_report"]`
    - `session.state["non_demographic_feedback"]` (optional; populated only on revision iteration 1 after Auditor rejection).
  - **Never Reads**: `session.state["audit_report"]` (which contains `demographic_impact`) or `external_demographic_audit`.
  - **Writes**: `output_key="draft_plan"` (`DraftPlan` JSON / Pydantic model) and appends each draft to `session.state["revision_history"]`.
- **Why Separate Agent? (`c5_01_load_explore.ipynb` Section 13)**:
  - The Planner is strictly denied access to race/ethnicity features and is instructed to optimize structural healthcare access (`pct_uninsured_18_64`, `km_to_safety_net`, `pct_no_vehicle`, chronic/respiratory burden, and Saturday transit availability).
  - It delegates all numerical scoring and 4-site selection to the deterministic `optimize_four_clinic_stops` tool (Plan 05) and enriches each stop with source-backed plain-language reasoning, explicit spatial grain disclosures (`tract` vs `12 km grid` vs `multi-county HSA`), and provisional host warnings.

---

## 2. File Ownership (Strict Isolation for Parallel Builds)

This plan owns **only** the following files:
```text
/Users/dvt112/Downloads/A4I/
├── carebridge/
│   └── agents/
│       └── planner_agent/
│           ├── __init__.py
│           ├── prompts.py
│           └── agent.py
└── tests/
    └── test_06_planner_agent.py
```

---

## 3. Step-by-Step Implementation Specification

### Step 3.1: System Prompt (`carebridge/agents/planner_agent/prompts.py`)

Note how the Siting Planner's prompt is explicitly **ANALYTICAL, CITED, AND RESOLUTION-QUALIFIED** (for the public-health outreach lead), deliberately separated from the Community Communications Agent's warm 6th-grade bus-stop flyer prompt so we never get "hedged flyers or chatty technical notes":

```python
PLANNER_AGENT_INSTRUCTION = """You are the CareBridge AI Siting Planner Agent.
Your posture is ANALYTICAL, SOURCE-CITED, and RESOLUTION-QUALIFIED. You write for the county public-health outreach
lead (not bus-stop flyers—that is the Community Communications Agent's role).
Your task is to propose a four-Saturday mobile health clinic siting plan (`draft_plan`) for the county using ONLY
structural, clinical, preventive-gap (`100 - pct_checkup`), and transit access factors—NEVER race or ethnicity.

Available session.state inputs:
- plan_request: {plan_request?}
- evidence_report: {evidence_report?}
- non_demographic_feedback (if revision 1): {non_demographic_feedback?}

MANDATORY EXECUTION RULES:
1. First check `evidence_report.core_tables_ready`. If False, return a `DraftPlan` with
   `status="insufficient_candidates"` and list the blocking failures in `planner_notes`.
2. NEVER compute need scores or pick tracts using your own free-text math. You MUST call the deterministic tool
   `optimize_four_clinic_stops` (which reads `health_evidence`, `mobility_evidence`, and any
   `non_demographic_feedback` from state) to select the 4 stops, identify `runner_up_tracts` (#5-#8), and compute
   sensitivity metrics.
3. For each of the 4 stops selected by `optimize_four_clinic_stops`, provide an analytical, source-cited,
   resolution-qualified `plain_language_rationale`, `evidence_citations`, and `spatial_grain_disclosures`:
   - State the tract's `pct_uninsured_18_64` (CDC PLACES modeled estimate for adults 18-64, noting 95% CI uncertainty),
     `pct_checkup_gap` (`100 - pct_checkup` preventive checkup gap), `pct_no_vehicle` (CDC SVI 5-year ACS survey
     estimate), and `km_to_safety_net` (straight-line upper-bound distance to nearest federally-recognized FQHC/Health
     Center inside the county border).
   - Explain why 5+ km without a car is a full-day barrier (bus transfers, time off work).
   - If mentioning respiratory illness trends (`disease_weekly`), explicitly state they apply to the 4-county
     Health Service Area (HSA: Fulton, DeKalb, Clayton, Gwinnett), NOT the specific census tract.
   - Keep `host_verified=False` and preserve the `provisional_warning` on every stop.
4. Answer Question 7 ("How do I tell the neighborhood we didn't pick why we didn't pick them?"): Ensure
   `runner_up_tracts` (#5-#8) includes a clear `technical_deferral_rationale` for each runner-up neighborhood
   (e.g., already covered within 4 km of Stop #1, within the 5 km inter-stop separation buffer, or lower marginal
   uncovered population).
5. If `non_demographic_feedback` is present (Revision 1), explicitly address every operational or evidentiary
   defect flagged by the Auditor (e.g., resolving catchment overlap, removing unsupported tract-level NSSP claims,
   or replacing an infeasible host) and note the change in `planner_notes`.
6. NEVER reference race, ethnicity, SVI Theme 3, or demographic parity targets.
"""
```

---

### Step 3.2: Planner Pre-Model Race-Blind State Filter & Agent Builder (`carebridge/agents/planner_agent/agent.py`)

Implement `planner_before_model_callback`:
- Inspects the `llm_request` contents and system instruction before every Gemini API call in `siting_planner_agent`.
- Calls `assert_race_blind_planner_input` on the prompt text and ensures that `session.state["audit_report"]` is never injected into the Planner's prompt context.
- If `optimize_four_clinic_stops` from `carebridge.tools.optimizer.tool` is not yet installed during isolated unit testing, provides a clean interface fallback so `test_06_planner_agent.py` can run independently in parallel with Plan 05.

```python
from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool
from google.genai import types

from carebridge.config import get_settings
from carebridge.contracts.state_keys import STATE_DRAFT_PLAN
from carebridge.contracts.plan_models import DraftPlan
from carebridge.security.model_armor import default_vertex_safety_settings
from carebridge.agents.planner_agent.prompts import PLANNER_AGENT_INSTRUCTION


def build_siting_planner_agent(optimizer_tool_func=None) -> LlmAgent:
    settings = get_settings()
    if optimizer_tool_func is None:
        from carebridge.tools.optimizer.tool import optimize_four_clinic_stops
        optimizer_tool_func = optimize_four_clinic_stops

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
    )
```

---

## 4. Security, Guardrails & Telemetry

- **Strict Race-Blind Context Isolation**: The Planner prompt only interpolates `{plan_request?}`, `{evidence_report?}`, and `{non_demographic_feedback?}` — it never interpolates `{audit_report?}`. Furthermore, `planner_race_blind_before_model_callback` scans the outgoing `LlmRequest` and raises `PolicyViolationError` if any demographic token (`rpl_theme3`, `pct_black`, `pct_hispanic`, `external_demographic_audit`) appears.
- **Revision History Tracking**: Every time `siting_planner_agent` produces a `DraftPlan`, `planner_after_model_callback` appends a deep copy of `DraftPlan` into `session.state["revision_history"]` so the final API response preserves both Draft 0 (rejected) and Draft 1 (revised).
- **Telemetry**: Emits OpenTelemetry span `agent.siting_planner.plan` with `revision_number`, `status`, `stop_geoids`, and token counts.

---

## 5. Verification & Unit Tests (`tests/test_06_planner_agent.py`)

Run standalone:
```bash
pytest tests/test_06_planner_agent.py -v
```
Tests must verify:
1. `planner_race_blind_before_model_callback` blocks any prompt containing `rpl_theme3` or `demographic_impact`.
2. When `evidence_report.core_tables_ready == False`, Planner outputs `DraftPlan(status="insufficient_candidates")`.
3. On initial run (`revision_number=0`) and revision run (`revision_number=1` with `non_demographic_feedback`), `session.state["draft_plan"]` is updated and `session.state["revision_history"]` records both drafts in order.
4. Every stop in `draft_plan.stops` has `host_verified is False` and non-empty `evidence_citations` and `spatial_grain_disclosures`.

---

## 6. Antigravity Execution Prompt

> **Copy-paste into Antigravity to execute Plan 06:**
> "Execute `/Users/dvt112/Downloads/A4I/plans/06_siting_planner_agent.md`. Create `carebridge/agents/planner_agent/` (`__init__.py`, `prompts.py`, `agent.py`) and `tests/test_06_planner_agent.py`. Run `pytest tests/test_06_planner_agent.py -v` and verify all tests pass."
