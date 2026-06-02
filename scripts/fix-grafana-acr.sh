#!/usr/bin/env bash
# Fix Grafana Container App ACR auth (401 / ImagePullBackOff) without delete/recreate.
# Run when fix-grafana.sh fails with FetchingKeyVaultSecretFailed or token exchange 401.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG="${BOOTSTRAP_CONFIG:-$ROOT/azure/bootstrap-azure.env}"
ADMIN_ONLY=false
SKIP_PULL=false

usage() {
  cat <<EOF
Usage: $0 [--admin-only] [--no-git-pull]

  Repairs ACR pull access for the self-hosted Grafana Container App:
    1. Assign AcrPull to the app's managed identity (unless --admin-only)
    2. Wait for RBAC + token propagation
    3. Bind registry (managed identity or ACR admin credentials)
    4. Restart revision and poll /api/health

  Config: azure/bootstrap-azure.env (or BOOTSTRAP_CONFIG)
EOF
}

for arg in "$@"; do
  case "$arg" in
    --admin-only) ADMIN_ONLY=true ;;
    --no-git-pull) SKIP_PULL=true ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $arg" >&2; usage >&2; exit 1 ;;
  esac
done

log() { echo "[fix-grafana-acr] $*"; }

if [[ "$SKIP_PULL" != "true" && -d "$ROOT/.git" ]]; then
  log "Updating repo..."
  git -C "$ROOT" pull --ff-only origin master 2>/dev/null \
    || git -C "$ROOT" pull --ff-only origin main 2>/dev/null \
    || log "WARN: git pull failed — continuing with local copy"
  log "Repo: $(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)"
fi

[[ -f "$CONFIG" ]] || { echo "ERROR: Missing $CONFIG" >&2; exit 1; }

set -a
# shellcheck disable=SC1090
source "$CONFIG"
set +a

: "${AZURE_RESOURCE_GROUP:?Set AZURE_RESOURCE_GROUP in $CONFIG}"
: "${AZURE_SUBSCRIPTION_ID:?Set AZURE_SUBSCRIPTION_ID in $CONFIG}"

ACR_NAME="${ACR_NAME:-acrtelemetrydevaj}"
GRAFANA_APP_NAME="${GRAFANA_APP_NAME:-grafana-telemetry-dev}"
GRAFANA_ACR_ADMIN_FALLBACK="${GRAFANA_ACR_ADMIN_FALLBACK:-true}"

az account set --subscription "$AZURE_SUBSCRIPTION_ID"
az extension add --name containerapp --upgrade --yes --output none 2>/dev/null || true

ACR_LOGIN_SERVER="${ACR_LOGIN_SERVER:-$(az acr show --name "$ACR_NAME" \
  --resource-group "$AZURE_RESOURCE_GROUP" --query loginServer -o tsv 2>/dev/null \
  || az acr show --name "$ACR_NAME" --query loginServer -o tsv)}"

acr_resource_id() {
  az acr show --name "$ACR_NAME" \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --query id -o tsv 2>/dev/null \
    || az acr show --name "$ACR_NAME" --query id -o tsv
}

acr_pull_assigned() {
  local principal_id=$1 acr_id=$2 count
  [[ -n "$principal_id" && -n "$acr_id" ]] || return 1
  count=$(az role assignment list --assignee-object-id "$principal_id" --scope "$acr_id" \
    --query "[?roleDefinitionName=='AcrPull'] | length(@)" -o tsv 2>/dev/null || echo 0)
  [[ "${count:-0}" -gt 0 ]]
}

assign_acr_pull() {
  local principal_id=$1 acr_id=$2 out
  if acr_pull_assigned "$principal_id" "$acr_id"; then
    log "Step 2: AcrPull already assigned for $principal_id"
    return 0
  fi
  log "Step 2: assigning AcrPull to $principal_id ..."
  if ! out=$(az role assignment create \
      --assignee-object-id "$principal_id" \
      --assignee-principal-type ServicePrincipal \
      --role AcrPull \
      --scope "$acr_id" 2>&1); then
    if echo "$out" | grep -qi 'RoleAssignmentExists'; then
      log "Step 2: AcrPull already assigned (concurrent)"
      return 0
    fi
    log "ERROR: AcrPull assignment failed: $out"
    log "Ask a subscription Owner/Contributor to run:"
    echo "  az role assignment create --assignee-object-id $principal_id \\"
    echo "    --assignee-principal-type ServicePrincipal --role AcrPull --scope $acr_id"
    return 1
  fi
  log "Step 2: AcrPull role assignment created"
  return 0
}

