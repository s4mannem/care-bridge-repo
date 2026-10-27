# agents

The team's ADK agents as their own service: `adk web` (dev UI + REST API) on Cloud Run.

| Path | What it is |
|---|---|
| `carebridge/` | Copy of the repo's top-level [`carebridge/`](../carebridge/README.md) package, where the agents are developed. Refresh it with `./sync.sh`. |
| `adk_runtime/` | Runs those agents on real ADK: the coordinator graph adapter (same as the API's `adk_adapter.py`), Gemini call pacing, and the intake/finalizer steps the API's runner does. |
| `apps/carebridge_coordinator/` | The ADK app: intake → Health & Access ‖ Transit & Community → Validator → Planner ⇄ Auditor (≤ 2 drafts) → Communications → finalizer. |

## Run it

```bash
cd agents && pip install -r requirements.txt
PYTHONPATH=. GOOGLE_GENAI_USE_VERTEXAI=TRUE GOOGLE_CLOUD_LOCATION=global \
  GEMINI_MODEL_REASONING=gemini-3.6-flash MCP_BIGQUERY_URL=https://bigquery.googleapis.com/mcp \
  adk web apps
```

In the chat, send a PlanRequest as JSON, e.g. `{"simulate_first_draft_defect": true}`, or any text for the
Fulton defaults. The finished `PlanResponse` lands in session state under `plan_response`. One plan per session.

## Deploy

`bash ci/submit.sh release agents` (run `./sync.sh` first). The service is private; open the dev UI with
`gcloud run services proxy carebridge-agents-dev --region us-central1 --port 8090`.

The planner UI doesn't call this service. It goes through the API (`api/`), which runs its own copy of the
same agents (`api/carebridge/`).
