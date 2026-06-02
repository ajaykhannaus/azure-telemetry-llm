#!/usr/bin/env bash
# Diagnose and repair self-hosted Grafana Container App (404 / no healthy replicas).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG="${BOOTSTRAP_CONFIG:-$ROOT/azure/bootstrap-azure.env}"
ENV_FILE="${ENV_FILE:-$ROOT/.env.azure}"

log() { echo "[fix-grafana] $*"; }

[[ -f "$CONFIG" ]] || { echo "ERROR: Missing $CONFIG" >&2; exit 1; }

set -a
# shellcheck disable=SC1090
source "$CONFIG"
set +a

: "${AZURE_RESOURCE_GROUP:?Set AZURE_RESOURCE_GROUP in $CONFIG}"

ACR_NAME="${ACR_NAME:-acrtelemetrydevaj}"
GRAFANA_APP_NAME="${GRAFANA_APP_NAME:-grafana-telemetry-dev}"
ACR_LOGIN_SERVER="${ACR_LOGIN_SERVER:-$(az acr show --name "$ACR_NAME" --resource-group "$AZURE_RESOURCE_GROUP" --query loginServer -o tsv)}"

az account set --subscription "${AZURE_SUBSCRIPTION_ID:?Set AZURE_SUBSCRIPTION_ID}"

log "Diagnosing $GRAFANA_APP_NAME in $AZURE_RESOURCE_GROUP ..."

if az containerapp show --name "$GRAFANA_APP_NAME" --resource-group "$AZURE_RESOURCE_GROUP" >/dev/null 2>&1; then
  az containerapp show --name "$GRAFANA_APP_NAME" --resource-group "$AZURE_RESOURCE_GROUP" \
    --query "{status:properties.runningStatus,fqdn:properties.configuration.ingress.fqdn,revision:properties.latestRevisionName}" -o json
  log "Replicas:"
  az containerapp replica list --name "$GRAFANA_APP_NAME" --resource-group "$AZURE_RESOURCE_GROUP" -o table 2>/dev/null \
    || log "  (no replicas — app cannot serve traffic)"
  log "Recent system logs:"
  az containerapp logs show --name "$GRAFANA_APP_NAME" --resource-group "$AZURE_RESOURCE_GROUP" \
    --type system --tail 15 2>/dev/null || true
  log "Recent console logs:"
  az containerapp logs show --name "$GRAFANA_APP_NAME" --resource-group "$AZURE_RESOURCE_GROUP" \
    --type console --tail 15 2>/dev/null || true
else
  log "Container App $GRAFANA_APP_NAME does not exist yet."
fi

if az acr repository show --name "$ACR_NAME" --image grafana:latest >/dev/null 2>&1; then
  log "ACR image ok: $ACR_LOGIN_SERVER/grafana:latest"
else
  log "WARN: $ACR_LOGIN_SERVER/grafana:latest not found in ACR — will rebuild"
fi

log "Repair: delete (if exists) → rebuild image → redeploy → wait for /api/health"
export GRAFANA_RECREATE=true
export FORCE_IMAGE_BUILD=true
export FORCE_CONTAINER_DEPLOY=true
export BOOTSTRAP_CONFIG="$CONFIG"
export WRITE_ENV_FILE="${WRITE_ENV_FILE:-.env.azure}"
chmod +x "$ROOT/scripts/bootstrap-azure.sh"
"$ROOT/scripts/bootstrap-azure.sh" --grafana-only

FQDN=$(az containerapp show --name "$GRAFANA_APP_NAME" --resource-group "$AZURE_RESOURCE_GROUP" \
  --query "properties.configuration.ingress.fqdn" -o tsv 2>/dev/null || true)

if [[ -n "$FQDN" ]] && curl -sf --max-time 20 "https://${FQDN}/api/health" >/dev/null 2>&1; then
  echo ""
  log "Grafana is healthy: https://${FQDN}  (admin / ${GRAFANA_ADMIN_PASSWORD:-admin})"
else
  echo ""
  log "Grafana still not healthy. Run these and share output:"
  echo "  az containerapp replica list -n $GRAFANA_APP_NAME -g $AZURE_RESOURCE_GROUP -o table"
  echo "  az containerapp logs show -n $GRAFANA_APP_NAME -g $AZURE_RESOURCE_GROUP --type system --tail 30"
  exit 1
fi
