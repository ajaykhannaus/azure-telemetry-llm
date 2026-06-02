#!/usr/bin/env bash
# Verify runner, observability backend, and Grafana in Azure.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT/.env.azure}"

log() { echo "[verify] $*"; }
ok() { log "OK  $*"; }
warn() { log "WARN $*"; }
fail() { log "FAIL $*"; FAILED=1; }

FAILED=0

[[ -f "$ENV_FILE" ]] || { log "ERROR: Missing $ENV_FILE"; exit 1; }

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

: "${AZURE_RESOURCE_GROUP:?Set AZURE_RESOURCE_GROUP in $ENV_FILE}"
: "${AZURE_SUBSCRIPTION_ID:?Set AZURE_SUBSCRIPTION_ID in $ENV_FILE}"

APP_NAME="${APP_NAME:-ai-telemetry-runner-dev}"
GRAFANA_APP_NAME="${GRAFANA_APP_NAME:-grafana-telemetry-dev}"
PROM_APP_NAME="${PROM_APP_NAME:-prometheus-scraper-dev}"
LOKI_APP_NAME="${LOKI_APP_NAME:-loki-telemetry-dev}"
TEMPO_APP_NAME="${TEMPO_APP_NAME:-tempo-telemetry-dev}"
OTEL_APP_NAME="${OTEL_APP_NAME:-otel-collector-dev}"

az account set --subscription "$AZURE_SUBSCRIPTION_ID"

app_fqdn() {
  az containerapp show --name "$1" --resource-group "$AZURE_RESOURCE_GROUP" \
    --query "properties.configuration.ingress.fqdn" -o tsv 2>/dev/null || true
}

check_url() {
  local label=$1 url=$2 pattern=${3:-}
  if [[ -n "$pattern" ]]; then
    if curl -sf --max-time 20 "$url" 2>/dev/null | grep -q "$pattern"; then
      ok "$label — $url"
    else
      fail "$label — $url"
    fi
  elif curl -sf --max-time 20 "$url" >/dev/null 2>&1; then
    ok "$label — $url"
  else
    fail "$label — $url"
  fi
}

echo ""
log "=== Telemetry runner ==="
RUNNER_FQDN=$(app_fqdn "$APP_NAME")
if [[ -n "$RUNNER_FQDN" ]]; then
  check_url "Runner /metrics" "https://${RUNNER_FQDN}/metrics" "ai_gateway"
else
  fail "Runner $APP_NAME has no FQDN"
fi

echo ""
log "=== Observability backend ==="
LOKI_FQDN=$(app_fqdn "$LOKI_APP_NAME")
TEMPO_FQDN=$(app_fqdn "$TEMPO_APP_NAME")
PROM_FQDN=$(app_fqdn "$PROM_APP_NAME")
OTEL_FQDN=$(app_fqdn "$OTEL_APP_NAME")

[[ -n "$LOKI_FQDN" ]] && check_url "Loki /ready" "https://${LOKI_FQDN}/ready" || fail "Loki $LOKI_APP_NAME missing"
[[ -n "$TEMPO_FQDN" ]] && check_url "Tempo /ready" "https://${TEMPO_FQDN}/ready" || fail "Tempo $TEMPO_APP_NAME missing"
[[ -n "$PROM_FQDN" ]] && check_url "Prometheus /-/ready" "https://${PROM_FQDN}/-/ready" || fail "Prometheus $PROM_APP_NAME missing"
[[ -n "$OTEL_FQDN" ]] && check_url "OTel Collector health" "https://${OTEL_FQDN}/" || log "WARN OTel Collector external health (internal-only ingress is normal)"

echo ""
log "=== Grafana ==="
GRAFANA_FQDN=$(app_fqdn "$GRAFANA_APP_NAME")
if [[ -n "$GRAFANA_FQDN" ]]; then
  if curl -sf --max-time 20 "https://${GRAFANA_FQDN}/api/health" >/dev/null; then
    ok "Grafana /api/health — https://${GRAFANA_FQDN}"
    echo ""
    echo "Grafana: https://${GRAFANA_FQDN}  (admin / ${GRAFANA_ADMIN_PASSWORD:-admin})"
    echo "Datasources: Prometheus=${PROMETHEUS_URL:-https://${PROM_FQDN}} Loki=${LOKI_URL:-https://${LOKI_FQDN}} Tempo=${TEMPO_URL:-https://${TEMPO_FQDN}}"
  else
    fail "Grafana — https://${GRAFANA_FQDN}/api/health"
    echo "  Fix: ./scripts/fix-grafana.sh"
  fi
else
  fail "Grafana $GRAFANA_APP_NAME has no FQDN"
fi

echo ""
log "=== Data flow ==="
echo "  Metrics:  runner /metrics → Prometheus scraper → Grafana (Prometheus DS)"
echo "  Traces:   runner OTLP → OTel Collector → Tempo → Grafana (Tempo DS)"
echo "  Logs:     runner OTLP → OTel Collector → Loki → Grafana (Loki DS)"
echo "  Events:   runner → Event Hub → (ADX when enabled)"
echo "  Platform: Container App stdout → Log Analytics (Azure Portal)"

echo ""
if [[ "$FAILED" -eq 0 ]]; then
  log "All checks passed"
  exit 0
fi

log "Some checks failed — see WARN/FAIL lines above"
exit 1
