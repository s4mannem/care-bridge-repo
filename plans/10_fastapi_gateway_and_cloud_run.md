# Plan 10 — FastAPI Gateway, Cloud Run Packaging & Deployment

> **Component Role**: Implements **Section 01 — Runtime Entry & Cloud Packaging** (`Cloud Run Service · FastAPI + ADK Runner`) from the CareBridge AI architecture diagram.
> **Endpoints Covered**:
> - `POST /v1/plan` (executes the CareBridge AI multi-agent siting, audit, and outreach pipeline and returns `PlanResponse`)
> - `GET /v1/counties/13121/summary` (returns Fulton County baseline snapshot, 4 spatial resolutions metadata, and dataset availability)
> - `GET /healthz` and `GET /readyz` (Cloud Run liveness/readiness probes)
> - `GET /` (serves the interactive CareBridge AI Operations UI from Plan 11)

---

## 1. Executive Summary & Architectural Purpose

From the CareBridge AI architecture diagram:
- **Runtime Entry**: *"Single-container MVP (`Cloud Run Service · FastAPI + ADK Runner`) exposing `POST /v1/plan`, `/healthz`, `/readyz` and static Operations UI."*
- **Response Contract (`PlanResponse`)**:
  - Returns `final_plan` (4 proposed Saturday stops + `runner_up_tracts`), `audit_report` (verdict, `non_demographic_defects`, post-hoc `demographic_impact`), `revision_history` (showing visible disagreement between Draft 0 and Draft 1 when challenged), `outreach` (6th-grade EN/ES bus-stop flyers + `unpicked_neighborhood_explanations`), `provenance`, `limitations`, `data_availability`, and `needs_human_review`.

---

## 2. File Ownership (Strict Isolation for Parallel Builds)

This plan owns **only** the following files:
```text
/Users/dvt112/Downloads/A4I/
├── carebridge/
│   └── api/
│       ├── __init__.py
│       ├── app.py
│       └── routes.py
├── Dockerfile
├── deploy_cloud_run.sh
└── tests/
    └── test_10_fastapi_gateway.py
```

---

## 3. Step-by-Step Implementation Specification

### Step 3.1: FastAPI Routes (`carebridge/api/routes.py`)

Implement an `APIRouter`:
1. `GET /healthz`: Returns `{"status": "ok", "service": "carebridge-ai-track1", "version": "1.0.0"}`.
2. `GET /readyz`: Verifies configuration, security guardrails (`race_blind_guard`, `model_armor`), and BigQuery/mock fixture readiness.
3. `POST /v1/plan`:
   - Accepts `PlanRequest` body.
   - Runs `sanitize_user_prompt` on inputs to block prompt injection or PII.
   - Calls `await execute_carebridge_plan(request)` from `carebridge.agents.coordinator.runner`.
   - Runs `assert_no_pii_in_payload` on the serialized `PlanResponse` before returning.
4. `GET /v1/tracts/{county_fips}`:
   - Returns validated race-blind tract burden & access metrics + facility locations (`care_sites`, `shortage_facilities`) for map rendering in the Operations UI.

---

### Step 3.2: FastAPI Application Factory (`carebridge/api/app.py`)

- Configures CORS, request-ID middleware, structured JSON logging, and OpenTelemetry request tracing.
- Mounts static assets from `carebridge/ui/static` (if present) and serves `carebridge/ui/static/index.html` at `GET /`.

---

### Step 3.3: Single-Container Cloud Run `Dockerfile` & `deploy_cloud_run.sh`

- `Dockerfile`: Uses `python:3.11-slim`, runs as non-root user `carebridge`, installs `pyproject.toml`, and starts `uvicorn carebridge.api.app:app --host 0.0.0.0 --port ${PORT:-8080}`.
- `deploy_cloud_run.sh`: Parameterized `gcloud run deploy carebridge-ai` script setting `--region=us-central1`, `--memory=2Gi`, and BigQuery dataset environment variables.

---

## 4. Verification & Unit Tests (`tests/test_10_fastapi_gateway.py`)

Run standalone:
```bash
pytest tests/test_10_fastapi_gateway.py -v
```
Tests must verify:
1. `GET /healthz` and `GET /readyz` return HTTP 200.
2. `POST /v1/plan` with default Fulton County (`13121`) payload returns HTTP 200 and a valid `PlanResponse` JSON matching all contract fields (`final_plan.stops`, `final_plan.runner_up_tracts`, `audit_report`, `outreach.stop_notices`, `outreach.unpicked_neighborhood_explanations`).
3. `POST /v1/plan` with `simulate_first_draft_defect=True` returns `len(revision_history) == 2`, demonstrating the Planner $\rightleftarrows$ Auditor challenge-and-revision loop over HTTP.
4. Invalid `county_fips` (e.g., `"13121; DROP TABLE"`) is rejected with HTTP 422.

---

## 5. Antigravity Execution Prompt

> **Copy-paste into Antigravity to execute Plan 10:**
> "Execute `/Users/dvt112/Downloads/A4I/plans/10_fastapi_gateway_and_cloud_run.md`. Create `carebridge/api/` (`__init__.py`, `routes.py`, `app.py`), `Dockerfile`, `deploy_cloud_run.sh`, and `tests/test_10_fastapi_gateway.py`. Run `pytest tests/test_10_fastapi_gateway.py -v` and confirm all tests pass."
