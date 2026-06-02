#!/usr/bin/env bash
# Fix Grafana Container App ACR auth (401 / ImagePullBackOff) without delete/recreate.
# Run when fix-grafana.sh fails with FetchingKeyVaultSecretFailed or token exchange 401.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG="${BOOTSTRAP_CONFIG:-$ROOT/azure/bootstrap-azure.env}"
USE_MANAGED_IDENTITY=false
SKIP_PULL=false

usage() {
  cat <<EOF
Usage: $0 [--try-managed-identity] [--no-git-pull]

  Fixes ACR pull for Grafana (default: ACR admin credentials — most reliable in sandbox):
    1. Remove broken managed-identity registry config (if present)
    2. Enable ACR admin + store password as Container App secret
    3. Bind registry with username/password
    4. Force new revision + poll /api/health

  Use --try-managed-identity to attempt AcrPull + system identity first (slower).

  Config: azure/bootstrap-azure.env (or BOOTSTRAP_CONFIG)
EOF
}

for arg in "$@"; do
  case "$arg" in
    --try-managed-identity) USE_MANAGED_IDENTITY=true ;;
    --admin-only) ;; # legacy alias — admin is already the default
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

az account set --subscription "$AZURE_SUBSCRIPTION_ID"
az extension add --name containerapp --upgrade --yes --output none 2>/dev/null || true

ACR_LOGIN_SERVER="${ACR_LOGIN_SERVER:-$(az acr show --name "$ACR_NAME" \
  --resource-group "$AZURE_RESOURCE_GROUP" --query loginServer -o tsv 2>/dev/null \
  || az acr show --name "$ACR_NAME" --query loginServer -o tsv)}"

show_registry_config() {
  log "Current registry config:"
  az containerapp registry list \
    --name "$GRAFANA_APP_NAME" \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    -o json 2>/dev/null | sed 's/^/[fix-grafana-acr]   /' || log "   (none)"
}

remove_registry_config() {
  log "Removing existing registry config for $ACR_LOGIN_SERVER ..."
  az containerapp registry remove \
    --name "$GRAFANA_APP_NAME" \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --server "$ACR_LOGIN_SERVER" \
    --output none 2>/dev/null || true
}

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
    log "AcrPull already assigned for $principal_id"
    return 0
  fi
  log "Assigning AcrPull to $principal_id ..."
  if ! out=$(az role assignment create \
      --assignee-object-id "$principal_id" \
      --assignee-principal-type ServicePrincipal \
      --role AcrPull \
      --scope "$acr_id" 2>&1); then
    if echo "$out" | grep -qi 'RoleAssignmentExists'; then
      return 0
    fi
    log "ERROR: AcrPull assignment failed: $out"
    return 1
  fi
  log "AcrPull role assignment created"
  return 0
}

wait_for_acr_pull_propagation() {
  local principal_id=$1 acr_id=$2 i
  log "Waiting for AcrPull + token propagation (up to ~4 min) ..."
  for i in $(seq 1 24); do
    if acr_pull_assigned "$principal_id" "$acr_id"; then
      log "  AcrPull visible ($i/24)"
      (( i >= 10 )) && return 0
    fi
    sleep 10
  done
  return 1
}

configure_managed_identity_registry() {
  local out
  remove_registry_config
  log "Binding registry with managed identity ..."
  if ! out=$(az containerapp registry set \
    --name "$GRAFANA_APP_NAME" \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --server "$ACR_LOGIN_SERVER" \
    --identity system 2>&1); then
    log "WARN: managed-identity registry set failed: $out"
    return 1
  fi
  show_registry_config
  return 0
}

configure_acr_admin_registry() {
  local user pass out grafana_pass
  grafana_pass="${GRAFANA_ADMIN_PASSWORD:-admin}"
  remove_registry_config
  log "Enabling ACR admin user on $ACR_NAME ..."
  if ! az acr update --name "$ACR_NAME" --admin-enabled true --output none 2>&1; then
    log "ERROR: could not enable ACR admin user (need Contributor on ACR)"
    return 1
  fi
  user=$(az acr credential show --name "$ACR_NAME" --query username -o tsv 2>/dev/null || true)
  pass=$(az acr credential show --name "$ACR_NAME" --query 'passwords[0].value' -o tsv 2>/dev/null || true)
  [[ -n "$user" && -n "$pass" ]] || { log "ERROR: could not read ACR admin credentials"; return 1; }

  log "Storing secrets (grafana-admin-password + acr-admin-password) ..."
  if ! out=$(az containerapp secret set \
    --name "$GRAFANA_APP_NAME" \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --secrets "grafana-admin-password=$grafana_pass" "acr-admin-password=$pass" 2>&1); then
    log "ERROR: secret set failed: $out"
    return 1
  fi

  log "Binding registry with admin username/password ..."
  if ! out=$(az containerapp registry set \
    --name "$GRAFANA_APP_NAME" \
    --resource-group "$AZURE_RESOURCE_GROUP" \
    --server "$ACR_LOGIN_SERVER" \
    --username "$user" \
    --password-secret acr-admin-password 2>&1); then
    log "ERROR: ACR admin registry set failed: $out"
    return 1
  fi
  show_registry_config
  log "ACR admin registry configured (no managed identity)"
  return 0
}

system_logs_show_acr_401() {
  az containerapp logs show --name "$GRAFANA_APP_NAME" --resource-group "$AZURE_RESOURCE_GROUP" \
    --type system --tail 25 2>/dev/null \
    | grep -qiE '401|token exchange|FetchingKeyVaultSecretFailed|managed identity'
}

