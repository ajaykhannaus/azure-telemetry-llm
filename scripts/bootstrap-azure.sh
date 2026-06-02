#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG="${BOOTSTRAP_CONFIG:-$ROOT/azure/bootstrap-azure.env}"
SKIP_BUILD=false
CLI_PREFLIGHT=false

usage() {
  cat <<EOF
Usage: $0 [--preflight] [--no-build] [--grafana-only]

  Config: azure/bootstrap-azure.env
  Output: .env.azure (copy to .env)
EOF
}

GRAFANA_ONLY=false
for arg in "$@"; do
  case "$arg" in
    --preflight) CLI_PREFLIGHT=true ;;
    --no-build)  SKIP_BUILD=true ;;
    --grafana-only) GRAFANA_ONLY=true ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $arg" >&2; usage >&2; exit 1 ;;
  esac
done

log() { echo "[bootstrap-azure] $*"; }

# Azure Container Apps rejects probe values outside documented ranges.
validate_grafana_yaml() {
  local file=$1
  local line key val bad=false
  while IFS= read -r line; do
    [[ "$line" =~ initialDelaySeconds:[[:space:]]*([0-9]+) ]] || continue
    val="${BASH_REMATCH[1]}"
    if (( val > 60 )); then
      log "ERROR: $file has initialDelaySeconds=$val (Azure max 60)"
      bad=true
    fi
  done < "$file"
  while IFS= read -r line; do
    [[ "$line" =~ failureThreshold:[[:space:]]*([0-9]+) ]] || continue
    val="${BASH_REMATCH[1]}"
    if (( val > 30 )); then
      log "ERROR: $file has failureThreshold=$val (Azure max 30)"
      bad=true
    fi
  done < "$file"
  if [[ "$bad" == "true" ]]; then
    log "Run: git pull   (need latest infra/grafana.template.yaml)"
    return 1
  fi
}

[[ -f "$CONFIG" ]] || {
  echo "ERROR: Missing $CONFIG" >&2
  echo "       cp azure/bootstrap-azure.env.example azure/bootstrap-azure.env" >&2
  exit 1
}

set -a
# shellcheck disable=SC1090
source "$CONFIG"
set +a

: "${AZURE_RESOURCE_GROUP:?Set AZURE_RESOURCE_GROUP in $CONFIG}"

if [[ -z "${AZURE_SUBSCRIPTION_ID:-}" || "$AZURE_SUBSCRIPTION_ID" == "00000000-0000-0000-0000-000000000000" ]]; then
  if [[ -n "${AZURE_SUBSCRIPTION_NAME:-}" ]]; then
    AZURE_SUBSCRIPTION_ID=$(az account list \
      --query "[?name=='$AZURE_SUBSCRIPTION_NAME'].id | [0]" -o tsv 2>/dev/null || true)
    [[ -n "$AZURE_SUBSCRIPTION_ID" ]] || {
      echo "ERROR: Subscription '$AZURE_SUBSCRIPTION_NAME' not found." >&2
      exit 1
    }
    log "subscription $AZURE_SUBSCRIPTION_NAME → $AZURE_SUBSCRIPTION_ID"
  else
    echo "ERROR: Set AZURE_SUBSCRIPTION_ID or AZURE_SUBSCRIPTION_NAME in $CONFIG" >&2
    exit 1
  fi
fi

USE_EXISTING_RG="${USE_EXISTING_RG:-true}"
PROVISION_OBSERVABILITY="${PROVISION_OBSERVABILITY:-true}"
PROVISION_ADX="${PROVISION_ADX:-true}"
BUILD_IMAGES="${BUILD_IMAGES:-true}"
WRITE_ENV_FILE="${WRITE_ENV_FILE:-.env.azure}"
PREFLIGHT="${PREFLIGHT:-false}"
ADX_CLUSTER="${ADX_CLUSTER:-adxtelemetrydev}"
ADX_DATABASE="${ADX_DATABASE:-observability}"
ADX_ENV="${ADX_ENV:-dev}"
[[ "$CLI_PREFLIGHT" == "true" ]] && PREFLIGHT=true
[[ "$SKIP_BUILD" == "true" ]] && BUILD_IMAGES=false

