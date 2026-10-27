# Plan 05 — Four-Stop Coverage Optimizer (Custom Deterministic Python Tool)

> **Component Role**: Implements the **Four-Stop Coverage Optimizer** (`data-node="optimizer"`) in Lane 02 (Decide, Optimize, Challenge) of the CareBridge AI architecture diagram.
> **ADK Primitive**: Pure, deterministic Python module wrapped as an ADK `FunctionTool` (`optimize_four_clinic_stops`) invoked by the `Siting Planner Agent`.

---

## 1. Executive Summary & Architectural Purpose

The CareBridge AI architecture diagram explicitly mandates:
- **"A deterministic Python optimizer owns scoring and four-site selection, not Gemini prose."**
- **"Custom Python tool computes within-county normalized need scores, selects distinct geographic catchments, discounts overlapping coverage and reports sensitivity to weights. Pure/testable scoring and greedy maximum-coverage are suitable MVP implementations. No invented visit counts or venue capacity."**

Key capabilities built in this module:
1. **Race-Blind Within-County Min-Max / Quantile Need Scoring (`scoring.py`)**:
   - Computes normalized `[0.0, 1.0]` component scores across all valid tracts in the county using ONLY permitted structural/clinical variables:
     - `uninsured_norm`: `pct_uninsured_18_64` (PLACES adults 18–64)
     - `safety_net_distance_norm`: `km_to_safety_net` (with extra weight on `extra_km_if_uninsured > 0`)
     - `no_vehicle_norm`: `pct_no_vehicle` (combined with `pct_mobility_difficulty` / `pct_lack_transport`)
     - `chronic_respiratory_norm`: mean of normalized `pct_asthma`, `pct_copd`, `pct_diabetes`, `pct_bphigh`
     - `checkup_preventive_gap_norm`: normalized `100.0 - pct_checkup` (explicitly inverting `pct_checkup` because low routine checkup rate is bad and indicates a preventive care gap)
     - `saturday_transit_access_bonus`: normalized Saturday MARTA stop availability at the candidate venue (`0.0` if optional MARTA view is unavailable)
   - Supports the 3 strategy weight profiles requested via `PlanRequest.strategy`:
     - `balanced_uninsured_safety_net_gap`: `(0.30 uninsured, 0.25 safety_net_dist, 0.20 no_vehicle, 0.15 chronic, 0.10 checkup_gap)`
     - `chronic_respiratory_focus`: `(0.20 uninsured, 0.20 safety_net_dist, 0.15 no_vehicle, 0.35 chronic, 0.10 checkup_gap)`
     - `zero_vehicle_transit_priority`: `(0.20 uninsured, 0.25 safety_net_dist, 0.35 no_vehicle, 0.10 chronic, 0.10 checkup_gap)`
