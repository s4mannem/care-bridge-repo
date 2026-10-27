# CareBridge AI — Implementation Plans Index (`00`–`11`)

This directory contains the complete, gap-free implementation plans for **CareBridge AI (Track 1: Resource & Siting Advisor backed by Track 2 Equity Auditor & Track 3 Bilingual Explanation Agent)**, aligned with [`/Users/dvt112/Downloads/A4I/architecture_diagram.html`](file:///Users/dvt112/Downloads/A4I/architecture_diagram.html).

## Architectural Highlights & Gap Coverage
1. **Three Tracks, One Architecture (3 Pointers)**:
   - **Siting Planner (`Plan 06`) + Deterministic Optimizer (`Plan 05`)**: Race-blind inputs only; analytical, cited, resolution-qualified rationale for the outreach lead.
   - **Independent Equity & Rigor Auditor (`Plan 07`)**: Isolated permission boundary with exclusive post-hoc access to `external_demographic_audit`; challenges catchment overlap, spatial grain violations, and PLACES 95% CI over-claims; sends only sanitized `non_demographic_feedback` back to the Planner (max 1 revision).
   - **Community Communications Agent (`Plan 08`)**: Intentionally contrasting prompt posture—warm, 6th-grade reading level English & Spanish bus-stop flyers + empathetic explanations for runner-up neighborhoods (`unpicked_neighborhood_explanations`), with zero statistical hedging and zero invented bookings.
2. **"What You're Building" (All 7 Outreach Lead Questions)**:
   - Explicitly inverts routine checkup (`pct_checkup_gap = 100.0 - pct_checkup`) so low preventive checkup rate increases need score.
   - Explicitly answers **Question 7** (*"How do I tell the neighborhood we didn't pick why we didn't pick them?"*) via deterministic `runner_up_tracts` (`#5`–`#8`) in `DraftPlan` and bilingual `unpicked_neighborhood_explanations` in `OutreachMessages`.
3. **"Questions That Need More Than We Gave You" (All 7 Edge Questions & 4 Spatial Resolutions)**:
   - Sequential **Evidence Validator Agent (`Plan 04`)** runs *after* the 2-branch parallel MCP fan-out (`Plan 02` + `Plan 03`) and enforces all 4 spatial resolutions (`11-char Tract`, `12km PM2.5 Grid`, `Facility Point`, `4-County HSA`) plus upper-bound federal facility distances, HRSA `TOT_OPER_HR_PER_WEEK` operating hours, PLACES 95% CIs, and PII/licensing exclusions (`FQHC_ADMIN_CONTACT_*`, NPPES, unlicensed mobile clinics, CC BY-NC transit matrices).

---

## Execution Order

| Plan | File | Scope & Owned Module | Test Command |
| :--- | :--- | :--- | :--- |
| **Plan 00** *(Prerequisite)* | [`00_foundation_contracts_security_telemetry.md`](file:///Users/dvt112/Downloads/A4I/plans/00_foundation_contracts_security_telemetry.md) | Pydantic contracts (`evidence_models`, `plan_models`, `audit_models`, `outreach_models`, `api_models`), `state_keys`, `race_blind_guard`, `model_armor`, `owasp_guardrails`, OpenTelemetry, `fulton_fixtures` | `pytest tests/test_00_foundation.py -v` |
| **Plan 01** | [`01_bigquery_data_plane_and_mcp.md`](file:///Users/dvt112/Downloads/A4I/plans/01_bigquery_data_plane_and_mcp.md) | BigQuery SQL views (`01_marta_gtfs_views.sql`, `02_optional_enrichments.sql`, `03_demographic_audit_table.sql`), `mcp_tools.yaml`, `bq_mcp_client.py` | `pytest tests/test_01_bigquery_mcp.py -v` |
| **Plan 02** | [`02_health_access_evidence_agent.md`](file:///Users/dvt112/Downloads/A4I/plans/02_health_access_evidence_agent.md) | `carebridge/agents/health_agent/` (Evidence Agent A · MCP, `100 - pct_checkup`, 95% CIs, `TOT_OPER_HR_PER_WEEK`, HPSA area vs facility, 4-county HSA) | `pytest tests/test_02_health_agent.py -v` |
| **Plan 03** | [`03_transit_community_evidence_agent.md`](file:///Users/dvt112/Downloads/A4I/plans/03_transit_community_evidence_agent.md) | `carebridge/agents/mobility_agent/` (Evidence Agent B · MCP, MARTA Saturday GTFS, IMLS libraries, USDA food access, graceful degradation) | `pytest tests/test_03_mobility_agent.py -v` |
| **Plan 04** | [`04_evidence_validator_agent.md`](file:///Users/dvt112/Downloads/A4I/plans/04_evidence_validator_agent.md) | `carebridge/agents/validator_agent/` (Sequential gate after parallel fan-out; `check()` vs `note()`, 4 spatial resolutions, 7 edge caveats) | `pytest tests/test_04_validator_agent.py -v` |
| **Plan 05** | [`05_four_stop_coverage_optimizer_tool.md`](file:///Users/dvt112/Downloads/A4I/plans/05_four_stop_coverage_optimizer_tool.md) | `carebridge/tools/optimizer/` (Deterministic scoring with `checkup_preventive_gap_norm`, 4-stop greedy max-coverage, `runner_up_tracts` #5–#8, $\pm 15\%$ sensitivity) | `pytest tests/test_05_optimizer_tool.py -v` |
| **Plan 06** | [`06_siting_planner_agent.md`](file:///Users/dvt112/Downloads/A4I/plans/06_siting_planner_agent.md) | `carebridge/agents/planner_agent/` (Race-blind Planner, analytical/cited rationale, `runner_up_tracts` technical deferral rationales, revision history) | `pytest tests/test_06_planner_agent.py -v` |
| **Plan 07** | [`07_equity_rigor_auditor_agent.md`](file:///Users/dvt112/Downloads/A4I/plans/07_equity_rigor_auditor_agent.md) | `carebridge/agents/auditor_agent/` (Adversarial Auditor, protected `external_demographic_audit` lookup, sanitized `non_demographic_feedback` diode) | `pytest tests/test_07_auditor_agent.py -v` |
| **Plan 08** | [`08_community_communications_agent.md`](file:///Users/dvt112/Downloads/A4I/plans/08_community_communications_agent.md) | `carebridge/agents/communicator_agent/` (Warm 6th-grade EN/ES bus-stop flyers + `unpicked_neighborhood_explanations`, no invented bookings) | `pytest tests/test_08_communicator_agent.py -v` |
| **Plan 09** | [`09_coordinator_agent_and_adk_workflow.md`](file:///Users/dvt112/Downloads/A4I/plans/09_coordinator_agent_and_adk_workflow.md) | `carebridge/agents/coordinator/` & `agent/agent.py` (`ParallelAgent` $\rightarrow$ Validator $\rightarrow$ `LoopAgent(max_iterations=2)` $\rightarrow$ Communicator) | `pytest tests/test_09_coordinator_workflow.py -v` |
| **Plan 10** | [`10_fastapi_gateway_and_cloud_run.md`](file:///Users/dvt112/Downloads/A4I/plans/10_fastapi_gateway_and_cloud_run.md) | `carebridge/api/`, `Dockerfile`, `deploy_cloud_run.sh` (`POST /v1/plan`, `/healthz`, `/readyz`, `/v1/tracts/{county_fips}`) | `pytest tests/test_10_fastapi_gateway.py -v` |
| **Plan 11** | [`11_operations_ui_and_e2e_verification.md`](file:///Users/dvt112/Downloads/A4I/plans/11_operations_ui_and_e2e_verification.md) | `carebridge/ui/static/` (Interactive 4-part Clinic Plan UI) & `tests/test_11_e2e_challenge_compliance.py` | `pytest -v` |
