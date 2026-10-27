variable "project_id" {
  description = "Google Cloud project that hosts every environment."
  type        = string
}

variable "region" {
  description = "Region for Cloud Run, Artifact Registry, Cloud Build and Cloud Deploy."
  type        = string
  default     = "us-central1"
}

variable "prefix" {
  description = "Name prefix for services, pipelines, service accounts and the image repository."
  type        = string
  default     = "carebridge"
}

variable "environments" {
  description = "Cloud Deploy targets, in promotion order. One Cloud Run service per component per env."
  type = list(object({
    name             = string
    require_approval = bool
  }))
  default = [
    { name = "dev", require_approval = false },
    { name = "prod", require_approval = true },
  ]
}

variable "github_connection" {
  description = "Name of an existing Cloud Build (2nd gen) GitHub connection in var.region. Empty skips triggers."
  type        = string
  default     = ""
}

variable "github_repo_uri" {
  description = "HTTPS clone URL of the repository the triggers watch."
  type        = string
  default     = "https://github.com/s4mannem/care-bridge-repo.git"
}

variable "main_branch" {
  description = "Branch whose pushes create releases and whose PRs run CI."
  type        = string
  default     = "main"
}

variable "maps_extra_referrers" {
  description = "More web addresses allowed to use the UI's Google Maps key, e.g. the hashed Cloud Run URL (https://carebridge-ui-dev-<hash>-uc.a.run.app/*)."
  type        = list(string)
  default     = []
}
