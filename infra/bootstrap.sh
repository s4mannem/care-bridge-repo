#!/usr/bin/env bash
# One-time setup: enable the APIs Terraform needs to start, create the state
# bucket, write terraform.tfvars and run `terraform init`. Safe to rerun.
#
#   bash infra/bootstrap.sh                 # uses the gcloud default project
#   PROJECT_ID=my-proj bash infra/bootstrap.sh
#
# Then: cd infra && terraform plan && terraform apply
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${REGION:-us-central1}"
PREFIX="${PREFIX:-carebridge}"
[[ -n $PROJECT_ID ]] || { echo "bootstrap: set PROJECT_ID or run gcloud config set project" >&2; exit 1; }

echo "bootstrap: project $PROJECT_ID, region $REGION"
gcloud services enable serviceusage.googleapis.com cloudresourcemanager.googleapis.com \
  storage.googleapis.com iam.googleapis.com --project="$PROJECT_ID"

state="$PROJECT_ID-$PREFIX-tfstate"
if ! gcloud storage buckets describe "gs://$state" --project="$PROJECT_ID" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://$state" --project="$PROJECT_ID" --location="$REGION" \
    --uniform-bucket-level-access
  gcloud storage buckets update "gs://$state" --versioning
fi

if [[ ! -f $here/terraform.tfvars ]]; then
  sed -e "s/your-gcp-project/$PROJECT_ID/" -e "s/us-central1/$REGION/" -e "s/\"carebridge\"/\"$PREFIX\"/" \
    "$here/terraform.tfvars.example" > "$here/terraform.tfvars"
  echo "bootstrap: wrote infra/terraform.tfvars"
fi

terraform -chdir="$here" init -backend-config="bucket=$state" -reconfigure
