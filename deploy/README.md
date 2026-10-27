# Deployment and CI/CD

Every component (UI, API, agents, MCP, and anything added later) goes through the same path on
Google Cloud. Nothing here is specific to one language or one component.

```
 PR into main ──► Cloud Build  <c>-ci       docker build --target test
                                             (that component's folder changed)

 push to main ──► Cloud Build  <c>-release  test ─► build runtime image ─► Artifact Registry
                                             └─► render Cloud Run manifests ─► Cloud Deploy release
                                                                                     │
                     Cloud Deploy pipeline <prefix>-<c>:   dev  ──(promote + approval)──►  prod
                                                            │                              │
                                              Cloud Run <prefix>-<c>-dev     <prefix>-<c>-prod
```

| Piece | Where | What it does |
|---|---|---|
| Component registry | [`deploy/components.yaml`](components.yaml) | Lists each component: folder, on/off, runtime IAM roles |
| Cloud Run templates | `deploy/components/<c>/service.yaml` | One per component, with `${ENV}`, `${PROJECT_ID}` and similar placeholders |
| CI build | [`ci/cloudbuild/ci.yaml`](../ci/cloudbuild/ci.yaml) | Builds the `test` stage of the component's Dockerfile, only when `_RUN_TESTS=true` |
| Release build | [`ci/cloudbuild/release.yaml`](../ci/cloudbuild/release.yaml) | Runs tests (only when `_RUN_TESTS=true`), then image, then render, then a Cloud Deploy release |
| Renderer | [`ci/scripts/render.py`](../ci/scripts/render.py) | Writes `service.<env>.yaml` plus `skaffold.yaml` (one profile per env) |
| Manual runs | [`ci/submit.sh`](../ci/submit.sh) | Same builds from your shell, before triggers exist |
| Infrastructure | [`infra/`](../infra) | Terraform: APIs, Artifact Registry, service accounts, Cloud Deploy, triggers |

**Build once, deploy many.** The release builds one image and pins its digest. Cloud Deploy moves
that exact digest from dev to prod, and only the rendered env vars differ between environments.

**Tests are off by default.** Both builds skip the `test` stage unless the `_RUN_TESTS`
substitution is `true`, so a PR check passes straight away and a release goes straight to the
image build. Run the tests locally (`pytest`, `flutter test`) before you merge. To turn them back on,
set `_RUN_TESTS = "true"` in the trigger substitutions in [`infra/triggers.tf`](../infra/triggers.tf),
or run `RUN_TESTS=true bash ci/submit.sh ci <component>` for a single run.

## The component contract

To be deployable, a component folder needs:

1. A **Dockerfile with two stages**:
   - `test`: runs its tests. The build fails if the tests fail.
   - `runtime`: serves HTTP on `$PORT` (8080).
2. A **manifest template** at `deploy/components/<name>/service.yaml`. Copy the closest existing one.
   The renderer substitutes `SERVICE`, `ENV`, `PREFIX`, `COMPONENT`, `PROJECT_ID`, `PROJECT_NUMBER`,
   `REGION` and `SERVICE_ACCOUNT`, each written with the `$` and braces. Any other `$` must be written `$$`.
3. An **entry in `deploy/components.yaml`** with `enabled: true` and the IAM roles its runtime needs.
   Then run `terraform apply`, which creates its service account, pipeline and two triggers.

| Component | Folder | Status | Exposure |
|---|---|---|---|
| `api` | `api/` | enabled | public (invoker IAM check off) |
| `ui` | `ui/` | enabled | public; nginx forwards `/v1/` to the same env's API |
| `agents` | `agents/` | disabled until it has a Dockerfile | private (callers need `run.invoker`) |
| `mcp` | `mcp/` | disabled; only for a self-hosted MCP Toolbox | private |

## One-time setup

Run this in Cloud Shell, which already has `terraform`, `gcloud` and `docker`. You need Owner on
the project.

```bash
bash infra/bootstrap.sh
```

That enables the bootstrap APIs, creates the state bucket and runs `terraform init`.

```bash
cd infra && terraform apply
```

This creates everything except the triggers.

**Connect GitHub (once, in the console).** Go to Cloud Build → Repositories → 2nd gen → Create host
connection → GitHub, in `us-central1`. Install the Cloud Build app on the repo. Then set the
connection name in `infra/terraform.tfvars`:

```hcl
github_connection = "<connection-name>"
```

```bash
terraform apply
```

This second apply creates the CI and release triggers per component.

## Day to day

- **Open a PR:** the CI trigger runs for each component whose folder (or `ci/`) changed.
- **Merge to main:** the release trigger builds, then Cloud Deploy rolls the release out to **dev**.
- **Promote to prod:**

  ```bash
  gcloud deploy releases promote --release=<release> --delivery-pipeline=carebridge-<c> --region=us-central1
  ```

  Prod requires approval. Approve in the Cloud Deploy console, or with
  `gcloud deploy rollouts approve`.
- **Roll back:**

  ```bash
  gcloud deploy targets rollback carebridge-prod --delivery-pipeline=carebridge-<c> --region=us-central1
  ```
- **Run a build without triggers:**

  ```bash
  bash ci/submit.sh ci api
  ```

  ```bash
  bash ci/submit.sh release ui
  ```

Find URLs with `terraform output service_urls`. The pattern is
`https://carebridge-<c>-<env>-<project-number>.us-central1.run.app`.

## Decisions worth knowing

- **One project, two environments.** Dev and prod are separate Cloud Run services in the team's
  single project, because the event gives one project per team. For separate projects, give each
  target its own `run.location` and move the IAM to match.
- **The API is public.** The UI's nginx proxy can't attach Google ID tokens, so the API skips the
  invoker check. The UI is served from the same origin, so no CORS is needed and no key is compiled
  into the app. Before real users arrive, put both behind a load balancer with IAP, or restrict
  ingress. Agents and MCP stay private.
- **Least-privilege identities.**
  - `carebridge-ci` can push images and create releases, nothing more.
  - `carebridge-deployer` deploys to Cloud Run.
  - Each component runs as its own `carebridge-<c>` with only the roles listed in the registry.
- **Fork PRs don't run automatically.** CI on PRs from outside contributors waits for a `/gcbrun`
  comment, because the repo is public.
- **Qwiklabs projects expire.** When the lab project goes away, its state, images and services go
  with it. Rerun bootstrap and apply in the new project.
