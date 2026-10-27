# api/: CareBridge gateway (FastAPI)

The API the Saturday Planner UI (`ui/`) calls. It sits in front of the agents: routes hand
requests to an `AgentRunner` and never call ADK or BigQuery for the UI directly.

**Status: scaffolding.** Routes are wired and return a consistent error shape. The API contracts,
the planner tools and the ADK graph come next.

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
| `carebridge/agents/runner.py` | The `AgentRunner` seam. `stub` today; `adk` runs the multi-agent graph |
| `carebridge/data/bigquery.py` | `a4i_health` access via Application Default Credentials |
| `carebridge/contracts/` | *Next:* Pydantic models mirroring `ui/lib/models.dart` |
| `carebridge/tools/` | *Next:* scoring, selection and audit tools ported from `ui/scripts/build_mock.py` |

## Endpoints

| Method | Path | Today |
|---|---|---|
| GET | `/healthz` | `200 {"status": "ok"}` (liveness) |
| GET | `/readyz` | `200`/`503` with config checks; `?deep=true` also queries BigQuery |
| POST | `/v1/plan` | `501` from the stub runner; `504` if the runner exceeds `CAREBRIDGE_PLAN_TIMEOUT_S` |
| GET | `/v1/tracts/{county_fips}` | `501`; FIPS must be 5 digits or it's `422` |

## Configuration

See `.env.example`. Copy it to `api/.env` (gitignored). Values in `api/.env` override the repo-root `.env`.

## Deploy

This is the `api` component in the shared pipeline. See [deploy/README.md](../deploy/README.md).

- The Dockerfile's `test` stage runs pytest, and its `runtime` stage is what Cloud Run serves.
- The Cloud Run settings and env vars are in `deploy/components/api/service.yaml`.
- Credentials come from the `carebridge-api` service account, never from the image.
