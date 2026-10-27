# Plan 09 — Coordinator Agent, ADK Workflow Orchestration & `adk web` Entrypoint

> **Component Role**: Implements the **Coordinator Agent** (`data-node="coordinator"`) in Section 02 (Agent Graph) of the CareBridge AI architecture diagram.
> **ADK Primitives**:
> - `ParallelAgent` (`evidence_collection_parallel`) running `health_access_agent` and `transit_community_agent` concurrently.
> - Sequential `evidence_validator_agent` gate after the parallel fan-out.
> - `LoopAgent` (`plan_audit_loop`, `max_iterations=2`) orchestrating `siting_planner_agent` $\rightleftarrows$ `equity_rigor_auditor` with a deterministic exit condition (`AuditLoopExitChecker` escalating when `revision_required == False`).
> - `SequentialAgent` / `Workflow` (`carebridge_coordinator_workflow`, `timeout=120.0`) chaining the full pipeline and assembling `final_plan` + `PlanResponse`.
> - Exposes `root_agent` in `agent/agent.py` so `adk web` and `adk run` work out-of-the-box as required by `c5_01_load_explore.ipynb` Section 13.

---

## 1. Executive Summary & Architectural Purpose

From the CareBridge AI architecture diagram and `c5_01_load_explore.ipynb` Section 13:
- **Responsibility**: *"Normalizes county, four Saturdays and siting strategy; enforces execution order, bounded revision loop and final human-review status. Orchestrates parallel evidence gathering, sequential planning, independent auditing and communication output. Caps automatic plan revision at one retry and marks all recommendations provisional until site operations are confirmed."*
- **Three-Stage Scoped `session.state` Topology**:
  1. **Stage 1 — Parallel Evidence Fan-Out (`ParallelAgent`)**:
     - Branch A (`health_access_agent`) $\rightarrow$ `session.state["health_evidence"]`
     - Branch B (`transit_community_agent`) $\rightarrow$ `session.state["mobility_evidence"]`
     - Zero shared output keys during parallel execution.
  2. **Stage 2 — Sequential Data-Quality & 4-Resolution Gate**:
     - `evidence_validator_agent` reads `health_evidence` + `mobility_evidence` $\rightarrow$ writes `session.state["evidence_report"]`.
  3. **Stage 3 — Bounded Plan $\rightleftarrows$ Audit Loop (`LoopAgent(max_iterations=2)`)**:
     - `siting_planner_agent` reads race-blind state (`plan_request`, `health_evidence`, `mobility_evidence`, `evidence_report`, `non_demographic_feedback`) $\rightarrow$ writes `session.state["draft_plan"]` (including `runner_up_tracts`) and appends to `session.state["revision_history"]`.
     - `equity_rigor_auditor` reads `draft_plan` + protected `external_demographic_audit` $\rightarrow$ writes `session.state["audit_report"]`, `session.state["revision_required"]`, and sanitized `session.state["non_demographic_feedback"]`.
     - `audit_loop_exit_gate` (`BaseAgent`): Checks `if not session.state.get("revision_required", False)` (or if `evidence_report.core_tables_ready == False`), promotes `draft_plan` $\rightarrow$ `session.state["final_plan"]`, and yields `Event(actions=EventActions(escalate=True))` to exit the loop cleanly.
  4. **Stage 4 — Grounded Bilingual Community Communications**:
     - `community_communications_agent` reads `final_plan` (stops + `runner_up_tracts`) + `audit_report` $\rightarrow$ writes `session.state["outreach_messages"]` (including `unpicked_neighborhood_explanations`).

---

## 2. File Ownership (Strict Isolation for Parallel Builds)

This plan owns **only** the following files:
```text
/Users/dvt112/Downloads/A4I/
├── agent/
│   ├── __init__.py
│   └── agent.py
├── carebridge/
│   └── agents/
│       └── coordinator/
│           ├── __init__.py
│           ├── exit_gate.py
│           ├── workflow.py
│           └── runner.py
└── tests/
    └── test_09_coordinator_workflow.py
```

---

## 3. Step-by-Step Implementation Specification

### Step 3.1: Deterministic Loop Exit & Final-Plan Promotion Gate (`carebridge/agents/coordinator/exit_gate.py`)

Implement `AuditLoopExitGate(BaseAgent)`:
- Runs as the 3rd sub-agent inside `LoopAgent(name="plan_audit_loop", max_iterations=2, sub_agents=[planner, auditor, exit_gate])`.
- Inspects `ctx.session.state`:
  - If `not ctx.session.state.get("revision_required", False)` or `revision_number >= 1`:
    - Copies `ctx.session.state["draft_plan"]` to `ctx.session.state["final_plan"]`.
    - Computes top-level `needs_human_review`: `True` if `audit_report.verdict == "needs_human_review"` or `audit_report.demographic_impact.requires_human_equity_review` or `draft_plan.status != "ok"`.
    - Yields `Event(author=self.name, actions=EventActions(escalate=True))` to terminate `LoopAgent`.
  - Otherwise (when `revision_required == True` on `revision_number == 0`):
    - Increments `ctx.session.state["current_revision_number"] = 1` and yields `Event(author=self.name, actions=EventActions(escalate=False))` so `LoopAgent` executes Iteration 2 (`revision_number = 1`).

