# Three kinds of identity, each with only what its job needs:
#   ci        Cloud Build: test, push images, create releases
#   deployer  Cloud Deploy: render and roll out to Cloud Run
#   runtime   one per component: what the running service can touch

resource "google_service_account" "ci" {
  account_id   = "${var.prefix}-ci"
  display_name = "${var.prefix} Cloud Build"
}

resource "google_service_account" "deployer" {
  account_id   = "${var.prefix}-deployer"
  display_name = "${var.prefix} Cloud Deploy execution"
}

resource "google_service_account" "runtime" {
  for_each     = local.components
  account_id   = "${var.prefix}-${each.key}"
  display_name = "${var.prefix} ${each.key} runtime"
}

# ── ci ───────────────────────────────────────────────────────────────────────

resource "google_project_iam_member" "ci" {
  for_each = toset(["roles/logging.logWriter", "roles/clouddeploy.releaser"])
  project  = var.project_id
  role     = each.value
  member   = google_service_account.ci.member
}

resource "google_artifact_registry_repository_iam_member" "ci_push" {
  repository = google_artifact_registry_repository.images.name
  location   = var.region
  role       = "roles/artifactregistry.writer"
  member     = google_service_account.ci.member
}

# Cloud Run checks that whoever deploys a revision can read its image, and
# Cloud Deploy deploys as the deployer account.
resource "google_artifact_registry_repository_iam_member" "deployer_pull" {
  repository = google_artifact_registry_repository.images.name
  location   = var.region
  role       = "roles/artifactregistry.reader"
  member     = google_service_account.deployer.member
}

resource "google_storage_bucket_iam_member" "ci_deploy_bucket" {
  bucket = google_storage_bucket.deploy.name
  role   = "roles/storage.objectAdmin"
  member = google_service_account.ci.member
}

# objectAdmin lacks storage.buckets.get, which `gcloud deploy releases create`
# checks before staging the rendered manifests in the deploy bucket.
resource "google_storage_bucket_iam_member" "ci_deploy_bucket_get" {
  bucket = google_storage_bucket.deploy.name
  role   = "roles/storage.legacyBucketReader"
  member = google_service_account.ci.member
}

# `ci/submit.sh` (gcloud builds submit) uploads the source to <project>_cloudbuild,
# and the build runs as the ci account, which must read it back. Triggers don't need
# this; they fetch from GitHub. gcloud creates the bucket on the first submit.
resource "google_storage_bucket_iam_member" "ci_submit_source" {
  bucket = "${var.project_id}_cloudbuild"
  role   = "roles/storage.objectViewer"
  member = google_service_account.ci.member
}

# Creating a release acts as the target's execution service account.
resource "google_service_account_iam_member" "ci_acts_as_deployer" {
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.serviceAccountUser"
  member             = google_service_account.ci.member
}

# ── deployer ─────────────────────────────────────────────────────────────────

# run.admin rather than run.developer: public services set
# run.googleapis.com/invoker-iam-disabled, which needs setIamPolicy.
resource "google_project_iam_member" "deployer" {
  for_each = toset(["roles/clouddeploy.jobRunner", "roles/run.admin", "roles/logging.logWriter"])
  project  = var.project_id
  role     = each.value
  member   = google_service_account.deployer.member
}

resource "google_storage_bucket_iam_member" "deployer_deploy_bucket" {
  bucket = google_storage_bucket.deploy.name
  role   = "roles/storage.objectAdmin"
  member = google_service_account.deployer.member
}

resource "google_service_account_iam_member" "deployer_acts_as_runtime" {
  for_each           = google_service_account.runtime
  service_account_id = each.value.name
  role               = "roles/iam.serviceAccountUser"
  member             = google_service_account.deployer.member
}

# ── runtime ──────────────────────────────────────────────────────────────────

resource "google_project_iam_member" "runtime" {
  for_each = local.runtime_roles
  project  = var.project_id
  role     = each.value.role
  member   = google_service_account.runtime[each.value.component].member
}
