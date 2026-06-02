#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT/.env.azure}"

log() { echo "[cloudshell-deploy] $*"; }

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERROR: $ENV_FILE not found." >&2
  echo "       Run ./scripts/bootstrap-azure.sh first." >&2
  exit 1
fi

export ENV_FILE
export SKIP_AZ_LOGIN=true

chmod +x "$ROOT/scripts/deploy-local.sh"

log "Deploying from Azure Cloud Shell (no Mac required)"
log "Using $ENV_FILE"

"$ROOT/scripts/deploy-local.sh" deploy
"$ROOT/scripts/bootstrap-azure.sh" --grafana-only
"$ROOT/scripts/deploy-local.sh" verify

echo ""
echo "Done — app is running in Azure."
echo "Optional: download secrets with: cat .env.azure"
