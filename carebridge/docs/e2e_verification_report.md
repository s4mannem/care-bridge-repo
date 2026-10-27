# CareBridge Fulton — End-to-End Local Verification Report

**Execution Date**: October 27, 2026  
**Target County**: Fulton County, GA (`county_fips="13121"`)  
**Test Command**: `python3 -m unittest discover -s tests -p "test_*.py" -v`  
**Overall Result**: **76 tests executed in 2.000s — 100% PASS (`OK`, `skipped=1` live cloud BigQuery credential check)**

---

## 1. Test Suite Execution Summary

| Test Module | Plan / Scope | Tests Run | Status | Key Verification Focus |
| :--- | :--- | :---: | :---: | :--- |
| [`tests/test_00_contracts_and_security.py`](file:///Users/dvt112/Downloads/A4I/tests/test_00_contracts_and_security.py) *(+ `test_00_foundation.py`)* | **Plan 00**: Contracts, Security, Telemetry & Fixtures | 14 | **PASS** | Pydantic roundtrips, `pct_checkup` inversion, `assert_race_blind_planner_input`, `assert_no_pii_in_payload`, `ModelArmorScreener`, `CareBridgeTelemetryPlugin` |
| [`tests/test_01_bigquery_mcp.py`](file:///Users/dvt112/Downloads/A4I/tests/test_01_bigquery_mcp.py) | **Plan 01**: BigQuery Data Plane & MCP Toolset Boundary | 5 | **PASS** | SQLi rejection, 100 MB query cap, physical toolset isolation (`mcp_query_posthoc_demographic_audit` excluded from evidence toolsets), `NotFound` fallback |
| [`tests/test_02_health_agent.py`](file:///Users/dvt112/Downloads/A4I/tests/test_02_health_agent.py) | **Plan 02**: Health & Access Evidence Agent (Agent A) | 5 | **PASS** | `pct_checkup_gap = 100 - pct_checkup`, Fulton `0/99` HPSA nuance, 4-county HSA grain, NSSP `NULL` $\rightarrow$ `data_unavailable=True`, ADK `InMemoryRunner` |
| [`tests/test_03_mobility_agent.py`](file:///Users/dvt112/Downloads/A4I/tests/test_03_mobility_agent.py) | **Plan 03**: Transit & Community Evidence Agent (Agent B) | 5 | **PASS** | Saturday MARTA GTFS headways, IMLS library venues, `host_permission_verified=False` enforcement, isolated `mobility_evidence` state key |
| [`tests/test_04_validator_agent.py`](file:///Users/dvt112/Downloads/A4I/tests/test_04_validator_agent.py) | **Plan 04**: Evidence Validator Agent | 7 | **PASS** | 8 fatal `check()` rules (11-char GEOID, county prefix, duplicate check, checkup inversion) vs non-fatal `note()` publisher warnings |
| [`tests/test_05_optimizer_tool.py`](file:///Users/dvt112/Downloads/A4I/tests/test_05_optimizer_tool.py) | **Plan 05**: Four-Stop Coverage Optimizer Tool | 7 | **PASS** | Deterministic 4-stop selection, pairwise Haversine $\ge 5.0\text{ km}$, Question 7 `runner_up_tracts` (`#5`–`#8`), $\pm 15\%$ weight perturbation sensitivity |
| [`tests/test_06_planner_agent.py`](file:///Users/dvt112/Downloads/A4I/tests/test_06_planner_agent.py) | **Plan 06**: Siting Planner Agent (Track 1) | 7 | **PASS** | `planner_race_blind_before_model_callback`, `insufficient_candidates` gate, `Draft 0` $\rightarrow$ `Draft 1` overlap repair |
| [`tests/test_07_auditor_agent.py`](file:///Users/dvt112/Downloads/A4I/tests/test_07_auditor_agent.py) | **Plan 07**: Equity & Rigor Auditor Agent (Track 2) | 5 | **PASS** | Rejects $< 5.0\text{ km}$ overlap & grain overclaims, certifies One-Way Demographic Diode, approves `Draft 1`, escalates at revision cap |
| [`tests/test_08_communicator_agent.py`](file:///Users/dvt112/Downloads/A4I/tests/test_08_communicator_agent.py) | **Plan 08**: Community Communications Agent (Track 3) | 5 | **PASS** | 4 bilingual EN/ES bus-stop flyers, Question 7 runner-up explanations, 4-county HSA notes, blocks `"confirmed and booked"` claims |
| [`tests/test_09_cloud_bigquery_integration.py`](file:///Users/dvt112/Downloads/A4I/tests/test_09_cloud_bigquery_integration.py) | **Plan 09**: Cloud BigQuery View Integration | 3 | **PASS** *(1 skipped)* | Verifies all 9 SQL view queries (`v_burden_tracts` .. `v_external_demographic_audit`) and simulated `bigquery.Client` execution |
| [`tests/test_09_coordinator_workflow.py`](file:///Users/dvt112/Downloads/A4I/tests/test_09_coordinator_workflow.py) | **Plan 09**: Root Coordinator & ADK Workflow Graph | 5 | **PASS** | `SequentialAgent` $\rightarrow$ `ParallelAgent` $\rightarrow$ `Validator` $\rightarrow$ `LoopAgent(max_iterations=2)` $\rightarrow$ `Communicator`, `from agent.agent import root_agent` |
| [`tests/test_11_e2e_challenge_compliance.py`](file:///Users/dvt112/Downloads/A4I/tests/test_11_e2e_challenge_compliance.py) | **Plan 11**: End-to-End Challenge 5 Compliance Suite | 12 | **PASS** | Full E2E verification across all 3 strategies, 3 Tracks, 4 Judge Questions, 7 Outreach Questions, 4 Spatial Resolutions, Dark HSA, and 10 Exclusions |
| **TOTAL** | **All Plans (`00`–`11`)** | **76** | **100% PASS** | **0 Failures, 0 Errors** |

---

## 2. End-to-End Fulton County (`13121`) Siting Results

When executed on Fulton County (`13121`) under the default `balanced_uninsured_safety_net_gap` strategy, the CareBridge multi-agent workflow produces the following 4-stop Saturday rotation:

| Stop Rank | Assigned Saturday | Primary Tract GEOID | Provisional Host Venue | Key Structural Burden & Access Metrics |
| :---: | :---: | :---: | :--- | :--- |
| **Stop #1** | `2026-11-07` | `13121010514` *(South Fulton / Fairburn)* | South Fulton / Fairburn Public Library *(Provisional Host)* | `26.4%` uninsured (18–64), `32.2%` checkup gap, `18.5 km` to safety net (`13.7 km` uninsured penalty) |
| **Stop #2** | `2026-11-14` | `13121010214` *(Adamsville / West Atlanta)* | Adamsville-Collier Heights Branch Library *(Provisional Host)* | `24.2%` uninsured (18–64) vs `14.0%` all-ages (`10.2 pp` age-structure gap), `43.0%` zero-vehicle households, `8.1 km` to safety net |
| **Stop #3** | `2026-11-21` | `13121007602` *(Cleveland Ave / SW Atlanta)* | Cleveland Avenue Branch Library *(Provisional Host)* | `25.6%` uninsured (18–64), `30.8%` checkup gap, `28.4%` zero-vehicle households, `9.4 km` to safety net |
| **Stop #4** | `2026-11-28` | `13121011305` *(Southside / Hapeville)* | Hapeville / Southside Community Library *(Provisional Host)* | `23.5%` uninsured (18–64), `30.2%` checkup gap, `24.8%` zero-vehicle households, `11.2 km` to safety net |

### Question 7 Runner-Up Neighborhood Deferrals (`#5`–`#8`)
Every high-need neighborhood not assigned a dedicated van receives both an analytical deferral record (`RunnerUpTractExplanation`) for the outreach lead and an empathetic bilingual explanation (`UnpickedNeighborhoodExplanation`) for community partners:
- **Tract `13121007808` (Need Rank `#5`)**: Deferred (`catchment_already_covered`) because it sits `2.05 km` from **Stop #2** (`Adamsville-Collier Heights Branch Library`), well inside its `4.0 km` Saturday service catchment.
- **Tract `13121008201` (Need Rank `#6`)**: Deferred (`inter_stop_separation_constraint`) because it sits `4.59 km` from **Stop #2** (`< 5.0 km` minimum inter-stop separation buffer).
- **Tract `13121010305` (Need Rank `#7`)**: Deferred (`catchment_already_covered`) because it sits `3.72 km` from **Stop #1** (`South Fulton / Fairburn Public Library`).
- **Tract `13121011000` (Need Rank `#8`)**: Deferred (`lower_marginal_coverage`) and directed to the nearest selected stop (`Stop #3`, `5.36 km` away).

---

## 3. Adversarial Self-Correction Trajectory (`simulate_first_draft_defect=True`)

1. **Iteration 0 (`Draft 0`)**:
   - Siting Planner emits `Draft 0` where Stop #1 (`13121010514`) and Stop #2 (`13121010305`) are only `3.72 km` apart (`< 5.0 km` minimum separation).
   - Independent Equity & Rigor Auditor detects `DEFECT-OVERLAP-S1-S2` (`DefectCategory.CATCHMENT_OVERLAP`), sets `verdict = AuditVerdict.REJECTED_REVISION_REQUIRED`, and writes sanitized `non_demographic_feedback` into `session.state["non_demographic_feedback"]`.
   - `AuditLoopExitGate` sees `revision_required == True` on Iteration 0 and keeps the `LoopAgent` running (`escalate=False`).
2. **Iteration 1 (`Draft 1`)**:
   - Siting Planner reads `non_demographic_feedback` (without ever seeing `audit_report.demographic_impact`), excludes the overlapping candidate, and produces `Draft 1` where all 4 stops are $\ge 5.0\text{ km}$ apart.
   - Independent Equity & Rigor Auditor verifies zero operational/grain defects and confirms post-hoc demographic parity (`catchment_svi_theme3_mean = 0.897` vs `county_svi_theme3_mean = 0.752`, minority parity ratio `1.19x`), issuing `AuditVerdict.APPROVED`.
   - `AuditLoopExitGate` promotes `Draft 1` to `session.state["final_plan"]` and signals `EventActions(escalate=True)` so Stage 4 (`community_communications_agent`) generates the final bilingual EN/ES outreach package.
