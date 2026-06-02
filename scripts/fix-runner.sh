#!/usr/bin/env bash
# Fix ai-telemetry-runner-dev 404 (no healthy replicas / ACR pull failure).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT/.env.azure}"
RECREATE=false
SKIP_PULL=false
BUILD_IMAGE=false

usage() {
  cat <<EOF
Usage: $0 [--recreate] [--build] [--no-git-pull]

  Redeploys the telemetry runner with ACR admin auth embedded in YAML.
  Requires .env.azure (from bootstrap) with Event Hub settings.

  --recreate  Delete app first (default if app exists but returns 404)
  --build     Force rebuild ai-telemetry-runner:latest in ACR
EOF
}

for arg in "$@"; do
  case "$arg" in
    --recreate) RECREATE=true ;;
    --build) BUILD_IMAGE=true ;;
    --no-git-pull) SKIP_PULL=true ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $arg" >&2; usage >&2; exit 1 ;;
  esac
done

log() { echo "[fix-runner] $*"; }

if [[ "$SKIP_PULL" != "true" && -d "$ROOT/.git" ]]; then
  log "Updating repo..."
  git -C "$ROOT" pull --ff-only origin master 2>/dev/null \
    || git -C "$ROOT" pull --ff-only origin main 2>/dev/null \
    || log "WARN: git pull failed"
  log "Repo: $(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)"
fi

[[ -f "$ENV_FILE" ]] || { log "ERROR: Missing $ENV_FILE — run ./scripts/bootstrap-azure.sh first"; exit 1; }

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

: "${AZURE_RESOURCE_GROUP:?Set AZURE_RESOURCE_GROUP in $ENV_FILE}"
: "${AZURE_SUBSCRIPTION_ID:?Set AZURE_SUBSCRIPTION_ID in $ENV_FILE}"
: "${EVENTHUB_NAMESPACE:?Set EVENTHUB_NAMESPACE in $ENV_FILE}"
: "${EVENTHUB_CONNECTION_STRING:?Set EVENTHUB_CONNECTION_STRING in $ENV_FILE}"

ACR_NAME="${ACR_NAME:-acrtelemetrydevaj}"
APP_NAME="${APP_NAME:-ai-telemetry-runner-dev}"
CAE_NAME="${CAE_NAME:-cae-telemetry-dev}"
AZURE_LOCATION="${AZURE_LOCATION:-eastus}"

az account set --subscription "$AZURE_SUBSCRIPTION_ID"
az extension add --name containerapp --upgrade --yes --output none 2>/dev/null || true

ACR_LOGIN_SERVER="${ACR_LOGIN_SERVER:-$(az acr show --name "$ACR_NAME" \
  --resource-group "$AZURE_RESOURCE_GROUP" --query loginServer -o tsv 2>/dev/null \
  || az acr show --name "$ACR_NAME" --query loginServer -o tsv)}"

runner_fqdn() {
  az containerapp show --name "$APP_NAME" --resource-group "$AZURE_RESOURCE_GROUP" \
    --query "properties.configuration.ingress.fqdn" -o tsv 2>/dev/null || true
}

runner_serving() {
  local fqdn
  fqdn=$(runner_fqdn)
  [[ -n "$fqdn" ]] && curl -sf --max-time 15 "https://${fqdn}/metrics" 2>/dev/null | grep -q ai_gateway
}

render_runner_yaml() {
  local dest=$1 env_id user pass eh_conn otel_ep domain
  env_id=$(az containerapp env show --name "$CAE_NAME" --resource-group "$AZURE_RESOURCE_GROUP" --query id -o tsv)
  az acr update --name "$ACR_NAME" --admin-enabled true --output none 2>/dev/null || true
  user=$(az acr credential show --name "$ACR_NAME" --query username -o tsv)
  pass=$(az acr credential show --name "$ACR_NAME" --query 'passwords[0].value' -o tsv)
  eh_conn="$EVENTHUB_CONNECTION_STRING"
  domain=$(az containerapp env show --name "$CAE_NAME" --resource-group "$AZURE_RESOURCE_GROUP" \
    --query properties.defaultDomain -o tsv)
  otel_ep="${OTEL_EXPORTER_OTLP_ENDPOINT:-http://${OTEL_APP_NAME:-otel-collector-dev}.internal.${domain}:4317}"
  awk -v loc="$AZURE_LOCATION" \
      -v env_id="$env_id" \
      -v acr_server="$ACR_LOGIN_SERVER" \
      -v acr_user="$user" \
      -v acr_pass="$pass" \
      -v image="${ACR_LOGIN_SERVER}/ai-telemetry-runner:latest" \
      -v eh_ns="$EVENTHUB_NAMESPACE" \
      -v eh_conn="$eh_conn" \
      -v otel_ep="$otel_ep" \
      '{
        gsub(/__LOCATION__/, loc)
        gsub(/__MANAGED_ENV_ID__/, env_id)
        gsub(/__ACR_LOGIN_SERVER__/, acr_server)
        gsub(/__ACR_USERNAME__/, acr_user)
        gsub(/__ACR_ADMIN_PASSWORD__/, acr_pass)
        gsub(/__IMAGE__/, image)
        gsub(/__EVENTHUB_NAMESPACE__/, eh_ns)
        gsub(/__EVENTHUB_CONNECTION_STRING__/, eh_conn)
        gsub(/__OTEL_ENDPOINT__/, otel_ep)
        print
      }' "$ROOT/infra/runner-acr-admin.template.yaml" > "$dest"
}

