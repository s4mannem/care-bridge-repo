#!/usr/bin/env bash
# Refresh agents/carebridge from the repo's top-level carebridge/ package, which
# is where the team edits the agents. Run it before releasing the agents service.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
rsync -a --delete --exclude __pycache__ "$here/../carebridge/" "$here/carebridge/"
echo "agents/carebridge now matches carebridge/ ($(git -C "$here/.." rev-parse --short HEAD))"