---

### Step 3.2: Coordinator ADK Workflow Graph (`carebridge/agents/coordinator/workflow.py`)

```python
from google.adk.agents import ParallelAgent, SequentialAgent, LoopAgent

from carebridge.agents.health_agent.agent import build_health_access_agent
from carebridge.agents.mobility_agent.agent import build_transit_community_agent
from carebridge.agents.validator_agent.agent import build_evidence_validator_agent
from carebridge.agents.planner_agent.agent import build_siting_planner_agent
from carebridge.agents.auditor_agent.agent import build_equity_rigor_auditor_agent
from carebridge.agents.communicator_agent.agent import build_community_communications_agent
from carebridge.agents.coordinator.exit_gate import AuditLoopExitGate


def build_carebridge_coordinator_workflow() -> SequentialAgent:
    evidence_parallel = ParallelAgent(
        name="evidence_collection_parallel",
        description="Lane 01 parallel fan-out: Health & Access Agent (A) + Transit & Community Agent (B).",
        sub_agents=[
            build_health_access_agent(),
            build_transit_community_agent(),
        ],
    )

    validator_gate = build_evidence_validator_agent()

    plan_audit_loop = LoopAgent(
        name="plan_audit_loop",
        description="Bounded Planner <-> Independent Auditor challenge loop (max 1 revision = 2 iterations).",
        max_iterations=2,
        sub_agents=[
            build_siting_planner_agent(),
            build_equity_rigor_auditor_agent(),
            AuditLoopExitGate(name="audit_loop_exit_gate"),
        ],
    )

    communicator = build_community_communications_agent()

    return SequentialAgent(
        name="carebridge_coordinator",
        description=(
            "CareBridge AI Track 1 Coordinator: Orchestrates parallel evidence gathering, "
            "4-resolution validation gate, race-blind planning, post-hoc equity auditing, "
            "and bilingual community outreach generation."
        ),
        sub_agents=[
            evidence_parallel,
            validator_gate,
            plan_audit_loop,
            communicator,
        ],
    )
```

---

### Step 3.3: Programmatic Runner & `PlanResponse` Assembler (`carebridge/agents/coordinator/runner.py`)

Implement `async def execute_carebridge_plan(request: PlanRequest) -> PlanResponse`:
- Initializes an `InMemorySessionService` session with `state={"plan_request": request.model_dump(), "revision_history": []}`.
- Runs the Coordinator workflow (supporting deterministic tool-direct execution in offline test mode or full `Runner` execution with Gemini).
- Assembles and validates `PlanResponse`, populating:
  - `final_plan` (with `stops` and `runner_up_tracts`)
  - `audit_report` (with `non_demographic_defects` and `demographic_impact`)
  - `revision_history` (showing Draft 0 and Draft 1 when a revision occurred)
  - `evidence_report`
  - `outreach` (with `stop_notices` and `unpicked_neighborhood_explanations`)
  - `provenance`, `limitations`, `data_availability`, and `telemetry_summary`.

---

### Step 3.4: ADK Web / CLI Entrypoint (`agent/agent.py`)

Per `c5_01_load_explore.ipynb` Section 13, `adk web` expects `agent/agent.py` exposing `root_agent`:
```python
from carebridge.agents.coordinator.workflow import build_carebridge_coordinator_workflow

root_agent = build_carebridge_coordinator_workflow()
```

---

## 4. Verification & Unit Tests (`tests/test_09_coordinator_workflow.py`)

Run standalone:
```bash
pytest tests/test_09_coordinator_workflow.py -v
```
Tests must verify:
1. **Standard Path (`simulate_first_draft_defect=False`)**: Runs all 4 stages in sequence, approves on Iteration 0 (`len(response.revision_history) == 1`), populates 4 stops + `runner_up_tracts` + bilingual `outreach` + `unpicked_neighborhood_explanations`.
2. **Adversarial Revision Path (`simulate_first_draft_defect=True`)**: Draft 0 has overlapping catchments, Auditor rejects Draft 0 with `non_demographic_feedback` (`CATCHMENT_OVERLAP`), `AuditLoopExitGate` triggers Iteration 1, Planner resolves the overlap in Draft 1, Auditor approves Draft 1, and `len(response.revision_history) == 2`.
3. **Scoped State Verification**: `assert_race_blind_planner_input` passes on all Planner-visible state keys (`plan_request`, `health_evidence`, `mobility_evidence`, `evidence_report`, `non_demographic_feedback`, `draft_plan`), while `audit_report.demographic_impact` contains the post-hoc Fulton County demographic parity comparison.
4. **`agent/agent.py` Export**: `from agent.agent import root_agent` succeeds and exposes the 4-stage workflow.

---

## 5. Antigravity Execution Prompt

> **Copy-paste into Antigravity to execute Plan 09:**
> "Execute `/Users/dvt112/Downloads/A4I/plans/09_coordinator_agent_and_adk_workflow.md`. Create `carebridge/agents/coordinator/` (`__init__.py`, `exit_gate.py`, `workflow.py`, `runner.py`), `agent/` (`__init__.py`, `agent.py`), and `tests/test_09_coordinator_workflow.py`. Run `pytest tests/test_09_coordinator_workflow.py -v` and confirm all tests pass."
