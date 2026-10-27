# Two Cloud Build triggers per component, scoped to its folder:
#   <prefix>-<component>-ci       PR into main  -> ci/cloudbuild/ci.yaml
#   <prefix>-<component>-release  push to main  -> ci/cloudbuild/release.yaml
#
# Needs a 2nd-gen GitHub connection made once in the console (it installs the
# Cloud Build GitHub app); pass its name as var.github_connection.

locals {
  trigger_components = var.github_connection == "" ? {} : local.components
}

resource "google_cloudbuildv2_repository" "repo" {
  count = var.github_connection == "" ? 0 : 1

  name              = trimsuffix(basename(var.github_repo_uri), ".git")
  location          = var.region
  parent_connection = "projects/${var.project_id}/locations/${var.region}/connections/${var.github_connection}"
  remote_uri        = var.github_repo_uri
}

resource "google_cloudbuild_trigger" "ci" {
  for_each = local.trigger_components

  name            = "${var.prefix}-${each.key}-ci"
  location        = var.region
  description     = "PR check for ${each.key} (${each.value.dir}/)"
  service_account = google_service_account.ci.id
  filename        = "ci/cloudbuild/ci.yaml"
  included_files  = ["${each.value.dir}/**", "ci/**"]

  repository_event_config {
    repository = google_cloudbuildv2_repository.repo[0].id
    pull_request {
      branch = "^${var.main_branch}$"
      # Public repo: PRs from outside contributors wait for a /gcbrun comment.
      comment_control = "COMMENTS_ENABLED_FOR_EXTERNAL_CONTRIBUTORS_ONLY"
    }
  }

  substitutions = {
    _COMPONENT = each.key
    _DIR       = each.value.dir
  }
}

resource "google_cloudbuild_trigger" "release" {
  for_each = local.trigger_components

  name            = "${var.prefix}-${each.key}-release"
  location        = var.region
  description     = "Build ${each.key} and release it to ${local.env_names[0]}"
  service_account = google_service_account.ci.id
  filename        = "ci/cloudbuild/release.yaml"
  included_files  = ["${each.value.dir}/**", "deploy/components/${each.key}/**", "ci/**"]

  repository_event_config {
    repository = google_cloudbuildv2_repository.repo[0].id
    push {
      branch = "^${var.main_branch}$"
    }
  }

  substitutions = {
    _COMPONENT      = each.key
    _DIR            = each.value.dir
    _ENVS           = join(",", local.env_names)
    _PREFIX         = var.prefix
    _REGION         = var.region
    _REPO           = google_artifact_registry_repository.images.repository_id
    _PROJECT_NUMBER = data.google_project.this.number
    _DEPLOY_BUCKET  = google_storage_bucket.deploy.name
  }
}
