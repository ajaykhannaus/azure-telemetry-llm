#!/usr/bin/env bash
# End-to-end Azure observability: runner → logs/traces/metrics → Grafana.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT/.env.azure}"
SKIP_PULL=false
FORCE_GRAFANA=false

usage() {
  cat <<EOF
Usage: $0 [--no-git-pull] [--force-grafana]

  One-shot Cloud Shell setup after bootstrap-azure.sh:
    1. Deploy/fix telemetry runner (ACR admin)
    2. Deploy Loki + Tempo + Prometheus + OTel Collector
    3. Wire runner OTLP → collector
    4. Redeploy Grafana with datasource URLs (if needed)
    5. Verify health of all components

  --force-grafana  Always refresh Grafana Container App (default: only if verify fails)
EOF
}

for arg in "$@"; do
  case "$arg" in
    --no-git-pull) SKIP_PULL=true ;;
    --force-grafana) FORCE_GRAFANA=true ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $arg" >&2; usage >&2; exit 1 ;;
  esac
done

log() { echo "[setup-complete] $*"; }

if [[ "$SKIP_PULL" != "true" && -d "$ROOT/.git" ]]; then
  log "Updating repo..."
  git -C "$ROOT" pull --ff-only origin master 2>/dev/null \
    || git -C "$ROOT" pull --ff-only origin main 2>/dev/null \
    || log "WARN: git pull failed"
fi

[[ -f "$ENV_FILE" ]] || { log "ERROR: Missing $ENV_FILE — run ./scripts/bootstrap-azure.sh first"; exit 1; }

export BOOTSTRAP_CONFIG="${BOOTSTRAP_CONFIG:-$ROOT/azure/bootstrap-azure.sandbox.env}"
[[ -f "$BOOTSTRAP_CONFIG" ]] || BOOTSTRAP_CONFIG="$ROOT/azure/bootstrap-azure.env"
export WRITE_ENV_FILE="$ENV_FILE"

chmod +x "$ROOT/scripts/"*.sh

log "Step 1/5 — Runner (metrics + Event Hub)"
"$ROOT/scripts/fix-runner.sh" --no-git-pull ${FORCE_IMAGE_BUILD:+--build}

log "Step 2/5 — Observability backend (Loki, Tempo, Prometheus, OTel Collector)"
"$ROOT/scripts/deploy-observability-stack.sh" --no-git-pull ${FORCE_IMAGE_BUILD:+--build}

log "Step 3/5 — Runner OTLP → collector (included in obs-stack)"
# deploy-observability-stack wires OTLP by default

log "Step 4/5 — Grafana (datasources)"
need_grafana=false
if [[ "$FORCE_GRAFANA" == "true" ]]; then
  need_grafana=true
else
  GRAFANA_APP="${GRAFANA_APP_NAME:-grafana-telemetry-dev}"
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
  if ! curl -sf --max-time 15 "https://$(az containerapp show -n "$GRAFANA_APP" -g "$AZURE_RESOURCE_GROUP" \
      --query 'properties.configuration.ingress.fqdn' -o tsv 2>/dev/null)/api/health" >/dev/null 2>&1; then
    need_grafana=true
  elif [[ -z "${LOKI_URL:-}" || -z "${TEMPO_URL:-}" || -z "${PROMETHEUS_URL:-}" ]]; then
    need_grafana=true
  else
    log "Grafana already healthy with datasource URLs — skipping redeploy"
  fi
fi

if [[ "$need_grafana" == "true" ]]; then
  export FORCE_CONTAINER_DEPLOY=true
  "$ROOT/scripts/bootstrap-azure.sh" --grafana-only --no-build
fi

log "Step 4b/5 — Grafana datasource URLs"
"$ROOT/scripts/fix-grafana-datasources.sh"

log "Step 5/5 — Verify"
"$ROOT/scripts/verify-observability.sh"

echo ""
echo "============================================================"
echo "  Full observability stack is ready"
echo "============================================================"
echo "  Open Grafana URL from verify output (login: admin / admin)"
echo "  Allow 2–3 minutes for dashboards to populate after first deploy"
echo "============================================================"
