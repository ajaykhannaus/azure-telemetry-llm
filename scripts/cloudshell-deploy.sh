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

chmod +x "$ROOT/scripts/"*.sh

log "Full observability deploy (runner + Loki/Tempo/Prometheus/Collector + Grafana)"
log "Using $ENV_FILE"

"$ROOT/scripts/cloudshell-setup-complete.sh" --no-git-pull

echo ""
echo "Done — full observability stack is running in Azure."
echo "Optional: download secrets with: cat .env.azure"