2. **Greedy Maximum-Coverage 4-Stop Selector, Runner-Up Deferral Ledger & Catchment Overlap Discount (`coverage.py`)**:
   - Uses Haversine distance (`catchment_radius_km = 4.0 km` default) around each candidate stop/tract centroid.
   - At each step $k \in \{1, 2, 3, 4\}$, evaluates the marginal population-weighted need covered by each candidate stop, **heavily discounting (`overlap_discount = 0.85`) tracts already covered by previously selected stops** and enforcing a minimum inter-stop separation (`min_stop_separation_km = 5.0 km`) unless `exclude_tract_geoids` or audit remediation overrides it.
   - **Answers Question 7 ("How do I tell the neighborhood we didn't pick why we didn't pick them?")**: Deterministically computes `runner_up_tracts` (`list[RunnerUpTractExplanation]`) for the highest-need non-selected tracts (ranks #5–#8), recording exact `deferral_reason_code` (`catchment_already_covered`, `inter_stop_separation_constraint`, `no_saturday_transit_or_venue`, or `lower_marginal_coverage`), `covered_by_stop_rank`, and `distance_to_nearest_selected_stop_km`.
   - Supports `excluded_tract_geoids` and `min_separation_km_override` parameters so when the `Independent Equity & Rigor Auditor` rejects Draft 0 for catchment overlap or infeasible host, the revision run deterministically selects non-overlapping alternative stops.
   - Never invents patient visit capacity or clinic appointment counts; flags all selected venues with `host_verified=False`.
3. **Weight Sensitivity Analysis (`sensitivity.py`)**:
   - Perturbs strategy weights by $\pm 15\%$ across 8 deterministic directions and computes the Jaccard stability index of the selected top-4 catchments (`top_4_stability_jaccard`) plus `borderline_tracts`.

---

## 2. File Ownership (Strict Isolation for Parallel Builds)

This plan owns **only** the following files:
```text
/Users/dvt112/Downloads/A4I/
├── carebridge/
│   └── tools/
│       └── optimizer/
│           ├── __init__.py
│           ├── scoring.py
│           ├── coverage.py
│           ├── sensitivity.py
│           └── tool.py
└── tests/
    └── test_05_optimizer_tool.py
```

---

## 3. Step-by-Step Implementation Specification

### Step 3.1: Within-County Race-Blind Need Scoring (`carebridge/tools/optimizer/scoring.py`)

```python
import math
from carebridge.contracts.evidence_models import TractHealthRecord, TractMobilityRecord
from carebridge.contracts.plan_models import ScoreBreakdown
from carebridge.security.race_blind_guard import assert_race_blind_planner_input

STRATEGY_WEIGHTS: dict[str, dict[str, float]] = {
    "balanced_uninsured_safety_net_gap": {
        "uninsured": 0.35,
        "safety_net_distance": 0.30,
        "no_vehicle": 0.20,
        "chronic_respiratory": 0.15,
    },
    "chronic_respiratory_focus": {
        "uninsured": 0.25,
        "safety_net_distance": 0.25,
        "no_vehicle": 0.15,
        "chronic_respiratory": 0.35,
    },
    "zero_vehicle_transit_priority": {
        "uninsured": 0.25,
        "safety_net_distance": 0.25,
        "no_vehicle": 0.35,
        "chronic_respiratory": 0.15,
    },
}
```
- Implement `haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float`.
- Implement `compute_tract_scores(tracts: list[TractHealthRecord], mobility_map: dict[str, TractMobilityRecord], strategy: str, custom_weights: dict[str, float] | None = None) -> dict[str, ScoreBreakdown]`:
  - First runs `assert_race_blind_planner_input([t.model_dump() for t in tracts])`.
  - Ignores zero-population tracts (`total_pop <= 0`) or tracts missing coordinates.
  - Normalizes each variable within the county `[min, max] -> [0.0, 1.0]`.

---

### Step 3.2: Greedy Max-Coverage 4-Stop Selector (`carebridge/tools/optimizer/coverage.py`)

Implement `select_four_distinct_stops(...) -> list[ProposedClinicStop]`:
- For each candidate tract $i$ (with coordinates and `total_pop > 0`), identifies all county tracts within `catchment_radius_km` ($4.0\text{ km}$).
- Computes candidate marginal utility:
  $$\text{Utility}(i \mid S_{\text{covered}}) = \sum_{j \in \text{Catchment}(i)} \text{pop}_j \cdot \text{score}_j \cdot \begin{cases} 1 - \text{overlap\_discount} & \text{if } j \in S_{\text{covered}} \\ 1.0 & \text{otherwise} \end{cases}$$
- Applies an inter-stop distance constraint (`haversine_km(stop_a, stop_b) >= min_separation_km`) so all 4 Saturday stops serve distinct geographic neighborhoods across Fulton County.
- Matches each selected tract to its best `CandidateHostVenue` from `MobilityEvidence` (or labels it `"Provisional Tract Centroid Host ({geo_id}) — Venue Unassigned"` if no library/community venue exists in that tract), always setting `host_verified=False`.
- Includes a `simulate_first_draft_defect: bool = False` option (triggered only on `revision_number == 0` when requested by the demo toggle in `PlanRequest`) that relaxes `min_separation_km` on Stop 2 so the `Independent Equity & Rigor Auditor` can demonstrate catching a real catchment overlap and forcing Revision 1!

---

### Step 3.3: Sensitivity Analyzer (`carebridge/tools/optimizer/sensitivity.py`) & ADK Tool Wrapper (`carebridge/tools/optimizer/tool.py`)

- `run_weight_sensitivity(tracts, mobility_map, strategy) -> SensitivitySummary` runs $\pm 15\%$ perturbations on each weight dimension and computes Jaccard similarity of the selected 4 stops.
- `optimize_four_clinic_stops` in `tool.py` reads `session.state["health_evidence"]`, `session.state["mobility_evidence"]`, `session.state["plan_request"]`, and `session.state["non_demographic_feedback"]` (if in revision 1), executes the deterministic optimizer + sensitivity analysis, and returns a validated `DraftPlan` dict.

---

## 4. Security, Guardrails & Telemetry

- **Deterministic Execution (No LLM Math)**: Zero LLM calls occur inside `carebridge/tools/optimizer/`. Same inputs always produce identical floating-point scores and stop rankings.
- **Race-Blind Verification**: Calls `assert_race_blind_planner_input` at entry; any attempt to pass demographic columns raises `PolicyViolationError`.
- **No Fabricated Operational Claims**: Hardcodes `host_verified = False` and attaches `provisional_warning` to every `ProposedClinicStop`.
- **OpenTelemetry Instrumentation**: Emits span `tool.optimizer.run` with `strategy`, `revision_number`, `candidate_tracts_count`, `selected_tracts`, and `top_4_stability_jaccard`.

---

## 5. Verification & Unit Tests (`tests/test_05_optimizer_tool.py`)

Run standalone:
```bash
pytest tests/test_05_optimizer_tool.py -v
```
Tests must verify:
1. Determinism: Running `optimize_four_clinic_stops` twice on `fulton_fixtures` returns byte-identical `DraftPlan` outputs.
2. Distinct Catchments: All 4 selected stops have pairwise Haversine distances $\ge 5.0\text{ km}$ in normal mode and distinct `primary_tract_geoid` values.
3. Revision Remediation: When `simulate_first_draft_defect=True` on `revision_number=0`, Stops 1 and 2 have overlapping catchments ($< 5.0\text{ km}$); when `revision_number=1` with `non_demographic_feedback` flagging catchment overlap, the optimizer enforces strict separation and resolves the overlap.
4. Insufficient Candidates: If fewer than 4 valid tracts exist, returns `status="insufficient_candidates"` cleanly instead of crashing.
5. Sensitivity Summary: `top_4_stability_jaccard` is in `[0.0, 1.0]`.

---

## 6. Antigravity Execution Prompt

> **Copy-paste into Antigravity to execute Plan 05:**
> "Execute `/Users/dvt112/Downloads/A4I/plans/05_four_stop_coverage_optimizer_tool.md`. Create `carebridge/tools/optimizer/` (`__init__.py`, `scoring.py`, `coverage.py`, `sensitivity.py`, `tool.py`) and `tests/test_05_optimizer_tool.py`. Run `pytest tests/test_05_optimizer_tool.py -v` and confirm 100% pass rate."
