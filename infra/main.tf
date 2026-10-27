locals {
  # deploy/components.yaml is the source of truth for what gets a pipeline.
  registry   = yamldecode(file("${path.module}/../deploy/components.yaml"))
  components = { for name, c in local.registry.components : name => c if try(c.enabled, true) }

  env_names = [for e in var.environments : e.name]

  runtime_roles = merge([
    for name, c in local.components : { for role in try(c.roles, []) : "${name}/${role}" => { component = name, role = role } }
  ]...)
}

data "google_project" "this" {
  project_id = var.project_id
}

resource "google_project_service" "apis" {
  for_each = toset([
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "clouddeploy.googleapis.com",
    "run.googleapis.com",
    "iam.googleapis.com",
    "secretmanager.googleapis.com",
    "bigquery.googleapis.com",
    "aiplatform.googleapis.com",
  ])
  service            = each.value
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "images" {
  repository_id = var.prefix
  location      = var.region
  format        = "DOCKER"
  description   = "Container images for every ${var.prefix} component."

  cleanup_policies {
    id     = "keep-recent"
    action = "KEEP"
    most_recent_versions {
      keep_count = 20
    }
  }
  cleanup_policies {
    id     = "drop-old"
    action = "DELETE"
    condition {
      older_than = "2592000s" # 30 days; anything in the newest 20 is kept above
    }
  }

  depends_on = [google_project_service.apis]
}

# Release sources and Cloud Deploy render/deploy artifacts.
resource "google_storage_bucket" "deploy" {
  name                        = "${var.project_id}-${var.prefix}-deploy"
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = true

  lifecycle_rule {
    condition {
      age = 90
    }
    action {
      type = "Delete"
    }
  }
}
