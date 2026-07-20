#!/usr/bin/env bash
# Bring a Stopped / 0-replica Grafana Container App back online (fixes the 404
# you get when properties.runningStatus == "Stopped"). Starts the app, waits for
# a running replica, HTTP-probes the ingress, and — if it still won't serve —
# dumps console logs and can force a revision restart.
#
# Usage:
#   ./scripts/start-grafana-azure.sh              # start + verify + probe
#   ./scripts/start-grafana-azure.sh --restart    # also force-restart latest revision
#   ./scripts/start-grafana-azure.sh --logs       # just show status + recent console logs
#
# Config: reads azure/bootstrap-azure.env (override with BOOTSTRAP_CONFIG=...).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG="${BOOTSTRAP_CONFIG:-$ROOT/azure/bootstrap-azure.env}"

log()  { echo "[start-grafana] $*"; }
fail() { echo "[start-grafana] ERROR: $*" >&2; exit 1; }

FORCE_RESTART=false
LOGS_ONLY=false
for arg in "$@"; do
  case "$arg" in
    --restart) FORCE_RESTART=true ;;
    --logs)    LOGS_ONLY=true ;;
    -h|--help) grep -E '^#( |$)' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) fail "unknown arg: $arg" ;;
  esac
done

command -v az >/dev/null 2>&1 || fail "az CLI not found."

# Self-update from the observability repo (github.com/ajaykhannaus/observability)
# so the VM always runs the latest fix — same pattern as fix-grafana.sh.
if [[ "$LOGS_ONLY" != "true" && -d "$ROOT/.git" ]]; then
  log "Updating repo from origin (observability)..."
  if ! git -C "$ROOT" pull --ff-only origin master 2>/dev/null \
      && ! git -C "$ROOT" pull --ff-only origin main 2>/dev/null; then
    log "WARN: git pull failed — continuing with local copy."
  fi
  log "Repo: $(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)"
fi

[[ -f "$CONFIG" ]] || fail "Missing $CONFIG"

set -a
# shellcheck disable=SC1090
source "$CONFIG"
set +a

: "${AZURE_RESOURCE_GROUP:?Set AZURE_RESOURCE_GROUP in $CONFIG}"
RG="$AZURE_RESOURCE_GROUP"
APP="${GRAFANA_APP_NAME:-${GRAFANA_NAME:-grafana-telemetry-dev}}"
POLL_TIMEOUT="${POLL_TIMEOUT:-150}"   # seconds to wait for Running + replica
LOG_TAIL="${LOG_TAIL:-60}"

az account show >/dev/null 2>&1 || fail "Not logged in. Run: az login"
if [[ -n "${AZURE_SUBSCRIPTION_ID:-}" ]]; then
  az account set --subscription "$AZURE_SUBSCRIPTION_ID" \
    || fail "Cannot switch to subscription $AZURE_SUBSCRIPTION_ID (wrong tenant? run 'az login')."
fi

az containerapp show -n "$APP" -g "$RG" >/dev/null 2>&1 \
  || fail "Container App '$APP' not found in RG '$RG'. Deploy it first (bootstrap-azure.sh --grafana-only)."

show_status() {
  az containerapp show -n "$APP" -g "$RG" \
    --query "{running:properties.runningStatus, provisioning:properties.provisioningState, revision:properties.latestRevisionName, fqdn:properties.configuration.ingress.fqdn}" \
    -o json
}

running_status() {
  az containerapp show -n "$APP" -g "$RG" --query "properties.runningStatus" -o tsv 2>/dev/null || echo "Unknown"
}

replica_count() {
  az containerapp replica list -n "$APP" -g "$RG" --query "length(@)" -o tsv 2>/dev/null || echo "0"
}

fqdn() {
  az containerapp show -n "$APP" -g "$RG" --query "properties.configuration.ingress.fqdn" -o tsv 2>/dev/null || echo ""
}

dump_logs() {
  log "Recent console logs (tail $LOG_TAIL):"
  az containerapp logs show -n "$APP" -g "$RG" --type console --tail "$LOG_TAIL" 2>/dev/null \
    || log "  (no console logs available)"
}

log "App: $APP   RG: $RG   Sub: ${AZURE_SUBSCRIPTION_ID:-<current>}"
log "Current status:"
show_status

if [[ "$LOGS_ONLY" == "true" ]]; then
  log "Replicas:"
  az containerapp replica list -n "$APP" -g "$RG" -o table 2>/dev/null || log "  (none)"
  dump_logs
  exit 0
fi

# --- Start the app if it is not already Running --------------------------------
STATUS="$(running_status)"
if [[ "$STATUS" != "Running" ]]; then
  log "runningStatus=$STATUS -> starting app..."
  az containerapp start -n "$APP" -g "$RG" -o none \
    || fail "az containerapp start failed."
else
  log "App already reports Running."
fi

# --- Optional forced revision restart -----------------------------------------
if [[ "$FORCE_RESTART" == "true" ]]; then
  REV="$(az containerapp show -n "$APP" -g "$RG" --query "properties.latestRevisionName" -o tsv 2>/dev/null || echo "")"
  if [[ -n "$REV" ]]; then
    log "Force-restarting revision $REV ..."
    az containerapp revision restart -n "$APP" -g "$RG" --revision "$REV" -o none \
      || log "WARN: revision restart failed (continuing)."
  fi
fi

# --- Poll for Running + at least one replica ----------------------------------
log "Waiting up to ${POLL_TIMEOUT}s for Running status and a live replica..."
deadline=$(( $(date +%s) + POLL_TIMEOUT ))
while :; do
  st="$(running_status)"
  rc="$(replica_count)"
  if [[ "$st" == "Running" && "${rc:-0}" -ge 1 ]]; then
    log "OK: runningStatus=Running, replicas=$rc"
    break
  fi
  if (( $(date +%s) >= deadline )); then
    log "WARN: still not ready (runningStatus=$st, replicas=${rc:-0})."
    log "Replicas:"
    az containerapp replica list -n "$APP" -g "$RG" -o table 2>/dev/null || log "  (none)"
    dump_logs
    fail "Grafana did not reach a running replica. Fix the error above, then retry (or run with --restart)."
  fi
  sleep 5
done

# --- HTTP probe the ingress ----------------------------------------------------
URL_HOST="$(fqdn)"
[[ -n "$URL_HOST" ]] || fail "No ingress FQDN — is external ingress enabled on the app?"
URL="https://$URL_HOST"

log "Probing $URL ..."
code=""
for _ in $(seq 1 12); do
  code="$(curl -s -o /dev/null -w '%{http_code}' -m 10 "$URL/api/health" 2>/dev/null || echo 000)"
  [[ "$code" == "200" ]] && break
  # /api/health may redirect on some setups; a 200/302 on root also means it's up
  code="$(curl -s -o /dev/null -w '%{http_code}' -m 10 "$URL/login" 2>/dev/null || echo 000)"
  [[ "$code" == "200" || "$code" == "302" ]] && break
  sleep 5
done

echo ""
echo "════════════════════════════════════════════════════════════"
if [[ "$code" == "200" || "$code" == "302" ]]; then
  echo "  Grafana is UP  (HTTP $code)"
else
  echo "  Grafana replica is running but HTTP probe returned: ${code:-000}"
  echo "  (cold start can take a moment — reload the URL; if it persists, run --logs)"
fi
echo "  URL   : $URL   (login: admin / admin)"
echo "════════════════════════════════════════════════════════════"
