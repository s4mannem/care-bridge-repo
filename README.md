# CareBridge

Plans four Saturday mobile clinic stops for a county from public federal data, audits the plan for
who it lands on, and explains it to the neighborhood. Built for Agents for Impact 2026, Challenge 5.

| Folder | Component | What it is |
|---|---|---|
| [`ui/`](ui/README.md) | `ui` | Saturday Planner, a Flutter app (web, iOS, Android) |
| [`api/`](api/README.md) | `api` | FastAPI gateway; runs the ADK multi-agent graph in-process (`CAREBRIDGE_AGENT_ENGINE=adk`) |
| `api/carebridge/agents/` | (inside `api`) | The agents: Health & Access (Gemini, over BigQuery's managed MCP server), Siting Planner (Gemini + coverage optimizer tool), Equity & Rigor Auditor (Gemini), Communications (Gemini); `graph.py` wires them |
| `agents/` | `agents` | Not used: the agents run inside `api`. Enable this component only to split them into their own private Cloud Run service |
| `mcp/` | `mcp` | Not used: the evidence agent consumes BigQuery's Google-managed MCP server, so nothing is self-hosted |
| [`deploy/`](deploy/README.md) | | Component registry and Cloud Run templates; **start here for CI/CD** |
| `ci/` | | Generic Cloud Build configs and scripts |
| `infra/` | | Terraform for the Google Cloud setup |

Shared settings (`BQ_PROJECT`, `GOOGLE_CLOUD_PROJECT`, ...) go in a gitignored `.env` at the repo root.
