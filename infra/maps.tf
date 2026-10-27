# Google Maps for the UI's planner map (Maps JavaScript API, loaded in the browser).
#
# A browser key is visible to anyone who opens the page, so it is locked to the
# UI's own addresses and to the Maps JavaScript API only. It lives in Secret
# Manager; the ui service reads it at start and nginx hands it to the page
# (ui/nginx/default.conf.template, /gmaps.js). Without it the app falls back
# to OpenStreetMap tiles.

resource "google_project_service" "maps" {
  for_each           = toset(["apikeys.googleapis.com", "maps-backend.googleapis.com"])
  service            = each.value
  disable_on_destroy = false
}

locals {
  maps_referrers = concat(
    # Both Cloud Run URL forms work; the project-number one is derivable here.
    [for env in local.env_names : "https://${var.prefix}-ui-${env}-${data.google_project.this.number}.${var.region}.run.app/*"],
    ["http://localhost/*", "http://localhost:*/*", "http://127.0.0.1:*/*"],
    var.maps_extra_referrers,
  )
}

resource "google_apikeys_key" "maps_browser" {
  name         = "${var.prefix}-maps-browser"
  display_name = "${var.prefix} UI map (Maps JavaScript API)"

  restrictions {
    browser_key_restrictions {
      allowed_referrers = local.maps_referrers
    }
    api_targets {
      service = "maps-backend.googleapis.com"
    }
  }

  depends_on = [google_project_service.maps]
}

resource "google_secret_manager_secret" "maps_key" {
  secret_id = "${var.prefix}-google-maps-key"
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

resource "google_secret_manager_secret_version" "maps_key" {
  secret      = google_secret_manager_secret.maps_key.id
  secret_data = google_apikeys_key.maps_browser.key_string
}

resource "google_secret_manager_secret_iam_member" "ui_reads_maps_key" {
  secret_id = google_secret_manager_secret.maps_key.id
  role      = "roles/secretmanager.secretAccessor"
  member    = google_service_account.runtime["ui"].member
}
