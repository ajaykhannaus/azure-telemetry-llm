#!/usr/bin/env bash
# Start the ENTIRE telemetry stack when its Container Apps come up Stopped after a
# redeploy (symptom: Grafana loads but panels show "No data" + a JSON parse error
# like `ReadObject: expect { but found <` — the Prometheus/Loki datasource apps
# are returning the Azure "Error 404 - Container App is stopped" HTML page).
#
# Uses the ARM Start action via `az rest` (core CLI, no containerapp extension
# needed), which reliably un-stops an explicitly Stopped app — `az containerapp
# start` may be missing on old CLIs and `az containerapp update` does NOT un-stop.
#
# Usage:
#   ./scripts/start-telemetry-stack-azure.sh            # start runner, otel, prom, loki, tempo, grafana
#   ./scripts/start-telemetry-stack-azure.sh --status   # just show runningStatus of each app
#
# Config: reads azure/bootstrap-azure.env (override with BOOTSTRAP_CONFIG=...).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CONFIG="${BOOTSTRAP_CONFIG:-$ROOT/azure/bootstrap-azure.env}"

log()  { echo "[start-stack] $*"; }
fail() { echo "[start-stack] ERROR: $*" >&2; exit 1; }

STATUS_ONLY=false
for arg in "$@"; do
  case "$arg" in
    --status)  STATUS_ONLY=true ;;
    -h|--help) grep -E '^#( |$)' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) fail "unknown arg: $arg" ;;
  esac
done

command -v az >/dev/null 2>&1 || fail "az CLI not found."

if [[ "$STATUS_ONLY" != "true" && -d "$ROOT/.git" ]]; then
  log "Updating repo from origin..."
  git -C "$ROOT" pull --ff-only origin master 2>/dev/null \
    || git -C "$ROOT" pull --ff-only origin main 2>/dev/null \
    || log "WARN: git pull failed — continuing with local copy."
fi

[[ -f "$CONFIG" ]] || fail "Missing $CONFIG"
set -a
# shellcheck disable=SC1090
source "$CONFIG"
set +a

: "${AZURE_RESOURCE_GROUP:?Set AZURE_RESOURCE_GROUP in $CONFIG}"
RG="$AZURE_RESOURCE_GROUP"

az account show >/dev/null 2>&1 || fail "Not logged in. Run: az login"
if [[ -n "${AZURE_SUBSCRIPTION_ID:-}" ]]; then
  az account set --subscription "$AZURE_SUBSCRIPTION_ID" \
    || fail "Cannot switch to subscription $AZURE_SUBSCRIPTION_ID (wrong tenant? run 'az login')."
fi
SUB="${AZURE_SUBSCRIPTION_ID:-$(az account show --query id -o tsv)}"

# Stack apps in start order: data-plane first, Grafana last. Defaults match
# bootstrap-azure.sh; overridable via the same env vars in the config file.
APPS=(
  "${APP_NAME:-ai-telemetry-runner-dev}"
  "${OTEL_APP_NAME:-otel-collector-dev}"
  "${PROM_APP_NAME:-prometheus-scraper-dev}"
  "${LOKI_APP_NAME:-loki-telemetry-dev}"
  "${TEMPO_APP_NAME:-tempo-telemetry-dev}"
  "${GRAFANA_APP_NAME:-${GRAFANA_NAME:-grafana-telemetry-dev}}"
)

running_status() {
  az containerapp show -n "$1" -g "$RG" --query "properties.runningStatus" -o tsv 2>/dev/null || echo "Missing"
}

arm_start() {
  local app="$1" err=/tmp/ss_err.$$
  for api in 2024-03-01 2023-05-01 2022-10-01; do
    if az rest --method post -o none 2>"$err" \
        --url "https://management.azure.com/subscriptions/${SUB}/resourceGroups/${RG}/providers/Microsoft.App/containerApps/${app}/start?api-version=${api}"; then
      rm -f "$err"; return 0
    fi
  done
  sed 's/^/    /' "$err" >&2; rm -f "$err"; return 1
}

log "RG: $RG   Sub: $SUB"

if [[ "$STATUS_ONLY" == "true" ]]; then
  printf '%-32s %s\n' "APP" "runningStatus"
  for app in "${APPS[@]}"; do printf '%-32s %s\n' "$app" "$(running_status "$app")"; done
  exit 0
fi

failed=()
for app in "${APPS[@]}"; do
  st="$(running_status "$app")"
  if [[ "$st" == "Missing" ]]; then
    log "SKIP $app (not found in $RG)"
    continue
  fi
  if [[ "$st" == "Running" ]]; then
    log "OK   $app already Running"
    continue
  fi
  log "START $app (was $st)..."
  if arm_start "$app"; then
    log "  -> start action accepted for $app"
  else
    log "  -> FAILED to start $app"
    failed+=("$app")
  fi
done

echo ""
log "Post-start status (allow ~30-90s for replicas + first scrape/flush):"
printf '%-32s %s\n' "APP" "runningStatus"
for app in "${APPS[@]}"; do
  st="$(running_status "$app")"; [[ "$st" == "Missing" ]] && continue
  printf '%-32s %s\n' "$app" "$st"
done

GRAFANA_FQDN="$(az containerapp show -n "${GRAFANA_APP_NAME:-${GRAFANA_NAME:-grafana-telemetry-dev}}" -g "$RG" \
  --query "properties.configuration.ingress.fqdn" -o tsv 2>/dev/null || echo "")"
echo ""
echo "════════════════════════════════════════════════════════════"
[[ -n "$GRAFANA_FQDN" ]] && echo "  Grafana : https://$GRAFANA_FQDN   (login: admin / admin)"
if ((${#failed[@]})); then
  echo "  WARN: could not start: ${failed[*]}"
  echo "        (check RBAC: needs Microsoft.App/containerApps/start/action, or the app may not exist)"
else
  echo "  All present stack apps issued a start. Wait ~1-2 min, then refresh Grafana."
fi
echo "════════════════════════════════════════════════════════════"
