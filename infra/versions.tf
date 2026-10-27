terraform {
  required_version = ">= 1.6"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }

  # Bucket is passed by infra/bootstrap.sh (-backend-config).
  backend "gcs" {
    prefix = "carebridge/infra"
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}
