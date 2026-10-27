# Plan 07 — Independent Equity & Rigor Auditor Agent (Protected Access Boundary)

> **Component Role**: Implements the **Independent Equity & Rigor Auditor** (`data-node="auditor"`) in Lane 02 (Decide, Optimize, Challenge) of the CareBridge AI architecture diagram.
> **ADK Primitive**: `LlmAgent` executing inside a separate permission boundary with exclusive access to `external_demographic_audit` (`mcp_query_posthoc_demographic_audit`), writing `session.state["audit_report"]`, `session.state["revision_required"]`, and `session.state["non_demographic_feedback"]`.

---

## 1. Executive Summary & Architectural Purpose

As emphasized in `c5_01_load_explore.ipynb` Section 13:
> *"2. The equity audit is structurally a second agent, and this is the strong one. You are forbidden from using race as a model input and required to audit your output against it. That means your system must contain a component that sees data the planner was denied. It also must not share the planner's context, because an agent asked to produce a plan and critique it in the same breath will defend the plan. The rule you were given forces the architecture."*

And from the CareBridge AI HTML diagram:
- **Responsibility**: *"Challenges overlap, unsupported evidence, sensitivity and post-hoc demographic impacts. Cannot rewrite the plan."*
- **Protected Access Boundary**:
  - Has exclusive permission to call `run_equity_and_rigor_audit` (which invokes `mcp_query_posthoc_demographic_audit` on `external_demographic_audit`).
  - Compares the population-weighted demographics (`pct_black`, `pct_hispanic`, `pct_white`, `pct_asian`, `pct_minority`, `rpl_theme3_proxy`) of the 4 selected stop catchments against the Fulton County population baseline.
- **Strict Separation of Revision Feedback vs Demographic Reporting**:
  - If the Auditor finds **operational or evidentiary defects** (e.g., two stop catchments overlap by $>20\%$ or $<5.0\text{ km}$ separation, a rationale claims NSSP COVID/flu trends are tract-level, straight-line distance is misrepresented as travel time, or a stop is claimed as "confirmed/booked"):
    - On `revision_number == 0`, it sets `verdict = AuditVerdict.REJECTED_REVISION_REQUIRED`, `session.state["revision_required"] = True`, and writes **only `NonDemographicAuditDefect` items** into `session.state["non_demographic_feedback"]`.
    - On `revision_number == 1` (after the max 1 allowed revision), if defects remain unresolved, it sets `verdict = AuditVerdict.NEEDS_HUMAN_REVIEW` and `session.state["revision_required"] = False` (terminating the `LoopAgent`).
  - **Demographic findings NEVER trigger an automated Planner re-optimization target**: Any post-hoc demographic disparity (`parity_ratio < 0.80` for an underserved group) is recorded in `AuditReport.demographic_impact` and sets `requires_human_equity_review = True` for human public-health leadership review, **without feeding race/ethnicity targets back to the Planner**.

---

## 2. File Ownership (Strict Isolation for Parallel Builds)

This plan owns **only** the following files:
```text
/Users/dvt112/Downloads/A4I/
├── carebridge/
│   └── agents/
│       └── auditor_agent/
│           ├── __init__.py
│           ├── prompts.py
│           ├── tools.py
│           └── agent.py
└── tests/
    └── test_07_auditor_agent.py
```

---

## 3. Step-by-Step Implementation Specification

### Step 3.1: Adversarial System Prompt (`carebridge/agents/auditor_agent/prompts.py`)

Note how this prompt intentionally conflicts with the Planner and Communicator prompts (`c5_01_load_explore.ipynb` Section 13 Rule 1 & Rule 3: *"skeptical, adversarial, cite-or-reject"*):

