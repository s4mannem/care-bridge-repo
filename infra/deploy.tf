# One Cloud Deploy target per environment, shared by every component, and one
# delivery pipeline per component that walks the targets in order.

resource "google_clouddeploy_target" "env" {
  for_each = { for e in var.environments : e.name => e }

  name             = "${var.prefix}-${each.key}"
  location         = var.region
  description      = "${var.prefix} ${each.key} on Cloud Run"
  require_approval = each.value.require_approval

  run {
    location = "projects/${var.project_id}/locations/${var.region}"
  }

  execution_configs {
    usages           = ["RENDER", "DEPLOY"]
    service_account  = google_service_account.deployer.email
    artifact_storage = "gs://${google_storage_bucket.deploy.name}/artifacts"
  }

  depends_on = [google_project_service.apis]
}

resource "google_clouddeploy_delivery_pipeline" "component" {
  for_each = local.components

  name        = "${var.prefix}-${each.key}"
  location    = var.region
  description = "${each.key} (${each.value.dir}/): ${join(" -> ", local.env_names)}"

  serial_pipeline {
    dynamic "stages" {
      for_each = var.environments
      content {
        target_id = google_clouddeploy_target.env[stages.value.name].name
        # Profile name matches the env; ci/scripts/render.py writes one per env.
        profiles = [stages.value.name]
      }
    }
  }
}