wait_for_runner() {
  local fqdn=$1 i
  log "Polling https://${fqdn}/metrics (up to ~10 min) ..."
  for i in $(seq 1 40); do
    if curl -sf --max-time 15 "https://${fqdn}/metrics" 2>/dev/null | grep -q ai_gateway; then
      log "Runner is healthy: https://${fqdn}/metrics"
      return 0
    fi
    (( i == 1 || i % 4 == 0 )) && log "  waiting ($i/40) ..."
    sleep 15
  done
  return 1
}

# ── main ─────────────────────────────────────────────────────────────────────

log "Runner repair: $APP_NAME in $AZURE_RESOURCE_GROUP"

if [[ "$BUILD_IMAGE" == "true" ]] || ! az acr repository show --name "$ACR_NAME" --image ai-telemetry-runner:latest >/dev/null 2>&1; then
  log "Building $ACR_NAME/ai-telemetry-runner:latest ..."
  az acr build --registry "$ACR_NAME" --platform linux/amd64 \
    --image "ai-telemetry-runner:latest" -f "$ROOT/Dockerfile.runner" "$ROOT"
fi

if az containerapp show --name "$APP_NAME" --resource-group "$AZURE_RESOURCE_GROUP" >/dev/null 2>&1; then
  az containerapp show --name "$APP_NAME" --resource-group "$AZURE_RESOURCE_GROUP" \
    --query "{status:properties.runningStatus,provisioning:properties.provisioningState,fqdn:properties.configuration.ingress.fqdn,replicas:properties.template.scale}" -o json
  log "Replicas:"
  az containerapp replica list --name "$APP_NAME" --resource-group "$AZURE_RESOURCE_GROUP" -o table 2>/dev/null \
    || log "  (no replicas)"
  if runner_serving; then
    log "Runner already serving metrics — nothing to do"
    echo "Metrics: https://$(runner_fqdn)/metrics"
    exit 0
  fi
  [[ "$RECREATE" != "true" ]] && RECREATE=true
else
  RECREATE=false
fi

rendered="$ROOT/infra/runner.rendered.yaml"
render_runner_yaml "$rendered"
log "Rendered $rendered"

if [[ "$RECREATE" == "true" ]] && az containerapp show --name "$APP_NAME" --resource-group "$AZURE_RESOURCE_GROUP" >/dev/null 2>&1; then
  log "Deleting $APP_NAME ..."
  az containerapp delete --name "$APP_NAME" --resource-group "$AZURE_RESOURCE_GROUP" --yes --output none
  for _ in $(seq 1 36); do
    az containerapp show --name "$APP_NAME" --resource-group "$AZURE_RESOURCE_GROUP" >/dev/null 2>&1 || break
    sleep 10
  done
  sleep 30
fi

if az containerapp show --name "$APP_NAME" --resource-group "$AZURE_RESOURCE_GROUP" >/dev/null 2>&1; then
  log "Updating $APP_NAME ..."
  az containerapp update --name "$APP_NAME" --resource-group "$AZURE_RESOURCE_GROUP" --yaml "$rendered"
else
  log "Creating $APP_NAME (ACR admin in YAML, blocking) ..."
  az containerapp create --name "$APP_NAME" --resource-group "$AZURE_RESOURCE_GROUP" --yaml "$rendered"
fi

rm -f "$rendered"

FQDN=$(runner_fqdn)
[[ -z "$FQDN" ]] && { log "ERROR: no ingress FQDN"; exit 1; }

if wait_for_runner "$FQDN"; then
  echo ""
  echo "Metrics: https://${FQDN}/metrics"
  echo "Health:  https://${FQDN}/healthz  (via port 8080 mapping if exposed)"
  exit 0
fi

log "Runner still not healthy:"
az containerapp logs show --name "$APP_NAME" --resource-group "$AZURE_RESOURCE_GROUP" --type system --tail 20 2>/dev/null || true
az containerapp logs show --name "$APP_NAME" --resource-group "$AZURE_RESOURCE_GROUP" --type console --tail 20 2>/dev/null || true
exit 1
