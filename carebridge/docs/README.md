# CareBridge Fulton — End-to-End Testing & Challenge 5 Compliance Documentation

This directory ([`carebridge/docs/`](file:///Users/dvt112/Downloads/A4I/carebridge/docs/)) contains the complete end-to-end (E2E) test specification, requirement traceability matrix, multi-agent architectural guarantees, and local verification results for **CareBridge Fulton** against the **Agents for Impact (A4I) 2026 Challenge 5 — Public Health** specification (`https://github.com/haggman/A4I2026-challenge-5-public-health` and [`c5_01_load_explore.ipynb`](file:///Users/dvt112/Downloads/A4I/c5_01_load_explore.ipynb)).

---

## Documentation Index

| Document | Purpose & Scope |
| :--- | :--- |
| **[`challenge_5_test_cases.md`](file:///Users/dvt112/Downloads/A4I/carebridge/docs/challenge_5_test_cases.md)** | Full specification of all Challenge 5 test cases mapped to *"What you're building"*, *"Questions that need more than we gave you"*, *"Three Tracks, One Architecture"*, *"The four questions judges look for"*, and the 10 deliberate data exclusions. |
| **[`test_execution_tracker.md`](file:///Users/dvt112/Downloads/A4I/carebridge/docs/test_execution_tracker.md)** | Step-by-step E2E test execution tracker (`TC-01` through `TC-12`) recording execution status, timestamps, durations, and empirical test metrics. |
| **[`e2e_verification_report.md`](file:///Users/dvt112/Downloads/A4I/carebridge/docs/e2e_verification_report.md)** | Local end-to-end test execution report (**76 tests across 11 suites, 100% passing**), walkthrough of the 3 siting strategies, standard vs. adversarial revision trajectories (`Draft 0` $\rightarrow$ `Draft 1`), and graceful degradation results. |
| **[`multi_agent_architecture_guarantees.md`](file:///Users/dvt112/Downloads/A4I/carebridge/docs/multi_agent_architecture_guarantees.md)** | Reference on the 6-agent ADK topology (`ParallelAgent` $\rightarrow$ `Validator` $\rightarrow$ `LoopAgent(max_iterations=2)` $\rightarrow$ `Communicator`), the **One-Way Demographic Diode**, the 4 spatial resolutions, and formal answers to the 4 Judge Questions. |

---

## Quick Start: Running End-to-End Tests Locally

All unit, integration, and end-to-end Challenge 5 compliance tests run deterministically offline in under 3 seconds using Python's built-in `unittest` runner:

```bash
# Run the complete 76-test suite (Plans 00-09 + Plan 11 E2E Challenge 5 Compliance)
python3 -m unittest discover -s tests -p "test_*.py" -v

# Run only the Challenge 5 End-to-End Compliance Suite (12 comprehensive E2E scenarios)
python3 -m unittest tests/test_11_e2e_challenge_compliance.py -v

# Run the Coordinator Multi-Agent Workflow Suite (Plan 09)
python3 -m unittest tests/test_09_coordinator_workflow.py -v
```

---

## End-to-End Multi-Agent Architecture Overview

```mermaid
flowchart TD
    Req["PlanRequest (county_fips='13121', strategy, saturdays)"] --> Coord["SequentialAgent: carebridge_coordinator"]

    subgraph Stage1["Stage 1: Parallel Evidence Fan-Out (ParallelAgent)"]
        AgentA["Health & Access Agent (Agent A)<br/>output_key: health_evidence"]
        AgentB["Transit & Community Agent (Agent B)<br/>output_key: mobility_evidence"]
    end

    Coord --> Stage1
    AgentA --> Val["Stage 2: Evidence Validator Agent<br/>check() vs note() + 4 Spatial Resolutions<br/>output_key: evidence_report"]
    AgentB --> Val

    subgraph Stage3["Stage 3: Bounded Plan-Audit Loop (LoopAgent, max_iterations=2)"]
        Planner["Track 1: Siting Planner Agent (100% Race-Blind)<br/>Tool: optimize_four_clinic_stops<br/>output_key: draft_plan"]
        Auditor["Track 2: Equity & Rigor Auditor Agent<br/>Protected Tool: execute_independent_plan_audit<br/>output_key: audit_report"]
        Gate["AuditLoopExitGate<br/>Promotes final_plan or triggers 1 revision"]
        Planner --> Auditor --> Gate
        Gate -- "non_demographic_feedback ONLY<br/>(One-Way Demographic Diode)" --> Planner
    end

    Val --> Stage3
    Gate -- "escalate=True (Approved or Cap Reached)" --> Comm["Stage 4 / Track 3: Community Communications Agent<br/>6th-Grade EN/ES Flyers + Question 7 Runner-Up Explanations<br/>output_key: outreach_messages"]
    Comm --> Resp["PlanResponse (4-Part Clinic Plan Deliverable)"]
```
