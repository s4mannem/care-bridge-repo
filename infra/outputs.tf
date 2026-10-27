output "service_urls" {
  description = "Cloud Run URL of each component in each env (live once its first release rolls out)."
  value = {
    for pair in setproduct(keys(local.components), local.env_names) :
    "${pair[0]}-${pair[1]}" => "https://${var.prefix}-${pair[0]}-${pair[1]}-${data.google_project.this.number}.${var.region}.run.app"
  }
}

output "delivery_pipelines" {
  value = [for p in google_clouddeploy_delivery_pipeline.component : p.name]
}

output "image_repository" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
}

output "ci_service_account" {
  value = google_service_account.ci.email
}

output "triggers" {
  value = concat(
    [for t in google_cloudbuild_trigger.ci : t.name],
    [for t in google_cloudbuild_trigger.release : t.name],
  )
}
