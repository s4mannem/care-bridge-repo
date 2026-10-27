# A4I 2026 Challenge 5 — Public Health Test Case Specification

This document maps every requirement, outreach question, edge case, spatial grain boundary, data exclusion, and multi-agent guarantee from the **A4I 2026 Challenge 5 — Public Health** specification (`https://github.com/haggman/A4I2026-challenge-5-public-health` and [`c5_01_load_explore.ipynb`](file:///Users/dvt112/Downloads/A4I/c5_01_load_explore.ipynb)) to executable test cases in [`tests/test_11_e2e_challenge_compliance.py`](file:///Users/dvt112/Downloads/A4I/tests/test_11_e2e_challenge_compliance.py) and the modular unit suites ([`test_00` through `test_09`](file:///Users/dvt112/Downloads/A4I/tests/)).

---

## 1. Requirement-to-Test Traceability Matrix

| Challenge 5 README Section | Requirement / Edge Case | Primary E2E Test Case | Supporting Unit Tests |
| :--- | :--- | :--- | :--- |
| **What you're building** | **4-Part Clinic Plan Deliverable** across all 3 siting strategies (`balanced_uninsured_safety_net_gap`, `chronic_respiratory_focus`, `zero_vehicle_transit_priority`) with 4 Saturday stops separated by $\ge 5.0\text{ km}$ and $\pm 15\%$ weight perturbation sensitivity | [`test_01_e2e_all_three_siting_strategies_produce_4_stops_and_distinct_rationales`](file:///Users/dvt112/Downloads/A4I/tests/test_11_e2e_challenge_compliance.py#L97-L169) | [`test_05_optimizer_tool.py`](file:///Users/dvt112/Downloads/A4I/tests/test_05_optimizer_tool.py), [`test_06_planner_agent.py`](file:///Users/dvt112/Downloads/A4I/tests/test_06_planner_agent.py) |
| **What you're building** | **All 7 Outreach Lead Questions**:<br/>• Routine checkup inversion (`pct_checkup_gap = 100.0 - pct_checkup`)<br/>• Dual uninsured rates (`pct_uninsured_18_64` PLACES vs `pct_uninsured_all_ages` SVI & Medicare 65+ gap)<br/>• Dual distances (`km_to_any_care` vs `km_to_safety_net` & `extra_km_if_uninsured` up to `28.6 km`)<br/>• **Question 7**: Runner-up tracts (`#5`–`#8`) technical deferral codes + empathetic EN/ES explanations | [`test_07_what_youre_building_all_7_outreach_lead_questions`](file:///Users/dvt112/Downloads/A4I/tests/test_11_e2e_challenge_compliance.py#L388-L442) | [`test_02_health_agent.py`](file:///Users/dvt112/Downloads/A4I/tests/test_02_health_agent.py), [`test_05_optimizer_tool.py`](file:///Users/dvt112/Downloads/A4I/tests/test_05_optimizer_tool.py), [`test_08_communicator_agent.py`](file:///Users/dvt112/Downloads/A4I/tests/test_08_communicator_agent.py) |
| **Three Tracks, One Architecture** | **Track 1** (100% race-blind Planner + Optimizer), **Track 2** (Protected Post-Hoc Equity & Rigor Auditor), **Track 3** (Warm 6th-grade EN/ES Communicator), and the **One-Way Demographic Diode** | [`test_02_three_tracks_one_architecture_and_one_way_demographic_diode`](file:///Users/dvt112/Downloads/A4I/tests/test_11_e2e_challenge_compliance.py#L171-L216) | [`test_00_contracts_and_security.py`](file:///Users/dvt112/Downloads/A4I/tests/test_00_contracts_and_security.py), [`test_07_auditor_agent.py`](file:///Users/dvt112/Downloads/A4I/tests/test_07_auditor_agent.py), [`test_09_coordinator_workflow.py`](file:///Users/dvt112/Downloads/A4I/tests/test_09_coordinator_workflow.py) |
| **The 4 Questions Judges Look For** | **Judge Q1**: *"If I delete any one agent from your diagram, does the answer get worse?"* | [`test_03_judge_question_1_delete_any_agent_degrades_or_breaks_deliverable`](file:///Users/dvt112/Downloads/A4I/tests/test_11_e2e_challenge_compliance.py#L218-L282) | [`test_04_validator_agent.py`](file:///Users/dvt112/Downloads/A4I/tests/test_04_validator_agent.py), [`test_06_planner_agent.py`](file:///Users/dvt112/Downloads/A4I/tests/test_06_planner_agent.py) |
| **The 4 Questions Judges Look For** | **Judge Q2**: *"Show me a key in `session.state` that one agent writes and another agent reads."* | [`test_04_judge_question_2_session_state_handoff_chain_across_all_agents`](file:///Users/dvt112/Downloads/A4I/tests/test_11_e2e_challenge_compliance.py#L284-L324) | [`test_09_coordinator_workflow.py`](file:///Users/dvt112/Downloads/A4I/tests/test_09_coordinator_workflow.py) |
| **The 4 Questions Judges Look For** | **Judge Q3**: *"Show me two agents whose instructions genuinely conflict."* | [`test_05_judge_question_3_genuinely_conflicting_agent_instructions`](file:///Users/dvt112/Downloads/A4I/tests/test_11_e2e_challenge_compliance.py#L326-L355) | [`test_06_planner_agent.py`](file:///Users/dvt112/Downloads/A4I/tests/test_06_planner_agent.py), [`test_07_auditor_agent.py`](file:///Users/dvt112/Downloads/A4I/tests/test_07_auditor_agent.py), [`test_08_communicator_agent.py`](file:///Users/dvt112/Downloads/A4I/tests/test_08_communicator_agent.py) |
| **The 4 Questions Judges Look For** | **Judge Q4**: *"Show me a point where the system rejected its own first answer."* (`Draft 0` rejected for $< 5.0\text{ km}$ overlap $\rightarrow$ `Draft 1` remedies overlap $\ge 5.0\text{ km}$) | [`test_06_judge_question_4_self_rejection_and_bounded_revision_draft0_to_draft1`](file:///Users/dvt112/Downloads/A4I/tests/test_11_e2e_challenge_compliance.py#L357-L386) | [`test_07_auditor_agent.py`](file:///Users/dvt112/Downloads/A4I/tests/test_07_auditor_agent.py), [`test_09_coordinator_workflow.py`](file:///Users/dvt112/Downloads/A4I/tests/test_09_coordinator_workflow.py) |
| **Questions that need more than we gave you** | **4 Spatial Resolutions** (`census_tract_11char`, `epa_12km_grid_on_tract_id`, `facility_lon_lat_point`, `multi_county_health_service_area`) & blocking ecological fallacy overclaims | [`test_08_questions_that_need_more_4_spatial_resolutions_and_grain_enforcement`](file:///Users/dvt112/Downloads/A4I/tests/test_11_e2e_challenge_compliance.py#L444-L473) | [`test_04_validator_agent.py`](file:///Users/dvt112/Downloads/A4I/tests/test_04_validator_agent.py), [`test_07_auditor_agent.py`](file:///Users/dvt112/Downloads/A4I/tests/test_07_auditor_agent.py) |
| **Questions that need more than we gave you** | **HRSA HPSA Nuance & Two-Verdict Validation**: `shortage_areas_count=0` active in Fulton (`99 Proposed For Withdrawal`) vs `shortage_facilities_count=6`, and fatal `check()` vs warning `note()` | [`test_09_hpsa_shortage_areas_zero_active_vs_facilities_and_two_verdict_validation`](file:///Users/dvt112/Downloads/A4I/tests/test_11_e2e_challenge_compliance.py#L475-L494) | [`test_02_health_agent.py`](file:///Users/dvt112/Downloads/A4I/tests/test_02_health_agent.py), [`test_04_validator_agent.py`](file:///Users/dvt112/Downloads/A4I/tests/test_04_validator_agent.py) |
| **Questions that need more than we gave you** | **NSSP Dark HSA Trap** (e.g., Santa Clara CA / Bronx NY where `percent_visits_*` are `NULL`): sets `data_unavailable=True` and reports *"we cannot tell"*, never *"no increase"* or `0.0%` | [`test_10_nssp_dark_hsa_data_unavailable_never_claims_no_increase`](file:///Users/dvt112/Downloads/A4I/tests/test_11_e2e_challenge_compliance.py#L496-L527) | [`test_02_health_agent.py`](file:///Users/dvt112/Downloads/A4I/tests/test_02_health_agent.py), [`test_04_validator_agent.py`](file:///Users/dvt112/Downloads/A4I/tests/test_04_validator_agent.py) |
| **Questions that need more than we gave you** | **Graceful Degradation on Optional Enrichments** (`marta_gtfs`, `usda_food_access`, `imls_venues`): completes planning using tract centroids when `include_optional_datasets=False` or BigQuery raises `NotFound` | [`test_11_graceful_degradation_when_optional_datasets_unavailable`](file:///Users/dvt112/Downloads/A4I/tests/test_11_e2e_challenge_compliance.py#L529-L545) | [`test_01_bigquery_mcp.py`](file:///Users/dvt112/Downloads/A4I/tests/test_01_bigquery_mcp.py), [`test_03_mobility_agent.py`](file:///Users/dvt112/Downloads/A4I/tests/test_03_mobility_agent.py) |
| **Section 11: What We Left Out (And Why)** | **10 Deliberate Exclusions & OWASP Guardrails**: SVI Theme 3 (`RPL_THEME3`, `RPL_THEMES`), `FQHC_ADMIN_CONTACT_*` PII, RHC `*_FTE_CT` decoys, CC BY-NC transit matrices, unlicensed mobile clinics, SQLi/prompt injection, and unverified host booking claims | [`test_12_ten_deliberate_exclusions_and_security_guardrails`](file:///Users/dvt112/Downloads/A4I/tests/test_11_e2e_challenge_compliance.py#L547-L601) | [`test_00_contracts_and_security.py`](file:///Users/dvt112/Downloads/A4I/tests/test_00_contracts_and_security.py), [`test_01_bigquery_mcp.py`](file:///Users/dvt112/Downloads/A4I/tests/test_01_bigquery_mcp.py), [`test_08_communicator_agent.py`](file:///Users/dvt112/Downloads/A4I/tests/test_08_communicator_agent.py) |

---

## 2. Detailed Breakdown of the 12 End-to-End Compliance Test Cases

### Test Case 01: Multi-Strategy 4-Stop Siting & Sensitivity Verification
- **Method**: [`Test11E2EChallenge5PublicHealthCompliance.test_01_e2e_all_three_siting_strategies_produce_4_stops_and_distinct_rationales`](file:///Users/dvt112/Downloads/A4I/tests/test_11_e2e_challenge_compliance.py#L97-L169)
- **Challenge 5 Context**: The county outreach lead can prioritize balanced uninsured/safety-net gaps, chronic respiratory burden, or zero-vehicle transit barriers.
- **Assertions**:
  1. Executes [`execute_carebridge_plan`](file:///Users/dvt112/Downloads/A4I/carebridge/agents/coordinator/runner.py) across all 3 strategies (`balanced_uninsured_safety_net_gap`, `chronic_respiratory_focus`, `zero_vehicle_transit_priority`).
  2. Verifies each strategy returns `status == "provisional_approved"` with 4 ranked Saturday stops (`stop_rank` `1..4`).
  3. Verifies pairwise Haversine distance $\ge 5.0\text{ km}$ across all 6 stop pairs per plan.
  4. Verifies `host_verified == False` and `PROVISIONAL` warnings on every stop.
  5. Verifies `SensitivitySummary` (`weight_perturbation_pct == 15.0`, `top_4_stability_jaccard > 0.0`).
  6. Confirms different weighting strategies produce distinct composite need score distributions.

### Test Case 02: Three Tracks, One Architecture & One-Way Demographic Diode
- **Method**: [`Test11E2EChallenge5PublicHealthCompliance.test_02_three_tracks_one_architecture_and_one_way_demographic_diode`](file:///Users/dvt112/Downloads/A4I/tests/test_11_e2e_challenge_compliance.py#L171-L216)
- **Challenge 5 Context**: Section 13 (*"Three Tracks, One Architecture"*) requires Track 1 (Siting Planner) to be strictly race-blind, Track 2 (Auditor) to evaluate post-hoc demographic equity in a separate permission boundary, and Track 3 (Communicator) to draft bilingual community flyers.
- **Assertions**:
  1. Verifies every key in `PLANNER_VISIBLE_STATE_KEYS` (`plan_request`, `health_evidence`, `mobility_evidence`, `evidence_report`), `SANITIZED_LOOPBACK_STATE_KEYS` (`non_demographic_feedback`, `revision_required`), `draft_plan`, and `final_plan` passes [`assert_race_blind_planner_input()`](file:///Users/dvt112/Downloads/A4I/carebridge/security/race_blind_guard.py) and [`assert_no_pii_in_payload()`](file:///Users/dvt112/Downloads/A4I/carebridge/security/race_blind_guard.py).
  2. Verifies `audit_report.demographic_impact` contains post-hoc county vs. catchment parity comparisons (`black`, `hispanic`, `minority_overall`, `catchment_svi_theme3_mean`).
  3. Verifies that passing `audit_report` into `assert_race_blind_planner_input()` raises `PolicyViolationError`.

### Test Case 03: Judge Question 1 — Agent Ablation & Necessity Verification
- **Method**: [`Test11E2EChallenge5PublicHealthCompliance.test_03_judge_question_1_delete_any_agent_degrades_or_breaks_deliverable`](file:///Users/dvt112/Downloads/A4I/tests/test_11_e2e_challenge_compliance.py#L218-L282)
- **Challenge 5 Context**: *"If I delete any one agent from your diagram, does the answer get worse?"*
- **Assertions**:
  1. **Without Agent A (`health_access_agent`)**: Validator sets `core_tables_ready=False` with blocking failures, and Planner halts (`status="insufficient_candidates"`, `stops=[]`).
  2. **Without Agent B (`transit_community_agent`)**: Optional MARTA GTFS Saturday headways and IMLS library host venues are lost (`saturday_transit_access_bonus == 0.0`), forcing fallback to generic tract centroids.
  3. **Without Auditor (`equity_rigor_auditor`)**: Defective `Draft 0` with $< 5.0\text{ km}$ catchment overlap remains unrepaired in the output.

### Test Case 04: Judge Question 2 — Cross-Agent `session.state` Handoff Chain
- **Method**: [`Test11E2EChallenge5PublicHealthCompliance.test_04_judge_question_2_session_state_handoff_chain_across_all_agents`](file:///Users/dvt112/Downloads/A4I/tests/test_11_e2e_challenge_compliance.py#L284-L324)
- **Challenge 5 Context**: *"Show me a key in `session.state` that one agent writes and another agent reads."*
- **Assertions**:
  Executes [`root_agent`](file:///Users/dvt112/Downloads/A4I/agent/agent.py) via ADK `InMemoryRunner` and verifies all 8 cross-agent state handoff keys are populated and consumed in sequence:
  - `health_evidence` (written by `health_access_agent` $\rightarrow$ read by `evidence_validator_agent` & `siting_planner_agent`)
  - `mobility_evidence` (written by `transit_community_agent` $\rightarrow$ read by `evidence_validator_agent` & `siting_planner_agent`)
  - `evidence_report` (written by `evidence_validator_agent` $\rightarrow$ read by `siting_planner_agent`, `equity_rigor_auditor`, & `community_communications_agent`)
  - `draft_plan` (written by `siting_planner_agent` $\rightarrow$ read by `equity_rigor_auditor`)
  - `non_demographic_feedback` (written by `equity_rigor_auditor` $\rightarrow$ read by `siting_planner_agent` on Iteration 1)
  - `audit_report` (written by `equity_rigor_auditor` $\rightarrow$ read by `audit_loop_exit_gate`)
  - `final_plan` (promoted by `audit_loop_exit_gate` $\rightarrow$ read by `community_communications_agent`)
  - `outreach_messages` (written by `community_communications_agent` $\rightarrow$ read by `PlanResponse` assembler)

### Test Case 05: Judge Question 3 — Genuinely Conflicting Agent Instructions
- **Method**: [`Test11E2EChallenge5PublicHealthCompliance.test_05_judge_question_3_genuinely_conflicting_agent_instructions`](file:///Users/dvt112/Downloads/A4I/tests/test_11_e2e_challenge_compliance.py#L326-L355)
- **Challenge 5 Context**: *"Show me two agents whose instructions genuinely conflict."*
- **Assertions**:
  1. Verifies [`PLANNER_AGENT_INSTRUCTION`](file:///Users/dvt112/Downloads/A4I/carebridge/agents/planner_agent/prompts.py) mandates analytical citations, 95% confidence interval disclosures, and race-blindness, while [`AUDITOR_AGENT_INSTRUCTION`](file:///Users/dvt112/Downloads/A4I/carebridge/agents/auditor_agent/prompts.py) enforces an adversarial/skeptical posture, and [`COMMUNICATOR_AGENT_INSTRUCTION`](file:///Users/dvt112/Downloads/A4I/carebridge/agents/communicator_agent/prompts.py) mandates warm 6th-grade reading level English/Spanish copy with zero statistical jargon.
  2. Compares actual Stop #1 outputs: `final_plan.stops[0].plain_language_rationale` includes `PLACES`, `95% CI`, and tract GEOID `13121010514`, whereas `outreach.stop_notices[0].english_notice` contains zero statistical hedging (`p90/p10`, `jaccard`, `haversine`, `crude95ci`, `rpl_theme`).

### Test Case 06: Judge Question 4 — Self-Rejection & Bounded Revision (`Draft 0` $\rightarrow$ `Draft 1`)
- **Method**: [`Test11E2EChallenge5PublicHealthCompliance.test_06_judge_question_4_self_rejection_and_bounded_revision_draft0_to_draft1`](file:///Users/dvt112/Downloads/A4I/tests/test_11_e2e_challenge_compliance.py#L357-L386)
- **Challenge 5 Context**: *"Show me a point where the system rejected its own first answer."*
- **Assertions**:
  1. Runs `execute_carebridge_plan` with `simulate_first_draft_defect=True`.
  2. Confirms `revision_history` has 2 drafts (`Draft 0` and `Draft 1`).
  3. Confirms `Draft 0` Stop #1 (`13121010514`) and Stop #2 (`13121010305`) are $< 5.0\text{ km}$ apart (`3.72 km`) and rejected by the Auditor (`AuditVerdict.REJECTED_REVISION_REQUIRED`).
  4. Confirms `Draft 1` replaces the overlapping stop so all 4 stops are $\ge 5.0\text{ km}$ apart and receives `AuditVerdict.APPROVED`.

### Test Case 07: All 7 Outreach Lead Questions ("What You're Building")
- **Method**: [`Test11E2EChallenge5PublicHealthCompliance.test_07_what_youre_building_all_7_outreach_lead_questions`](file:///Users/dvt112/Downloads/A4I/tests/test_11_e2e_challenge_compliance.py#L388-L442)
- **Assertions**:
  1. **Routine Checkup Inversion**: `pct_checkup + pct_checkup_gap == 100.0` across all 12 Fulton fixture tracts.
  2. **Two Uninsured Rates**: Tract `13121010214` (Adamsville) has `pct_uninsured_18_64 == 24.2%` (PLACES working-age adults) vs `pct_uninsured_all_ages == 14.0%` (SVI all ages, lowered by Medicare 65+), yielding `uninsured_age_structure_gap == 10.2` percentage points.
  3. **Two Distances**: Tract `13121010119` (North Fulton) has `km_to_any_care == 2.4 km` vs `km_to_safety_net == 28.6 km` (`extra_km_if_uninsured == 26.2 km`).
  4. **Question 7 (*"How do I tell the neighborhood we didn't pick why we didn't pick them?"*)**: Verifies `runner_up_tracts` (`#5`–`#8`) include valid `deferral_reason_code` (`catchment_already_covered`, `inter_stop_separation_constraint`, etc.) and matching bilingual `unpicked_neighborhood_explanations` directing residents to the nearest selected Saturday stop (`Stop #k` / `Parada #k`).

### Test Case 08: Four Spatial Resolutions & Ecological Fallacy Prevention
- **Method**: [`Test11E2EChallenge5PublicHealthCompliance.test_08_questions_that_need_more_4_spatial_resolutions_and_grain_enforcement`](file:///Users/dvt112/Downloads/A4I/tests/test_11_e2e_challenge_compliance.py#L444-L473)
- **Assertions**:
  1. Verifies all 4 spatial grains in `SpatialGrain`: `census_tract_11char`, `epa_12km_grid_on_tract_id`, `facility_lon_lat_point`, and `multi_county_health_service_area`.
  2. Injects a stop rationale claiming COVID-19/RSV is spiking in a single tract (`13121010214`), claiming a tract has the "highest PM2.5 tract in the county", and claiming a "15-minute bus ride" from straight-line distance.
  3. Verifies [`execute_independent_plan_audit`](file:///Users/dvt112/Downloads/A4I/carebridge/agents/auditor_agent/tools.py) rejects the plan with `DefectCategory.UNSUPPORTED_GRAIN_CLAIM`.

### Test Case 09: HRSA HPSA `0/99` Active `shortage_areas` vs `6` `shortage_facilities` & `check()` vs `note()`
- **Method**: [`Test11E2EChallenge5PublicHealthCompliance.test_09_hpsa_shortage_areas_zero_active_vs_facilities_and_two_verdict_validation`](file:///Users/dvt112/Downloads/A4I/tests/test_11_e2e_challenge_compliance.py#L475-L494)
- **Assertions**:
  1. Verifies Fulton County's `shortage_areas_count == 0` (all 99 rows in HRSA's source table are `Proposed For Withdrawal`) vs `shortage_facilities_count == 6` is recorded as a non-fatal publisher `WARN` (`is_pipeline_check=False`) rather than halting the pipeline (`core_tables_ready == True`).

### Test Case 10: NSSP Dark Health Service Area (`data_unavailable=True`) Trap
- **Method**: [`Test11E2EChallenge5PublicHealthCompliance.test_10_nssp_dark_hsa_data_unavailable_never_claims_no_increase`](file:///Users/dvt112/Downloads/A4I/tests/test_11_e2e_challenge_compliance.py#L496-L527)
- **Challenge 5 Context**: In counties like Santa Clara, CA (`06085`) or Bronx, NY (`36005`), NSSP `percent_visits_*` and `ed_trends_*` are `NULL`. A naive system treats `NULL` as `0.0` ("no increase").
- **Assertions**:
  1. Verifies `RegionalDiseaseSignal` preserves `data_unavailable=True` and `None` values without fabricating `0.0`.
  2. Verifies the Evidence Validator logs a `WARN` note instructing downstream agents to report `'we cannot tell', never 'no increase'`.

### Test Case 11: Graceful Degradation When Optional Enrichments Are Missing
- **Method**: [`Test11E2EChallenge5PublicHealthCompliance.test_11_graceful_degradation_when_optional_datasets_unavailable`](file:///Users/dvt112/Downloads/A4I/tests/test_11_e2e_challenge_compliance.py#L529-L545)
- **Assertions**:
  1. Executes `execute_carebridge_plan` with `include_optional_datasets=False` (simulating missing MARTA GTFS, USDA Food Access, and IMLS Libraries).
  2. Verifies the workflow completes end-to-end (`status="provisional_approved"`, 4 stops selected via tract centroids) and records `marta_gtfs: False`, `usda_food_access: False`, and `imls_venues: False` in `data_availability`.

### Test Case 12: All 10 Section 11 Exclusions & OWASP LLM Top 10 Guardrails
- **Method**: [`Test11E2EChallenge5PublicHealthCompliance.test_12_ten_deliberate_exclusions_and_security_guardrails`](file:///Users/dvt112/Downloads/A4I/tests/test_11_e2e_challenge_compliance.py#L547-L601)
- **Assertions**:
  1. Blocks SVI Theme 3 (`rpl_theme3`, `rpl_themes`, `ep_minrty`, `pct_black`, `DEMOGRAPHIC_AUDIT_FIXTURES`) via `assert_race_blind_planner_input()`.
  2. Blocks administrative contact PII (`fqhc_admin_contact_nm`, `fqhc_admin_contact_email`, `fqhc_admin_contact_phone_num`, raw email/phone regexes) via `assert_no_pii_in_payload()`.
  3. Verifies `FULTON_CARE_SITES` uses `tot_oper_hr_per_week` and excludes RHC `*_FTE_CT` decoy columns.
  4. Blocks non-Auditor access to `mcp_query_posthoc_demographic_audit` via `before_tool_guardrail_callback`.
  5. Blocks SQL injection in `validate_county_fips` and prompt injection in `ModelArmorScreener` / `sanitize_user_prompt`.
  6. Blocks fabricated host booking claims (`"confirmed and booked"`) in `communicator_after_model_guardrail`.
