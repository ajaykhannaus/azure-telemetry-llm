#!/usr/bin/env bash
# Verify runner, observability backend, and Grafana in Azure.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lib/azure-deploy-common.sh
source "$ROOT/scripts/lib/azure-deploy-common.sh"
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

app_ingress_external() {
  az containerapp show --name "$1" --resource-group "$AZURE_RESOURCE_GROUP" \
    --query "properties.configuration.ingress.external" -o tsv 2>/dev/null || echo "false"
}

app_running_ok() {
  local name=$1
  local prov run
  prov=$(az containerapp show --name "$name" --resource-group "$AZURE_RESOURCE_GROUP" \
    --query "properties.provisioningState" -o tsv 2>/dev/null || echo "")
  run=$(az containerapp show --name "$name" --resource-group "$AZURE_RESOURCE_GROUP" \
    --query "properties.runningStatus" -o tsv 2>/dev/null || echo "")
  [[ "$prov" == "Succeeded" && "$run" == "Running" ]]
}

check_runner_metrics() {
  local fqdn=$1
  local url="https://${fqdn}/metrics"
  local resp code

  if runner_metrics_ok "$url"; then
    ok "Runner /metrics — $url"
    return 0
  fi

  resp=$(curl -s --compressed -w $'\n%{http_code}' --max-time 20 "$url" 2>/dev/null || printf '\n000')
  code=$(printf '%s' "$resp" | tail -1)

  if [[ "$code" == "200" ]]; then
    ok "Runner /metrics — $url (HTTP 200)"
    return 0
  fi

  if app_running_ok "$APP_NAME"; then
    warn "Container App $APP_NAME is Running but /metrics returned HTTP ${code:-unknown}"
    warn "  Fix: ./scripts/fix-runner.sh"
  else
    warn "Container App $APP_NAME is not Running — redeploy runner"
    warn "  Fix: ./scripts/fix-runner-now.sh"
  fi
  fail "Runner /metrics — $url (HTTP ${code:-unknown})"
  return 1
}

check_url() {
  local label=$1 url=$2 pattern=${3:-}
  if [[ -n "$pattern" ]]; then
    if curl -sf --max-time 20 "$url" 2>/dev/null | grep -q "$pattern"; then
      ok "$label — $url"
      return 0
    fi
  elif curl -sf --max-time 20 "$url" >/dev/null 2>&1; then
    ok "$label — $url"
    return 0
  fi
  fail "$label — $url"
  return 1
}

check_container_app() {
  local label=$1 name=$2 url=$3 pattern=${4:-}
  if [[ "$(app_ingress_external "$name")" == "true" ]]; then
    check_url "$label" "$url" "$pattern"
    return
  fi
  if app_running_ok "$name"; then
    ok "$label — $name (internal ingress, Running)"
    return 0
  fi
  fail "$label — $name (internal ingress, not Running)"
  return 1
}

echo ""
log "=== Telemetry runner ==="
RUNNER_FQDN=$(app_fqdn "$APP_NAME")
if [[ -n "$RUNNER_FQDN" ]]; then
  check_runner_metrics "$RUNNER_FQDN"
else
  fail "Runner $APP_NAME has no FQDN"
fi

echo ""
log "=== Observability backend ==="
LOKI_FQDN=$(app_fqdn "$LOKI_APP_NAME")
TEMPO_FQDN=$(app_fqdn "$TEMPO_APP_NAME")
PROM_FQDN=$(app_fqdn "$PROM_APP_NAME")
OTEL_FQDN=$(app_fqdn "$OTEL_APP_NAME")

[[ -n "$LOKI_FQDN" ]] && check_container_app "Loki /ready" "$LOKI_APP_NAME" "https://${LOKI_FQDN}/ready" \
  || fail "Loki $LOKI_APP_NAME missing"
[[ -n "$TEMPO_FQDN" ]] && check_container_app "Tempo /ready" "$TEMPO_APP_NAME" "https://${TEMPO_FQDN}/ready" \
  || fail "Tempo $TEMPO_APP_NAME missing"
[[ -n "$PROM_FQDN" ]] && check_container_app "Prometheus /-/ready" "$PROM_APP_NAME" "https://${PROM_FQDN}/-/ready" \
  || fail "Prometheus $PROM_APP_NAME missing"
[[ -n "$OTEL_FQDN" ]] && check_container_app "OTel Collector health" "$OTEL_APP_NAME" "https://${OTEL_FQDN}/" \
  || fail "OTel Collector $OTEL_APP_NAME missing"

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
