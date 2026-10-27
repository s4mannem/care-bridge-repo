# api/: CareBridge gateway (FastAPI)

The API the Saturday Planner UI (`ui/`) calls. It sits in front of the agents: routes hand
requests to an `AgentRunner` and never call ADK or BigQuery for the UI directly.

**Status: contracts and recorded plans.** `/v1/plan` takes and returns the plan 00 contracts, and the
`stub` runner answers with recorded Fulton plans, so the UI works end to end. The planner tools and
the ADK graph come next.

## Run it

```bash
cd api
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'          # add ,agents for google-adk
.venv/bin/uvicorn carebridge.main:app --reload --port 8000
.venv/bin/pytest
```

Interactive docs: http://localhost:8000/docs (turned off when `CAREBRIDGE_ENV=prod`).

Point the UI at it with `flutter run -d chrome --dart-define=CAREBRIDGE_API=http://localhost:8000`.

## Layout

| Path | What lives there |
|---|---|
| `carebridge/main.py` | App factory: middleware, CORS, error handlers, routers |
| `carebridge/config.py` | Settings from `CAREBRIDGE_*` env vars; also reads the repo-root `.env` |
| `carebridge/api/routes/` | `health` (`/healthz`, `/readyz`), `plan` (`POST /v1/plan`), `tracts` (`GET /v1/tracts/{fips}`) |
| `carebridge/api/middleware.py` | `X-Request-Id` on every response, plus an access log line |
| `carebridge/api/errors.py` | `{"error": {"code", "message", "request_id"}}` for every failure |
| `carebridge/api/deps.py` | Dependency providers (settings, BigQuery repo, agent runner) |
| `carebridge/agents/runner.py` | The `AgentRunner` seam. `stub` serves recorded plans; `adk` will run the multi-agent graph |
| `carebridge/data/bigquery.py` | `a4i_health` access via Application Default Credentials |
| `carebridge/contracts/` | Plan 00 Pydantic models (`PlanRequest`, `PlanResponse`, plan/audit/evidence/outreach) and `session.state` keys; `ui/lib/models.dart` mirrors them |
| `carebridge/security/` | Race-blind planner guard, PII guard, prompt-injection screening, OWASP callbacks for the agents |
| `carebridge/telemetry/` | Request-id correlation and the ADK telemetry plugin |
| `carebridge/mocks/` | `recorded/`: six real-data plans + the Fulton tract layer (from `ui/scripts/build_mock.py`). `fulton_fixtures.py`: small synthetic fixtures for unit tests |
| `carebridge/tools/` | *Next:* scoring, selection and audit tools ported from `ui/scripts/build_mock.py` |

## Endpoints

| Method | Path | Today |
|---|---|---|
| GET | `/healthz` | `200 {"status": "ok"}` (liveness) |
| GET | `/readyz` | `200`/`503` with config checks; `?deep=true` also queries BigQuery |
| POST | `/v1/plan` | `PlanRequest` → `PlanResponse`. Stub: the recorded plan for `strategy` × `simulate_first_draft_defect` (Fulton only, else `404`). `422` on a contract violation, `400` on blocked free text, `504` past `CAREBRIDGE_PLAN_TIMEOUT_S` |
| GET | `/v1/tracts/{county_fips}` | GeoJSON tracts with `need` per strategy for `13121`; `404` for other counties, `422` if not 5 digits |

## Configuration

See `.env.example`. Copy it to `api/.env` (gitignored). Values in `api/.env` override the repo-root `.env`.

## Deploy

This is the `api` component in the shared pipeline. See [deploy/README.md](../deploy/README.md).

- The Dockerfile's `test` stage runs pytest, and its `runtime` stage is what Cloud Run serves.
- The Cloud Run settings and env vars are in `deploy/components/api/service.yaml`.
- Credentials come from the `carebridge-api` service account, never from the image.

## Contract notes

- `RunnerUpTractExplanation.need_rank` is `ge=1`, not plan 00's `ge=5`: a coverage optimizer can
  leave a top-4 need tract outside every catchment, and the recorded no-car plan does exactly that.
- `_compat.py` comes from the foundation branch unchanged. With pydantic installed it re-exports the
  real classes; its `google-genai` fallback lets the safety settings load without the agents extra.