ACR_NAME="${ACR_NAME:-acrtelemetrydevaj}"
CAE_NAME="${CAE_NAME:-cae-telemetry-dev}"
APP_NAME="${APP_NAME:-ai-telemetry-runner-dev}"
PROM_APP_NAME="${PROM_APP_NAME:-prometheus-scraper-dev}"
GRAFANA_NAME="${GRAFANA_NAME:-grafana-telemetry-dev}"
GRAFANA_APP_NAME="${GRAFANA_APP_NAME:-grafana-telemetry-dev}"
PROM_WS="${PROM_WS:-telemetry-prometheus-dev}"
EH_NS="${EH_NS:-evhns-telemetry-devaj}"
EH_NAME="${EVENTHUB_NAME:-ai-telemetry-events}"
AZURE_LOCATION="${AZURE_LOCATION:-eastus}"

[[ "$WRITE_ENV_FILE" != /* ]] && WRITE_ENV_FILE="$ROOT/$WRITE_ENV_FILE"

if ! az account show >/dev/null 2>&1; then
  if [[ -n "${AZURE_CLIENT_ID:-}" && -n "${AZURE_CLIENT_SECRET:-}" && -n "${AZURE_TENANT_ID:-}" ]]; then
    log "service principal login"
    az login --service-principal \
      -u "$AZURE_CLIENT_ID" \
      -p "$AZURE_CLIENT_SECRET" \
      --tenant "$AZURE_TENANT_ID" \
      --output none
  else
    echo "ERROR: Not logged in. Use Azure Cloud Shell or set AZURE_CLIENT_* in $CONFIG." >&2
    exit 1
  fi
fi

az account set --subscription "$AZURE_SUBSCRIPTION_ID"

SUB_NAME=$(az account show --query name -o tsv)
TENANT_ID=$(az account show --query tenantId -o tsv)

echo ""
echo "Azure bootstrap"
echo "  subscription : $SUB_NAME"
echo "  tenant       : $TENANT_ID"
echo "  rg           : $AZURE_RESOURCE_GROUP"
echo "  acr          : $ACR_NAME"
echo "  cae          : $CAE_NAME"
echo "  eventhub     : $EH_NS"
echo "  output       : $WRITE_ENV_FILE"
echo "  mode         : $([[ "$PREFLIGHT" == "true" ]] && echo preflight || echo apply)"
echo ""

[[ "$USE_EXISTING_RG" == "true" ]] && \
  AZURE_LOCATION=$(az group show --name "$AZURE_RESOURCE_GROUP" --query location -o tsv)

ACR_LOGIN_SERVER="${ACR_LOGIN_SERVER:-$(az acr show --name "$ACR_NAME" --resource-group "$AZURE_RESOURCE_GROUP" --query loginServer -o tsv 2>/dev/null || true)}"

containerapp_exists() {
  az containerapp show --name "$1" --resource-group "$AZURE_RESOURCE_GROUP" >/dev/null 2>&1
}

wait_for_containerapp_deleted() {
  local name=$1
  local i
  for i in $(seq 1 36); do
    if ! containerapp_exists "$name"; then
      log "grafana: delete complete for $name"
      return 0
    fi
    log "grafana: waiting for delete to finish ($i/36)..."
    sleep 10
  done
  log "ERROR: timed out waiting for $name to be deleted"
  return 1
}

wait_for_grafana_identity() {
  local name=$1
  local i principal_id
  for i in $(seq 1 24); do
    if containerapp_exists "$name"; then
      principal_id=$(az containerapp show --name "$name" --resource-group "$AZURE_RESOURCE_GROUP" \
        --query identity.principalId -o tsv 2>/dev/null || true)
      if [[ -n "$principal_id" ]]; then
        log "grafana: managed identity ready"
        return 0
      fi
    fi
    log "grafana: waiting for app + identity ($i/24)..."
    sleep 10
  done
  log "WARN: timed out waiting for $name identity"
  return 1
}

log_grafana_deploy_status() {
  local rev
  rev=$(az containerapp show --name "$GRAFANA_APP_NAME" --resource-group "$AZURE_RESOURCE_GROUP" \
    --query "properties.latestRevisionName" -o tsv 2>/dev/null || true)
  az containerapp show --name "$GRAFANA_APP_NAME" --resource-group "$AZURE_RESOURCE_GROUP" \
    --query "{provisioning:properties.provisioningState,running:properties.runningStatus,revision:properties.latestRevisionName,fqdn:properties.configuration.ingress.fqdn}" \
    -o json 2>/dev/null | sed 's/^/[bootstrap-azure] grafana status: /' || true
  if [[ -n "$rev" ]]; then
    az containerapp revision show --name "$GRAFANA_APP_NAME" --resource-group "$AZURE_RESOURCE_GROUP" \
      --revision "$rev" \
      --query "{health:properties.healthState,replicas:properties.replicas,trafficWeight:properties.trafficWeight}" \
      -o json 2>/dev/null | sed 's/^/[bootstrap-azure] grafana revision: /' || true
  fi
}

bind_grafana_acr_registry() {
  az containerapp registry set \
    --name "$GRAFANA_APP_NAME" \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --server "$ACR_LOGIN_SERVER" \
    --identity system \
    --output none 2>/dev/null || true
  log "grafana: registry auth bound ($ACR_LOGIN_SERVER → system identity)"
}

refresh_grafana_after_acr_pull() {
  local rendered=$1
  local i state
  # Do not block on provisioningState — failed image pulls keep it InProgress until AcrPull exists.
  for i in $(seq 1 6); do
    state=$(az containerapp show --name "$GRAFANA_APP_NAME" --resource-group "$AZURE_RESOURCE_GROUP" \
      --query "properties.provisioningState" -o tsv 2>/dev/null || echo "Missing")
    case "$state" in
      Succeeded|Failed) break ;;
      *)
        log "grafana: create finishing ($i/6, state=$state) — AcrPull assigned, will refresh revision next"
        sleep 10
        ;;
    esac
  done
  apply_grafana_update "$rendered"
}

delete_grafana_app() {
  [[ "${GRAFANA_RECREATE:-false}" == "true" ]] || return 0
  containerapp_exists "$GRAFANA_APP_NAME" || return 0
  log "grafana: delete $GRAFANA_APP_NAME (GRAFANA_RECREATE=true)"
  az containerapp delete \
    --name "$GRAFANA_APP_NAME" \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --yes --output none
  wait_for_containerapp_deleted "$GRAFANA_APP_NAME"
  log "grafana: pausing 30s for Azure async cleanup"
  sleep 30
}

create_grafana_app() {
  local rendered=$1
  local attempt out
  for attempt in 1 2 3 4 5 6; do
    if out=$(az containerapp create \
      --name "$GRAFANA_APP_NAME" \
      --resource-group "$AZURE_RESOURCE_GROUP" \
      --yaml "$rendered" \
      --no-wait 2>&1); then
      log "grafana: create accepted (provisioning in background)"
      return 0
    fi
    if echo "$out" | grep -qiE 'AuthorizationFailed|async operation|content hash'; then
      log "grafana: create attempt $attempt failed (Azure async conflict) — retry in 45s"
      sleep 45
      if containerapp_exists "$GRAFANA_APP_NAME"; then
        log "grafana: app exists now — will update instead"
        return 0
      fi
    else
      echo "$out" >&2
      return 1
    fi
  done
  log "ERROR: grafana create failed after $attempt attempts"
  return 1
}

apply_grafana_update() {
  local rendered=$1
  local attempt out
  for attempt in 1 2 3 4 5 6 7 8 9 10 11 12; do
    if out=$(az containerapp update \
      --name "$GRAFANA_APP_NAME" \
      --resource-group "$AZURE_RESOURCE_GROUP" \
      --yaml "$rendered" \
      --no-wait 2>&1); then
      log "grafana: update accepted (provisioning in background)"
      return 0
    fi
    if echo "$out" | grep -qiE 'Operation expired|already in progress|ContainerAppOperationInProgress|active provisioning operation'; then
      log "grafana: update attempt $attempt — Azure operation in progress, retry in 30s"
      sleep 30
      continue
    fi
    echo "$out" >&2
    return 1
  done
  log "WARN: grafana update still blocked after retries — continuing to poll /api/health"
  return 0
}

containerapp_running() {
  [[ "$(az containerapp show --name "$1" --resource-group "$AZURE_RESOURCE_GROUP" \
    --query "properties.runningStatus" -o tsv 2>/dev/null || echo "Missing")" == "Running" ]]
}

containerapp_fqdn() {
  az containerapp show --name "$1" --resource-group "$AZURE_RESOURCE_GROUP" \
    --query "properties.configuration.ingress.fqdn" -o tsv 2>/dev/null || true
}

containerapp_serving() {
  local fqdn
  fqdn=$(containerapp_fqdn "$1")
  [[ -n "$fqdn" ]] && curl -sf --max-time 15 "https://${fqdn}/api/health" >/dev/null 2>&1
}

ensure_grafana_acr_pull() {
  local principal_id acr_id
  principal_id=$(az containerapp show \
    --name "$GRAFANA_APP_NAME" \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --query identity.principalId -o tsv 2>/dev/null || true)
  [[ -z "$principal_id" ]] && { log "WARN: grafana has no managed identity yet"; return 0; }
  acr_id=$(az acr show --name "$ACR_NAME" --query id -o tsv)
  az role assignment create \
    --assignee "$principal_id" \
    --role AcrPull \
    --scope "$acr_id" --output none 2>/dev/null || true
  log "grafana: AcrPull assigned — waiting 45s for role propagation..."
  sleep 45
  bind_grafana_acr_registry
}

restart_grafana_revision() {
  local rev
  rev=$(az containerapp show --name "$GRAFANA_APP_NAME" --resource-group "$AZURE_RESOURCE_GROUP" \
    --query "properties.latestRevisionName" -o tsv 2>/dev/null || true)
  [[ -z "$rev" ]] && return 0
  log "grafana: restart revision $rev"
  az containerapp revision restart \
    --name "$GRAFANA_APP_NAME" \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --revision "$rev" \
    --output none 2>/dev/null || true
}

wait_for_grafana() {
  local fqdn i
  fqdn=$(containerapp_fqdn "$GRAFANA_APP_NAME")
  [[ -z "$fqdn" ]] && { log "WARN: Grafana has no ingress FQDN"; log_grafana_deploy_status; return 1; }
  log "grafana: polling https://${fqdn}/api/health (up to ~10 min)..."
  for i in $(seq 1 40); do
    if curl -sf --max-time 15 "https://${fqdn}/api/health" >/dev/null 2>&1; then
      log "grafana: healthy at https://${fqdn}"
      return 0
    fi
    if (( i == 1 || i % 4 == 0 )); then
      log "grafana: waiting ($i/40)..."
      log_grafana_deploy_status
    else
      log "grafana: waiting ($i/40)..."
    fi
    sleep 15
  done
  log "WARN: Grafana not responding — check replicas and logs:"
  log "  az containerapp replica list -n $GRAFANA_APP_NAME -g $AZURE_RESOURCE_GROUP -o table"
  log "  az containerapp logs show -n $GRAFANA_APP_NAME -g $AZURE_RESOURCE_GROUP --type console --tail 40"
  log_grafana_deploy_status
  return 1
}

acr_image_exists() {
  az acr repository show --name "$ACR_NAME" --image "$1" >/dev/null 2>&1
}

build_image_if_missing() {
  local tag=$1 dockerfile=$2 app_name=${3:-}
  if [[ -n "$app_name" ]] && containerapp_exists "$app_name" \
      && containerapp_running "$app_name" \
      && [[ "${FORCE_IMAGE_BUILD:-false}" != "true" ]]; then
    log "reuse $app_name — skipping $tag build"
    return 0
  fi
  if [[ "${FORCE_IMAGE_BUILD:-false}" != "true" ]] && acr_image_exists "$tag"; then
    log "reuse $ACR_NAME/$tag — skipping build"
    return 0
  fi
  log "building $ACR_NAME/$tag"
  az acr build --registry "$ACR_NAME" --platform linux/amd64 \
    --image "$tag" -f "$dockerfile" "$ROOT"
}

write_grafana_env() {
  local admin_pass="${GRAFANA_ADMIN_PASSWORD:-admin}"
  {
    echo "GRAFANA_APP_NAME=$GRAFANA_APP_NAME"
    echo "GRAFANA_URL=${GRAFANA_URL:-}"
    echo "GRAFANA_ADMIN_USER=admin"
    echo "GRAFANA_ADMIN_PASSWORD=${admin_pass}"
  } >> "$WRITE_ENV_FILE"
}

deploy_grafana() {
  local grafana_image="$ACR_LOGIN_SERVER/grafana:latest"
  local admin_pass="${GRAFANA_ADMIN_PASSWORD:-admin}"

  if [[ "${GRAFANA_SKIP_DELETE:-false}" != "true" ]]; then
    delete_grafana_app
  fi

  if containerapp_exists "$GRAFANA_APP_NAME" \
      && containerapp_serving "$GRAFANA_APP_NAME" \
      && [[ "${FORCE_CONTAINER_DEPLOY:-false}" != "true" ]]; then
    log "grafana: reuse $GRAFANA_APP_NAME — already serving traffic"
    GRAFANA_URL="https://$(containerapp_fqdn "$GRAFANA_APP_NAME")"
    write_grafana_env
    return 0
  fi

  if containerapp_exists "$GRAFANA_APP_NAME" && containerapp_running "$GRAFANA_APP_NAME"; then
    log "WARN: $GRAFANA_APP_NAME is Running in Azure but returns 404 — redeploying"
  fi

  local prom_fqdn prom_url runner_fqdn env_id rendered
  prom_fqdn=$(containerapp_fqdn "$PROM_APP_NAME")
  runner_fqdn=$(containerapp_fqdn "$APP_NAME")
  prom_url="http://prometheus:9090"
  [[ -n "$prom_fqdn" ]] && prom_url="https://${prom_fqdn}"
  [[ -z "$prom_fqdn" && -n "$runner_fqdn" ]] && prom_url="https://${runner_fqdn}"
  env_id=$(az containerapp env show \
    --name "$CAE_NAME" \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --query id -o tsv)
  rendered="$ROOT/infra/grafana.rendered.yaml"
  sed \
    -e "s|__LOCATION__|${AZURE_LOCATION}|g" \
    -e "s|__MANAGED_ENV_ID__|${env_id}|g" \
    -e "s|__ACR_LOGIN_SERVER__|${ACR_LOGIN_SERVER}|g" \
    -e "s|__IMAGE__|${grafana_image}|g" \
    -e "s|__PROMETHEUS_URL__|${prom_url}|g" \
    -e "s|__GRAFANA_ADMIN_PASSWORD__|${admin_pass}|g" \
    "$ROOT/infra/grafana.template.yaml" > "$rendered"
  validate_grafana_yaml "$rendered"

  if ! acr_image_exists "grafana:latest"; then
    log "ERROR: $ACR_LOGIN_SERVER/grafana:latest missing — run: FORCE_IMAGE_BUILD=true ./scripts/bootstrap-azure.sh --grafana-only"
    rm -f "$rendered"
    return 1
  fi

  if containerapp_exists "$GRAFANA_APP_NAME"; then
    log "grafana: update $GRAFANA_APP_NAME (not serving or forced)"
    ensure_grafana_acr_pull
    apply_grafana_update "$rendered"
  else
    log "grafana: create $GRAFANA_APP_NAME"
    create_grafana_app "$rendered"
    wait_for_grafana_identity "$GRAFANA_APP_NAME" || true
    ensure_grafana_acr_pull
    refresh_grafana_after_acr_pull "$rendered"
  fi

  GRAFANA_URL="https://$(containerapp_fqdn "$GRAFANA_APP_NAME")"
  write_grafana_env
  rm -f "$rendered"
  wait_for_grafana || true
}

if [[ "$GRAFANA_ONLY" == "true" ]]; then
  delete_grafana_app
  export GRAFANA_SKIP_DELETE=true
  if [[ "$BUILD_IMAGES" == "true" ]]; then
    if [[ "${FORCE_IMAGE_BUILD:-false}" == "true" ]] || [[ "${GRAFANA_RECREATE:-false}" == "true" ]] \
        || ! acr_image_exists "grafana:latest"; then
      log "building $ACR_NAME/grafana:latest"
      az acr build --registry "$ACR_NAME" --platform linux/amd64 \
        --image "grafana:latest" -f "$ROOT/Dockerfile.grafana" "$ROOT"
    else
      build_image_if_missing "grafana:latest" "$ROOT/Dockerfile.grafana" "$GRAFANA_APP_NAME"
    fi
  fi
  log "self-hosted grafana (grafana-only)"
  deploy_grafana
  echo ""
  echo "Grafana: ${GRAFANA_URL:-n/a}  (login: admin / ${GRAFANA_ADMIN_PASSWORD:-admin})"
  exit 0
fi

BOOTSTRAP_ARGS=(
  --resource-group "$AZURE_RESOURCE_GROUP"
  --location       "$AZURE_LOCATION"
  --acr-name       "$ACR_NAME"
  --cae-name       "$CAE_NAME"
  --app-name       "$APP_NAME"
  --eventhub-ns    "$EH_NS"
  --eventhub-name  "$EH_NAME"
)
[[ "$USE_EXISTING_RG" == "true" ]] && BOOTSTRAP_ARGS+=(--use-existing-rg)

if [[ "$PREFLIGHT" == "true" ]]; then
  chmod +x "$ROOT/infra/bootstrap.sh"
  "$ROOT/infra/bootstrap.sh" "${BOOTSTRAP_ARGS[@]}" --preflight
  log "preflight ok"
  exit 0
fi

log "core infra"
chmod +x "$ROOT/infra/bootstrap.sh"
"$ROOT/infra/bootstrap.sh" \
  "${BOOTSTRAP_ARGS[@]}" \
  --write-env "$WRITE_ENV_FILE" \
  --skip-print-secrets

PROM_REMOTE_WRITE_URL=""
AZURE_PROM_QUERY_URL=""
GRAFANA_URL=""

if [[ "$PROVISION_OBSERVABILITY" == "true" ]]; then
  log "observability"
  for ns in Microsoft.Monitor Microsoft.Dashboard; do
    state=$(az provider show --namespace "$ns" --query registrationState -o tsv 2>/dev/null || echo "NotRegistered")
    if [[ "$state" != "Registered" ]]; then
      if ! az provider register --namespace "$ns" --output none 2>/dev/null; then
        log "WARNING: cannot register $ns (insufficient subscription-level permissions)."
        log "  Ask a subscription Owner to run: az provider register --namespace $ns"
        log "  Skipping Azure Monitor / Managed Grafana provisioning."
        log "  Self-hosted Grafana Container App will still be deployed."
        PROVISION_OBSERVABILITY=false
        break
      fi
    fi
  done
fi

# Re-check: provider registration may have set this to false above.
if [[ "$PROVISION_OBSERVABILITY" == "true" ]]; then
  PROM_WS_NEW=false
  if az monitor account show --name "$PROM_WS" --resource-group "$AZURE_RESOURCE_GROUP" >/dev/null 2>&1; then
    log "prometheus workspace: reuse $PROM_WS — skipping create"
  else
    az monitor account create \
      --name "$PROM_WS" \
      --resource-group "$AZURE_RESOURCE_GROUP" \
      --location "$AZURE_LOCATION" \
      --output none
    PROM_WS_NEW=true
  fi

  AZURE_PROM_QUERY_URL=$(az monitor account show \
    --name "$PROM_WS" --resource-group "$AZURE_RESOURCE_GROUP" \
    --query "metrics.prometheusQueryEndpoint" -o tsv)

  PROM_WORKSPACE_ID=$(az monitor account show \
    --name "$PROM_WS" --resource-group "$AZURE_RESOURCE_GROUP" --query id -o tsv)

  MANAGED_RG="MA_${PROM_WS}_${AZURE_LOCATION}_managed"
  DCR_ID=""
  DCE=""
  fetch_prom_remote_write() {
    DCR_ID=$(az monitor data-collection rule list \
      --resource-group "$MANAGED_RG" \
      --query "[0].immutableId" -o tsv 2>/dev/null || true)
    DCE=$(az monitor data-collection endpoint list \
      --resource-group "$MANAGED_RG" \
      --query "[0].properties.logsIngestion.endpoint" -o tsv 2>/dev/null || true)
  }
  if [[ "$PROM_WS_NEW" == "true" ]]; then
    for _ in $(seq 1 18); do
      fetch_prom_remote_write
      [[ -n "$DCR_ID" && -n "$DCE" ]] && break
      sleep 10
    done
  else
    fetch_prom_remote_write
  fi

  if [[ -n "$DCR_ID" && -n "$DCE" ]]; then
    PROM_REMOTE_WRITE_URL="${DCE}/dataCollectionRules/${DCR_ID}/streamName/Microsoft-PrometheusMetrics/api/v1/write?api-version=2023-04-24"
  else
    log "WARN: PROM_REMOTE_WRITE_URL not detected"
  fi

  az extension add --name amg --upgrade --yes --output none 2>/dev/null || true
  if az grafana show --name "$GRAFANA_NAME" --resource-group "$AZURE_RESOURCE_GROUP" >/dev/null 2>&1; then
    log "managed grafana: reuse $GRAFANA_NAME — skipping provisioning"
    GRAFANA_URL=$(az grafana show --name "$GRAFANA_NAME" --resource-group "$AZURE_RESOURCE_GROUP" \
      --query "properties.endpoint" -o tsv)
  else
    az grafana create \
      --name "$GRAFANA_NAME" \
      --resource-group "$AZURE_RESOURCE_GROUP" \
      --location "$AZURE_LOCATION" \
      --sku Standard \
      --output none

    az grafana integrations add \
      --name "$GRAFANA_NAME" \
      --resource-group "$AZURE_RESOURCE_GROUP" \
      --workspace-id "$PROM_WORKSPACE_ID" \
      --output none 2>/dev/null || true

    GRAFANA_URL=$(az grafana show --name "$GRAFANA_NAME" --resource-group "$AZURE_RESOURCE_GROUP" \
      --query "properties.endpoint" -o tsv)
  fi
fi

ADX_CLUSTER_URI=""
if [[ "$PROVISION_ADX" == "true" ]]; then
  if az kusto cluster show --name "$ADX_CLUSTER" --resource-group "$AZURE_RESOURCE_GROUP" >/dev/null 2>&1; then
    log "adx: reuse $ADX_CLUSTER — skipping provisioning"
    ADX_CLUSTER_URI=$(az kusto cluster show \
      --name "$ADX_CLUSTER" --resource-group "$AZURE_RESOURCE_GROUP" --query uri -o tsv 2>/dev/null || true)
  else
    log "adx database"
    chmod +x "$ROOT/infra/adx-data-connection.sh"
    ADX_OUT=$("$ROOT/infra/adx-data-connection.sh" \
      --resource-group "$AZURE_RESOURCE_GROUP" \
      --location "$AZURE_LOCATION" \
      --cluster-name "$ADX_CLUSTER" \
      --db-name "$ADX_DATABASE" \
      --eventhub-ns "$EH_NS" \
      --eventhub-name "$EH_NAME" \
      --env "$ADX_ENV" 2>&1) || true
    echo "$ADX_OUT"
    ADX_CLUSTER_URI=$(echo "$ADX_OUT" | awk -F= '/^  ADX_CLUSTER_URI=/ {print $2; exit}')
    [[ -z "$ADX_CLUSTER_URI" ]] && ADX_CLUSTER_URI=$(az kusto cluster show \
      --name "$ADX_CLUSTER" --resource-group "$AZURE_RESOURCE_GROUP" --query uri -o tsv 2>/dev/null || true)
  fi
fi

{
  echo ""
  echo "PROM_WS=$PROM_WS"
  echo "PROM_APP_NAME=$PROM_APP_NAME"
  echo "GRAFANA_NAME=$GRAFANA_NAME"
  [[ -n "$PROM_REMOTE_WRITE_URL" ]] && echo "PROM_REMOTE_WRITE_URL=$PROM_REMOTE_WRITE_URL"
  [[ -n "$AZURE_PROM_QUERY_URL" ]] && echo "AZURE_PROM_QUERY_URL=$AZURE_PROM_QUERY_URL"
  [[ -n "$GRAFANA_URL" ]] && echo "GRAFANA_URL=$GRAFANA_URL"
  [[ -n "$ADX_CLUSTER_URI" ]] && echo "ADX_CLUSTER_URI=$ADX_CLUSTER_URI"
  [[ -n "$ADX_DATABASE" ]] && echo "ADX_DATABASE=$ADX_DATABASE"
  echo "OBS_APP_ID=$APP_NAME"
  echo ""
  echo "OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317"
  echo "OTEL_SERVICE_NAME=$APP_NAME"
  echo "OTEL_EXPORT_INTERVAL_MS=30000"
  echo "ENVIRONMENT=dev"
  echo "ALLOW_MOCK_MODE=true"
  echo "PROMETHEUS_PORT=8000"
  echo "HEALTH_PORT=8080"
  echo "BATCH_INTERVAL_S=5"
  echo "BASE_BATCH_SIZE=8"
  echo "ERROR_WINDOW_PROB=0.03"
  echo "ERROR_WINDOW_MIN_S=90"
  echo "ERROR_WINDOW_MAX_S=180"
  echo "SIMULATE_LATENCY=false"
  echo "PII_BACKEND=auto"
  echo "PROMPT_LOG_ENABLED=true"
  echo "EVAL_ENABLED=false"
} >> "$WRITE_ENV_FILE"

if [[ "$BUILD_IMAGES" == "true" ]]; then
  build_image_if_missing "ai-telemetry-runner:latest" "$ROOT/Dockerfile.runner" "$APP_NAME"
  build_image_if_missing "prometheus-scraper:latest" "$ROOT/Dockerfile.prometheus" "$PROM_APP_NAME"
  build_image_if_missing "grafana:latest" "$ROOT/Dockerfile.grafana" "$GRAFANA_APP_NAME"
fi

log "self-hosted grafana"
deploy_grafana

echo ""
echo "Done"
echo "  env    : $WRITE_ENV_FILE"
echo "  grafana: ${GRAFANA_URL:-n/a}  (login: admin / ${GRAFANA_ADMIN_PASSWORD:-admin})"
echo "  adx    : ${ADX_CLUSTER_URI:-n/a} / ${ADX_DATABASE}"
echo ""
echo "  cp $(basename "$WRITE_ENV_FILE") .env"
echo "  ./scripts/deploy-local.sh deploy"