```python
AUDITOR_AGENT_INSTRUCTION = """You are the CareBridge AI Independent Equity & Rigor Auditor.
Your posture is SKEPTICAL, ADVERSARIAL, and RIGOROUS. You NEVER rubber-stamp the Siting Planner Agent's `draft_plan`,
and you are forbidden from rewriting the stops yourself.

Inputs from session.state:
- draft_plan: {draft_plan?}
- evidence_report: {evidence_report?}

MANDATORY AUDIT PROTOCOL:
1. Call `execute_independent_plan_audit` to deterministically verify:
   a) Geographic & Catchment Overlap: Do any two of the 4 stops have centres < 5.0 km apart or share > 20% of
      their covered tracts?
   b) Evidentiary, 4-Resolution & Directionality Rigor:
      - Does any stop rationale claim NSSP respiratory trends (`disease_weekly`) apply to a neighborhood/tract
        instead of the 4-county HSA, or rank tracts by 12km PM2.5 (`p90/p10=1.05x`)?
      - Does it claim straight-line upper-bound distance to federal sites is bus travel time?
      - Does it claim an unconfirmed venue is booked (`host_verified=True`)?
      - Did it invert `pct_checkup` (`100 - pct_checkup`) properly and avoid over-interpreting `<1-2%` CDC PLACES
        differences that fall within overlapping 95% confidence intervals?
      - Did it include `runner_up_tracts` explanations answering why high-need runner-up tracts (#5-#8) were deferred?
   c) Sensitivity Stability: Is `top_4_stability_jaccard < 0.50` under +/-15% weight perturbation?
   d) Post-Hoc Demographic Impact (PROTECTED ACCESS BOUNDARY): Query `external_demographic_audit` and compare
      the population-weighted demographic distribution and SVI Theme 3 mean of the 4 selected catchments
      against the county-wide baseline.
2. DECISION & BOUNDED FEEDBACK RULES:
   - If non-demographic defects exist AND `draft_plan.revision_number == 0`:
     Set `verdict = "rejected_revision_required"`. Populate `non_demographic_defects` with explicit remediation
     instructions. NEVER include demographic numbers or race/ethnicity targets in `non_demographic_defects`.
   - If non-demographic defects remain AND `draft_plan.revision_number >= 1`:
     Set `verdict = "needs_human_review"` (max 1 revision reached).
   - If zero non-demographic defects exist:
     Set `verdict = "approved"` (or `"needs_human_review"` if post-hoc demographic parity requires human sign-off).
3. Always attach explicit methodological limitations (`limitations_attached`) to the final `AuditReport`.
"""
```

---

### Step 3.2: Protected Audit Tool & Post-Hoc Demographic Comparator (`carebridge/agents/auditor_agent/tools.py`)

Implement `execute_independent_plan_audit(tool_context: ToolContext) -> dict`:
1. **Caller Permission Check**: Verifies `tool_context.agent_name == "equity_rigor_auditor"`. If any other agent attempts to invoke this tool, raises `PolicyViolationError("Unauthorized access to protected demographic audit boundary")`.
2. **Non-Demographic Defect Checks**:
   - Checks pairwise Haversine distances and `covered_tract_geoids` overlap across the 4 stops in `draft_plan`.
   - Scans `plain_language_rationale` and `evidence_citations` for grain violations (e.g., claiming COVID/flu/RSV is rising in a tract without mentioning the HSA) or claiming a site is booked.
3. **Post-Hoc Aggregate Demographic Lookup**:
   - Queries `mcp_query_posthoc_demographic_audit` (or `fulton_fixtures.DEMOGRAPHIC_AUDIT_FIXTURES`) for all tracts in the county.
   - Computes county-wide population-weighted percentages (`pct_black`, `pct_hispanic`, `pct_white`, `pct_asian`, `pct_minority`, `county_svi_theme3_mean`) vs the 4-stop catchment population-weighted percentages (`catchment_svi_theme3_mean`, `parity_ratio`).
4. **Sanitized State Write**:
   - Writes full `AuditReport` to `tool_context.state["audit_report"]`.
   - Writes boolean `revision_required` to `tool_context.state["revision_required"]`.
   - Writes **ONLY** `[d.model_dump() for d in audit_report.non_demographic_defects]` to `tool_context.state["non_demographic_feedback"]`, ensuring `assert_race_blind_planner_input(tool_context.state["non_demographic_feedback"])` passes 100% of the time!