wait_for_acr_pull_propagation() {
  local principal_id=$1 acr_id=$2 i
  log "Step 3: waiting for AcrPull + ACR token propagation (up to ~4 min) ..."
  for i in $(seq 1 24); do
    if acr_pull_assigned "$principal_id" "$acr_id"; then
      log "  AcrPull visible in RBAC ($i/24)"
      if (( i >= 10 )); then
        log "Step 3: propagation wait complete"
        return 0
      fi
    else
      log "  waiting for AcrPull to appear ($i/24) ..."
    fi
    sleep 10
  done
  log "WARN: AcrPull not confirmed after 4 min — continuing anyway"
  return 0
}

bind_managed_identity_registry() {
  local out
  log "Step 4: binding registry with managed identity ..."
  if ! out=$(az containerapp registry set \
    --name "$GRAFANA_APP_NAME" \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --server "$ACR_LOGIN_SERVER" \
    --identity system 2>&1); then
    log "WARN: managed-identity registry set failed: $out"
    return 1
  fi
  log "Step 4: registry bound ($ACR_LOGIN_SERVER → system identity)"
  return 0
}

configure_acr_admin_registry() {
  local user pass out
  log "Step 4: configuring ACR admin credentials (sandbox fallback) ..."
  if ! az acr update --name "$ACR_NAME" --admin-enabled true --output none 2>/dev/null; then
    log "ERROR: could not enable ACR admin user on $ACR_NAME"
    return 1
  fi
  user=$(az acr credential show --name "$ACR_NAME" --query username -o tsv 2>/dev/null || true)
  pass=$(az acr credential show --name "$ACR_NAME" --query 'passwords[0].value' -o tsv 2>/dev/null || true)
  [[ -n "$user" && -n "$pass" ]] || { log "ERROR: could not read ACR admin credentials"; return 1; }
  az containerapp secret set \
    --name "$GRAFANA_APP_NAME" \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --secrets "acr-admin-password=$pass" \
    --output none
  if ! out=$(az containerapp registry set \
    --name "$GRAFANA_APP_NAME" \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --server "$ACR_LOGIN_SERVER" \
    --username "$user" \
    --password-secret acr-admin-password 2>&1); then
    log "ERROR: ACR admin registry set failed: $out"
    return 1
  fi
  log "Step 4: ACR admin registry configured"
  return 0
}

restart_grafana_revision() {
  local rev attempt out image
  rev=$(az containerapp show --name "$GRAFANA_APP_NAME" --resource-group "$AZURE_RESOURCE_GROUP" \
    --query "properties.latestRevisionName" -o tsv 2>/dev/null || true)
  if [[ -n "$rev" ]]; then
    log "Step 5: restarting revision $rev ..."
    az containerapp revision restart \
      --name "$GRAFANA_APP_NAME" \
      --resource-group "$AZURE_RESOURCE_GROUP" \
      --revision "$rev" \
      --output none 2>/dev/null || true
    return 0
  fi
  image="${ACR_LOGIN_SERVER}/grafana:latest"
  log "Step 5: no revision yet — triggering deploy with image $image ..."
  for attempt in 1 2 3 4 5 6; do
    if out=$(az containerapp update \
      --name "$GRAFANA_APP_NAME" \
      --resource-group "$AZURE_RESOURCE_GROUP" \
      --image "$image" \
      --no-wait 2>&1); then
      log "Step 5: update accepted"
      return 0
    fi
    if echo "$out" | grep -qiE 'OperationInProgress|active provisioning'; then
      log "  update blocked ($attempt/6) — retry in 30s"
      sleep 30
      continue
    fi
    log "ERROR: update failed: $out"
    return 1
  done
  return 1
}

