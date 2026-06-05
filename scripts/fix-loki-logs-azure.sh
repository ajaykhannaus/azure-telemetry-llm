#!/usr/bin/env bash
# Redeploy Loki + OTel Collector for native OTLP log ingestion, rewire runner, refresh Grafana.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT/.env.azure}"

log() { echo "[fix-loki-logs] $*"; }

[[ -f "$ENV_FILE" ]] || { log "ERROR: Missing $ENV_FILE"; exit 1; }

if [[ -d "$ROOT/.git" ]]; then
  log "Updating repo..."
  git -C "$ROOT" pull --ff-only origin master 2>/dev/null \
    || git -C "$ROOT" pull --ff-only origin main 2>/dev/null \
    || log "WARN: git pull failed"
fi

export ENV_FILE
export FORCE_CONTAINER_DEPLOY=true

log "Step 1/4 — Rebuild Loki (OTLP-ready) + OTel Collector (otlphttp/loki exporter)..."
"$ROOT/scripts/deploy-observability-stack.sh" --build --from loki --no-git-pull

log "Step 2/4 — Ensure runner OTLP endpoint points at collector..."
"$ROOT/scripts/fix-runner.sh" --no-git-pull

log "Step 3/4 — Refresh Grafana datasources + dashboards..."
python3 "$ROOT/dashboards/generate_dashboards.py"
export GRAFANA_URL GRAFANA_ADMIN_PASSWORD
# shellcheck disable=SC1090
source "$ENV_FILE"
"$ROOT/scripts/fix-grafana-datasources.sh"

log "Step 4/4 — Verify Loki telemetry_event count..."
"$ROOT/scripts/diagnose-grafana-azure.sh" || true

echo ""
log "Done. In Grafana Explore (Loki), run:"
log '  {service_name=~".+"} | json | event_type="telemetry_event"'
log "Wait 2–3 minutes after runner batches, then hard-refresh Dashboard 2."
