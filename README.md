# CareBridge

Plans four Saturday mobile clinic stops for a county from public federal data, audits the plan for
who it lands on, and explains it to the neighborhood. Built for Agents for Impact 2026, Challenge 5.

| Folder | Component | What it is |
|---|---|---|
| [`ui/`](ui/README.md) | `ui` | Saturday Planner, a Flutter app (web, iOS, Android) |
| [`api/`](api/README.md) | `api` | FastAPI gateway between the UI and the agents |
| `agents/` | `agents` | ADK multi-agent graph (coming) |
| `mcp/` | `mcp` | Self-hosted MCP Toolbox, only if needed (coming) |
| [`deploy/`](deploy/README.md) | | Component registry and Cloud Run templates; **start here for CI/CD** |
| `ci/` | | Generic Cloud Build configs and scripts |
| `infra/` | | Terraform for the Google Cloud setup |

Shared settings (`BQ_PROJECT`, `GOOGLE_CLOUD_PROJECT`, ...) go in a gitignored `.env` at the repo root.
