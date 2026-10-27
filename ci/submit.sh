#!/usr/bin/env bash
# Run a component's CI check or release from your machine or Cloud Shell, using
# the same Cloud Build config the triggers use. Handy before triggers exist.
#
#   bash ci/submit.sh ci api          # PR-style check: build the test stage
#   bash ci/submit.sh release ui      # test, build, push, Cloud Deploy release to dev
#
# Uploads the repo (minus .gcloudignore) to Cloud Build.
set -euo pipefail

usage() { echo "usage: bash ci/submit.sh <ci|release> <component>" >&2; exit 2; }
[[ $# -eq 2 ]] || usage
kind=$1 component=$2
[[ $kind == ci || $kind == release ]] || usage

root="$(cd "$(dirname "$0")/.." && pwd)"
PROJECT_ID="${PROJECT_ID:-$(gcloud config get-value project 2>/dev/null)}"
REGION="${REGION:-us-central1}"
PREFIX="${PREFIX:-carebridge}"
ENVS="${ENVS:-dev,prod}"

# `dir:` of this component in deploy/components.yaml.
dir=$(awk -v c="  $component:" '
  $0 == c { inside = 1; next }
  inside && /^  [^ ]/ { exit }
  inside && $1 == "dir:" { print $2; exit }' "$root/deploy/components.yaml")
[[ -n $dir ]] || { echo "submit: no component '$component' in deploy/components.yaml" >&2; exit 1; }

# ';'-separated (see `^;^` below) so _ENVS can keep its commas.
subs="_COMPONENT=$component;_DIR=$dir"
if [[ $kind == release ]]; then
  number=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
  subs+=";_ENVS=$ENVS;_PREFIX=$PREFIX;_REGION=$REGION;_REPO=$PREFIX"
  subs+=";_PROJECT_NUMBER=$number;_DEPLOY_BUCKET=$PROJECT_ID-$PREFIX-deploy"
fi

cd "$root"
gcloud builds submit . \
  --project="$PROJECT_ID" --region="$REGION" \
  --config="ci/cloudbuild/$kind.yaml" \
  --service-account="projects/$PROJECT_ID/serviceAccounts/$PREFIX-ci@$PROJECT_ID.iam.gserviceaccount.com" \
  --substitutions="^;^$subs"