force_grafana_image_pull() {
  local image="${ACR_LOGIN_SERVER}/grafana:latest" attempt out rev
  log "Forcing new revision to pull $image ..."
  for attempt in 1 2 3 4 5 6 7 8; do
    if out=$(az containerapp update \
      --name "$GRAFANA_APP_NAME" \
      --resource-group "$AZURE_RESOURCE_GROUP" \
      --image "$image" \
      --no-wait 2>&1); then
      log "Revision update accepted (attempt $attempt)"
      return 0
    fi
    if echo "$out" | grep -qiE 'OperationInProgress|active provisioning'; then
      log "  Azure operation in progress ($attempt/8) — wait 30s"
      sleep 30
      continue
    fi
    log "WARN: update failed: $out"
    break
  done
  rev=$(az containerapp show --name "$GRAFANA_APP_NAME" --resource-group "$AZURE_RESOURCE_GROUP" \
    --query "properties.latestRevisionName" -o tsv 2>/dev/null || true)
  if [[ -n "$rev" ]]; then
    log "Falling back to revision restart: $rev"
    az containerapp revision restart \
      --name "$GRAFANA_APP_NAME" \
      --resource-group "$AZURE_RESOURCE_GROUP" \
      --revision "$rev" \
      --output none 2>/dev/null || true
    return 0
  fi
  return 1
}

wait_for_grafana_health() {
  local fqdn=$1 i
  log "Polling https://${fqdn}/api/health (up to ~10 min) ..."
  for i in $(seq 1 40); do
    if curl -sf --max-time 15 "https://${fqdn}/api/health" >/dev/null 2>&1; then
      log "Grafana is healthy: https://${fqdn}"
      echo ""
      echo "Open: https://${fqdn}  (login: admin / ${GRAFANA_ADMIN_PASSWORD:-admin})"
      return 0
    fi
    if (( i == 1 || i % 4 == 0 )); then
      log "  waiting ($i/40) ..."
      if system_logs_show_acr_401; then
        log "  WARN: system logs still show ACR 401 — managed identity may still be active"
      fi
    fi
    sleep 15
  done
  return 1
}

repair_with_admin() {
  configure_acr_admin_registry
  force_grafana_image_pull
}

repair_with_managed_identity() {
  local principal_id acr_id
  principal_id=$(az containerapp show --name "$GRAFANA_APP_NAME" --resource-group "$AZURE_RESOURCE_GROUP" \
    --query identity.principalId -o tsv 2>/dev/null || true)
  [[ -n "$principal_id" ]] || { log "ERROR: no managed identity on app"; return 1; }
  acr_id=$(acr_resource_id)
  assign_acr_pull "$principal_id" "$acr_id" || return 1
  wait_for_acr_pull_propagation "$principal_id" "$acr_id" || true
  configure_managed_identity_registry || return 1
  force_grafana_image_pull
}

# ── main ─────────────────────────────────────────────────────────────────────

log "Grafana ACR auth repair for $GRAFANA_APP_NAME"
log "ACR: $ACR_LOGIN_SERVER"
log "Mode: $([[ "$USE_MANAGED_IDENTITY" == "true" ]] && echo managed-identity || echo admin-credentials)"

if ! az containerapp show --name "$GRAFANA_APP_NAME" --resource-group "$AZURE_RESOURCE_GROUP" >/dev/null 2>&1; then
  log "ERROR: Container App $GRAFANA_APP_NAME does not exist. Run: ./scripts/fix-grafana.sh"
  exit 1
fi

if ! az acr repository show --name "$ACR_NAME" --image grafana:latest >/dev/null 2>&1; then
  log "ERROR: $ACR_LOGIN_SERVER/grafana:latest not in ACR."
  log "Run: FORCE_IMAGE_BUILD=true ./scripts/bootstrap-azure.sh --grafana-only"
  exit 1
fi

log "Step 1: app status"
az containerapp show --name "$GRAFANA_APP_NAME" --resource-group "$AZURE_RESOURCE_GROUP" \
  --query "{status:properties.runningStatus,fqdn:properties.configuration.ingress.fqdn,principalId:identity.principalId,revision:properties.latestRevisionName}" \
  -o json
show_registry_config

if [[ "$USE_MANAGED_IDENTITY" == "true" ]]; then
  if ! repair_with_managed_identity; then
    log "Managed identity failed — switching to ACR admin ..."
    repair_with_admin
  fi
else
  repair_with_admin
fi

FQDN=$(az containerapp show --name "$GRAFANA_APP_NAME" --resource-group "$AZURE_RESOURCE_GROUP" \
  --query "properties.configuration.ingress.fqdn" -o tsv 2>/dev/null || true)
[[ -z "$FQDN" ]] && { log "ERROR: no ingress FQDN"; exit 1; }

if wait_for_grafana_health "$FQDN"; then
  exit 0
fi

log "Still not healthy. Recent system logs:"
az containerapp logs show --name "$GRAFANA_APP_NAME" --resource-group "$AZURE_RESOURCE_GROUP" \
  --type system --tail 20 2>/dev/null || true
log "Replicas:"
az containerapp replica list --name "$GRAFANA_APP_NAME" --resource-group "$AZURE_RESOURCE_GROUP" -o table 2>/dev/null \
  || log "  (no replicas)"
exit 1