wait_for_grafana_health() {
  local fqdn=$1 i
  log "Step 6: polling https://${fqdn}/api/health (up to ~10 min) ..."
  for i in $(seq 1 40); do
    if curl -sf --max-time 15 "https://${fqdn}/api/health" >/dev/null 2>&1; then
      log "Grafana is healthy: https://${fqdn}"
      echo ""
      echo "Open: https://${fqdn}  (login: admin / ${GRAFANA_ADMIN_PASSWORD:-admin})"
      return 0
    fi
    if (( i == 1 || i % 4 == 0 )); then
      log "  waiting ($i/40) ..."
      az containerapp show --name "$GRAFANA_APP_NAME" --resource-group "$AZURE_RESOURCE_GROUP" \
        --query "{provisioning:properties.provisioningState,running:properties.runningStatus,revision:properties.latestRevisionName}" \
        -o json 2>/dev/null | sed 's/^/[fix-grafana-acr]   /' || true
    fi
    sleep 15
  done
  return 1
}

# ── main ─────────────────────────────────────────────────────────────────────

log "Grafana ACR auth repair for $GRAFANA_APP_NAME in $AZURE_RESOURCE_GROUP"
log "ACR: $ACR_LOGIN_SERVER"

if ! az containerapp show --name "$GRAFANA_APP_NAME" --resource-group "$AZURE_RESOURCE_GROUP" >/dev/null 2>&1; then
  log "ERROR: Container App $GRAFANA_APP_NAME does not exist."
  log "Run: ./scripts/fix-grafana.sh   (creates the app first)"
  exit 1
fi

if ! az acr repository show --name "$ACR_NAME" --image grafana:latest >/dev/null 2>&1; then
  log "ERROR: $ACR_LOGIN_SERVER/grafana:latest not found in ACR."
  log "Run: FORCE_IMAGE_BUILD=true ./scripts/bootstrap-azure.sh --grafana-only"
  exit 1
fi

log "Step 1: current app status"
az containerapp show --name "$GRAFANA_APP_NAME" --resource-group "$AZURE_RESOURCE_GROUP" \
  --query "{status:properties.runningStatus,fqdn:properties.configuration.ingress.fqdn,principalId:identity.principalId,revision:properties.latestRevisionName}" \
  -o json

PRINCIPAL_ID=$(az containerapp show --name "$GRAFANA_APP_NAME" --resource-group "$AZURE_RESOURCE_GROUP" \
  --query identity.principalId -o tsv 2>/dev/null || true)
ACR_ID=$(acr_resource_id)

if [[ -z "$PRINCIPAL_ID" && "$ADMIN_ONLY" != "true" ]]; then
  log "ERROR: Grafana has no system-assigned managed identity."
  log "Try: ./scripts/fix-grafana-acr.sh --admin-only"
  exit 1
fi

REGISTRY_OK=false
if [[ "$ADMIN_ONLY" == "true" ]]; then
  configure_acr_admin_registry && REGISTRY_OK=true
else
  if assign_acr_pull "$PRINCIPAL_ID" "$ACR_ID"; then
    wait_for_acr_pull_propagation "$PRINCIPAL_ID" "$ACR_ID"
    bind_managed_identity_registry && REGISTRY_OK=true
  fi
  if [[ "$REGISTRY_OK" != "true" && "$GRAFANA_ACR_ADMIN_FALLBACK" == "true" ]]; then
    log "Managed identity path failed — trying ACR admin fallback ..."
    configure_acr_admin_registry && REGISTRY_OK=true
  fi
fi

if [[ "$REGISTRY_OK" != "true" ]]; then
  log "ERROR: could not configure ACR registry auth."
  log "Recent system logs:"
  az containerapp logs show --name "$GRAFANA_APP_NAME" --resource-group "$AZURE_RESOURCE_GROUP" \
    --type system --tail 20 2>/dev/null || true
  exit 1
fi

restart_grafana_revision

FQDN=$(az containerapp show --name "$GRAFANA_APP_NAME" --resource-group "$AZURE_RESOURCE_GROUP" \
  --query "properties.configuration.ingress.fqdn" -o tsv 2>/dev/null || true)
[[ -z "$FQDN" ]] && { log "ERROR: Grafana has no ingress FQDN"; exit 1; }

if wait_for_grafana_health "$FQDN"; then
  exit 0
fi

log "Grafana still not healthy. Diagnostics:"
echo "  az containerapp replica list -n $GRAFANA_APP_NAME -g $AZURE_RESOURCE_GROUP -o table"
echo "  az containerapp logs show -n $GRAFANA_APP_NAME -g $AZURE_RESOURCE_GROUP --type system --tail 30"
az containerapp replica list --name "$GRAFANA_APP_NAME" --resource-group "$AZURE_RESOURCE_GROUP" -o table 2>/dev/null \
  || log "  (no replicas)"
exit 1