---

### Step 3.3: ADK `LlmAgent` Definition (`carebridge/agents/auditor_agent/agent.py`)

```python
from google.adk.agents import LlmAgent
from google.adk.tools import FunctionTool
from google.genai import types

from carebridge.config import get_settings
from carebridge.contracts.state_keys import STATE_AUDIT_REPORT
from carebridge.contracts.audit_models import AuditReport
from carebridge.security.model_armor import default_vertex_safety_settings
from carebridge.agents.auditor_agent.prompts import AUDITOR_AGENT_INSTRUCTION
from carebridge.agents.auditor_agent.tools import execute_independent_plan_audit


def build_equity_rigor_auditor_agent() -> LlmAgent:
    settings = get_settings()
    return LlmAgent(
        name="equity_rigor_auditor",
        model=settings.gemini_model_reasoning,
        description=(
            "Independent Equity & Rigor Auditor: Challenges catchment overlap, grain errors, and sensitivity, "
            "and performs post-hoc demographic impact analysis inside a protected permission boundary."
        ),
        instruction=AUDITOR_AGENT_INSTRUCTION,
        tools=[FunctionTool(func=execute_independent_plan_audit)],
        output_key=STATE_AUDIT_REPORT,
        output_schema=AuditReport,
        generate_content_config=types.GenerateContentConfig(
            temperature=0.0,
            safety_settings=default_vertex_safety_settings(),
        ),
    )
```

---

## 4. Security, Guardrails & Telemetry

- **Strict Access Boundary (OWASP LLM06)**: `execute_independent_plan_audit` verifies `tool_context.agent_name == "equity_rigor_auditor"`.
- **One-Way Demographic Diode**: `non_demographic_feedback` written to `session.state` is validated by `assert_race_blind_planner_input` before returning, guaranteeing the Planner never receives protected-class optimization targets during a revision.
- **Telemetry**: Emits OpenTelemetry span `agent.auditor.evaluate` with `revision_audited`, `verdict`, `defects_count`, `catchment_svi_theme3_mean`, and `county_svi_theme3_mean`.

---

## 5. Verification & Unit Tests (`tests/test_07_auditor_agent.py`)

Run standalone:
```bash
pytest tests/test_07_auditor_agent.py -v
```
Tests must verify:
1. **Rejection Path (`revision_audited == 0`)**: Given a `DraftPlan` where Stop 1 and Stop 2 overlap (`< 5.0 km`), the Auditor sets `verdict == AuditVerdict.REJECTED_REVISION_REQUIRED`, `session.state["revision_required"] is True`, and populates `session.state["non_demographic_feedback"]` with a `CATCHMENT_OVERLAP` defect.
2. **Demographic Diode Check**: `session.state["non_demographic_feedback"]` passes `assert_race_blind_planner_input()` while `session.state["audit_report"]["demographic_impact"]` contains the full Fulton County post-hoc demographic comparison.
3. **Approval Path**: Given a valid 4-stop `DraftPlan` with distinct catchments and proper grain citations, the Auditor sets `verdict == AuditVerdict.APPROVED` and `session.state["revision_required"] is False`.
4. **Bounded Loop Cap (`revision_audited == 1`)**: If a defect still exists on `revision_number == 1`, the Auditor sets `verdict == AuditVerdict.NEEDS_HUMAN_REVIEW` and `session.state["revision_required"] is False` (preventing a second revision).
5. **Permission Boundary**: Calling `execute_independent_plan_audit` with `agent_name="siting_planner_agent"` raises `PolicyViolationError`.

---

## 6. Antigravity Execution Prompt

> **Copy-paste into Antigravity to execute Plan 07:**
> "Execute `/Users/dvt112/Downloads/A4I/plans/07_equity_rigor_auditor_agent.md`. Create `carebridge/agents/auditor_agent/` (`__init__.py`, `prompts.py`, `tools.py`, `agent.py`) and `tests/test_07_auditor_agent.py`. Run `pytest tests/test_07_auditor_agent.py -v` and verify all tests pass."
