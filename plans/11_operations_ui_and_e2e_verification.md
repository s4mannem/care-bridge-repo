# Plan 11 — Operations UI (Interactive 4-Part Clinic Plan Artifact) & End-to-End Verification

> **Component Role**: Implements the **Public Health Operations UI** (`Section 01`) and the **End-to-End Verification Suite** covering all requirements from ["What you're building"](https://github.com/haggman/A4I2026-challenge-5-public-health#what-youre-building), ["Questions that need more than we gave you"](https://github.com/haggman/A4I2026-challenge-5-public-health#questions-that-need-more-than-we-gave-you), and the **"Three Tracks, One Architecture"** thesis.

---

## 1. Executive Summary & Architectural Purpose

The Public Health Operations UI renders the **4-part interactive Clinic Plan Artifact** directly from `POST /v1/plan`:
1. **Interactive Fulton County Siting Map & 4-Stop Schedule**:
   - Displays the 4 proposed Saturday stops (`#1`–`#4`), their 4 km catchment rings, covered census tracts, existing federal `care_sites` / `shortage_facilities`, and normalized score breakdowns (`uninsured_norm`, `safety_net_distance_norm`, `no_vehicle_norm`, `chronic_respiratory_norm`, `checkup_preventive_gap_norm` = `100 - pct_checkup`).
   - Displays analytical, cited, resolution-qualified rationales for the outreach lead + `PROVISIONAL — Host & Permit Unconfirmed` badges.
2. **Question 7 Deliverable — Runner-Up Neighborhood Deferral Ledger ("Why We Didn't Pick Them")**:
   - Dedicated panel showing high-need runner-up tracts (`#5`–`#8`) with both the Planner's technical deferral rationale (`catchment_already_covered`, `inter_stop_separation_constraint`) and the Communicator's empathetic English & Spanish community explanations directing residents to the nearest selected Saturday stop.
3. **Visible Planner $\rightleftarrows$ Auditor Disagreement & Post-Hoc Equity Audit Panel**:
   - Interactive toggle (`Simulate Draft 0 Catchment Overlap Defect`) showing Draft 0 (rejected by the Independent Auditor for catchment overlap), the sanitized `non_demographic_feedback` sent to the Planner, Draft 1 (revised non-overlapping stops), and the Auditor's post-hoc demographic parity table (`external_demographic_audit` vs Fulton County baseline).
4. **Grounded Bilingual (EN/ES) Bus-Stop Flyers & 4-Resolution / 7-Boundary Disclosure Panel**:
   - Side-by-side 6th-grade English and Spanish community flyer cards (readable at a bus stop, contrasting with the Planner/Auditor's hedged clinical/technical notes) plus the 4-county HSA respiratory surveillance note and all 7 "Questions that need more than we gave you" disclosures.

---

## 2. File Ownership (Strict Isolation for Parallel Builds)

This plan owns **only** the following files:
```text
/Users/dvt112/Downloads/A4I/
├── carebridge/
│   └── ui/
│       ├── __init__.py
│       └── static/
│           ├── index.html
│           ├── styles.css
│           └── app.js
└── tests/
    └── test_11_e2e_challenge_compliance.py
```

---

## 3. Step-by-Step Implementation Specification

### Step 3.1: Interactive Operations UI (`carebridge/ui/static/index.html`, `styles.css`, `app.js`)

Build a clean, responsive dashboard (with Leaflet/SVG Fulton County tract & catchment visualization) that calls `POST /v1/plan` and `GET /v1/tracts/13121` and renders:
- Strategy selector (`balanced_uninsured_safety_net_gap`, `chronic_respiratory_focus`, `zero_vehicle_transit_priority`) + `Simulate Draft 0 Defect (Show Planner <-> Auditor Disagreement)` checkbox.
- **Tab 1: 4-Saturday Siting Plan & Map** (4 stops, score breakdown bars including `100 - pct_checkup`, analytical citations, provisional host warnings).
- **Tab 2: Why Not Picked? (Runner-Up Tracts #5–#8)** (answers Question 7 with technical deferral codes + EN/ES community explanations).
- **Tab 3: Independent Equity & Rigor Audit** (Draft 0 vs Draft 1 revision diff, sanitized `non_demographic_feedback` vs post-hoc `demographic_impact` parity table, and sensitivity Jaccard stability).
- **Tab 4: Bus-Stop Flyers (EN / ES) & 7 Data Boundaries** (6th-grade bilingual flyers, 4-county HSA note, and explicit disclosures for all 7 "Questions that need more than we gave you").

---

### Step 3.2: End-to-End Challenge 5 Compliance Test Suite (`tests/test_11_e2e_challenge_compliance.py`)

Verifies every single requirement from the Challenge 5 prompt end-to-end:
1. **3-Pointer Multi-Agent Separation**:
   - Planner is 100% race-blind (`assert_race_blind_planner_input` passes on all Planner inputs/outputs).
   - Auditor sees `external_demographic_audit` in an isolated context and can reject Draft 0 via `non_demographic_feedback` without leaking demographic targets back to the Planner.
   - Communicator produces 6th-grade EN/ES flyers without statistical hedging or invented bookings, while Planner/Auditor outputs carry explicit citations and spatial grain qualifications.
2. **"What You're Building" (All 7 Outreach Lead Questions)**:
   - Verifies `pct_checkup_gap == 100.0 - pct_checkup` inversion.
   - Verifies `runner_up_tracts` and `unpicked_neighborhood_explanations` answer Question 7 (*"How do I tell the neighborhood we didn't pick why we didn't pick them?"*).
3. **"Questions That Need More Than We Gave You" (All 7 Edge Questions)**:
   - Verifies 4 spatial resolutions (`11-char Tract`, `12km Grid`, `Facility Point`, `4-County HSA`) and all mandatory caveats (straight-line federal upper-bound distance $\neq$ bus travel time, CC BY-NC transit exclusion, NPPES pharmacy PII exclusion, unlicensed mobile clinic exclusion, PLACES 95% CI uncertainty, no individual medical triage).
4. **Operations UI Serving**:
   - Verifies `GET /` serves the Operations UI HTML and static assets cleanly.

---

## 4. Verification Command

Run the entire test suite across Plans `00`–`11`:
```bash
pytest -v
```

---

## 5. Antigravity Execution Prompt

> **Copy-paste into Antigravity to execute Plan 11:**
> "Execute `/Users/dvt112/Downloads/A4I/plans/11_operations_ui_and_e2e_verification.md`. Create `carebridge/ui/static/` (`index.html`, `styles.css`, `app.js`) and `tests/test_11_e2e_challenge_compliance.py`. Then run `pytest -v` across the full test suite (`test_00` through `test_11`) and confirm 100% pass rate."
