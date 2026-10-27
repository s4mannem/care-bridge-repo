# Developer guide

How to run each component locally and deploy it to the dev project. For how the CI/CD pipeline
itself works, see [`deploy/README.md`](../deploy/README.md).

| Component | Folder | Cloud Run service (dev) | Access |
|---|---|---|---|
| UI | [`ui/`](../ui/README.md) | `carebridge-ui-dev` | Public: https://carebridge-ui-dev-3amwavtowa-uc.a.run.app |
| API | [`api/`](../api/README.md) | `carebridge-api-dev` | Public; the UI reaches it through its own `/v1` proxy |
| Agents | [`agents/`](../agents/README.md) | `carebridge-agents-dev` | Private: `gcloud run services proxy` (below) |

Where the agent code lives:

- `carebridge/agents/` is where the team develops the agents.
- `agents/carebridge/` is a copy for the agents service. Refresh it with `bash agents/sync.sh`.
- `api/carebridge/` is the API's own copy, which the planner UI uses. A change to `carebridge/`
  does not reach the API unless it is copied there too.

## One-time setup

```bash
gcloud auth login
gcloud auth application-default login      # for local runs against BigQuery and Gemini
gcloud config set project qwiklabs-gcp-04-e4394201f6b9
```

Infrastructure (service accounts, pipelines, the Maps key) comes from Terraform in [`infra/`](../infra).
It is already applied for dev; re-run it only after changing `infra/` or `deploy/components.yaml`:

```bash
cd infra
terraform init -reconfigure -backend-config=bucket=qwiklabs-gcp-04-e4394201f6b9-carebridge-tfstate
terraform apply
```

## Deploy to dev

Run from the repo root, on the code you want live (usually an up-to-date `main`). Each command uploads
your working tree, **uncommitted changes included**, builds the image in Cloud Build, and creates a
Cloud Deploy release that rolls out to dev on its own. Each takes about 2–3 minutes.

```bash
git switch main && git pull
```

### UI

```bash
bash ci/submit.sh release ui
```

### API

```bash
bash ci/submit.sh release api
```

### Agents

```bash
bash agents/sync.sh
bash ci/submit.sh release agents
```

`agents/sync.sh` copies the team's latest `carebridge/` into `agents/carebridge/`; commit the result.

### Check a rollout

Replace `api` with `ui` or `agents`:

```bash
gcloud deploy rollouts list --delivery-pipeline carebridge-api --region us-central1 \
  --release "$(gcloud deploy releases list --delivery-pipeline carebridge-api --region us-central1 \
  --sort-by=~createTime --limit 1 --format='value(name.basename())')"
```

```bash
curl -s https://carebridge-api-dev-3amwavtowa-uc.a.run.app/readyz    # {"status":"ready",...,"agent_engine":"adk"}
curl -s https://carebridge-ui-dev-3amwavtowa-uc.a.run.app/healthz    # ok
```

Open the agents service's ADK dev UI (it is private; the proxy signs requests as you):

```bash
gcloud run services proxy carebridge-agents-dev --region us-central1 --port 8090
```

Then go to http://localhost:8090, pick `carebridge_coordinator`, and send `{"simulate_first_draft_defect": true}`
or any text for the Fulton defaults.

### Promote to prod

Prod gets the same image as dev, after an approval:

```bash
gcloud deploy releases promote --delivery-pipeline carebridge-api --region us-central1 --release <release-name>
```

## Run locally

### API

```bash
cd api
python3 -m venv .venv
.venv/bin/pip install -e '.[dev,agents]'
CAREBRIDGE_AGENT_ENGINE=adk GOOGLE_GENAI_USE_VERTEXAI=TRUE GOOGLE_CLOUD_LOCATION=global \
  BQ_PROJECT=qwiklabs-gcp-04-e4394201f6b9 .venv/bin/uvicorn carebridge.main:app --reload --port 8000
```

Leave out `CAREBRIDGE_AGENT_ENGINE=adk` to serve the recorded plans instead of running the agents.
Tests: `.venv/bin/pytest`.

### UI

```bash
cd ui
flutter pub get
flutter run -d chrome --dart-define=CAREBRIDGE_API=http://localhost:8000   # live local API
flutter run -d chrome                                                        # recorded plans, no API
```

Locally the map uses OpenStreetMap tiles; the Google map needs the deployed UI (its key comes from Secret Manager).

### Agents (ADK dev UI)

```bash
cd agents
pip install -r requirements.txt
PYTHONPATH=. GOOGLE_GENAI_USE_VERTEXAI=TRUE GOOGLE_CLOUD_LOCATION=global \
  GEMINI_MODEL_REASONING=gemini-3.6-flash MCP_BIGQUERY_URL=https://bigquery.googleapis.com/mcp \
  adk web apps
```

## Things to know

- **The last release wins.** Dev runs whatever was released last, from whoever's checkout. Release from `main`.
- **Tests are skipped by default** in Cloud Build. Run them locally, or prefix a release with `RUN_TESTS=true`.
- **Gemini quota is tight.** A full plan makes about a dozen Gemini calls; the agents space them 3 s apart
  (`CAREBRIDGE_GEMINI_MIN_GAP_S` on the API, `GEMINI_MIN_GAP_S` on the agents service) and retry on 429.
- **No auto-deploy yet.** Pushes to `main` don't deploy until the Cloud Build GitHub connection
  covers this repo and `github_connection` is set in `infra/terraform.tfvars` (see `infra/triggers.tf`).
