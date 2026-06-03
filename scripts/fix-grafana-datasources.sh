#!/usr/bin/env bash
# Create/update Grafana Prometheus, Loki, and Tempo datasources (Azure internal HTTPS URLs).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lib/azure-deploy-common.sh
source "$ROOT/scripts/lib/azure-deploy-common.sh"
ENV_FILE="${ENV_FILE:-$ROOT/.env.azure}"

log() { echo "[fix-grafana-ds] $*"; }

[[ -f "$ENV_FILE" ]] || { log "ERROR: Missing $ENV_FILE"; exit 1; }

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

: "${AZURE_RESOURCE_GROUP:?Set AZURE_RESOURCE_GROUP in $ENV_FILE}"
: "${AZURE_SUBSCRIPTION_ID:?Set AZURE_SUBSCRIPTION_ID in $ENV_FILE}"

CAE_NAME="${CAE_NAME:-cae-telemetry-dev}"
PROM_APP_NAME="${PROM_APP_NAME:-prometheus-scraper-dev}"
LOKI_APP_NAME="${LOKI_APP_NAME:-loki-telemetry-dev}"
TEMPO_APP_NAME="${TEMPO_APP_NAME:-tempo-telemetry-dev}"
GRAFANA_APP_NAME="${GRAFANA_APP_NAME:-grafana-telemetry-dev}"
GRAFANA_ADMIN_PASSWORD="${GRAFANA_ADMIN_PASSWORD:-admin}"

az account set --subscription "$AZURE_SUBSCRIPTION_ID"
az extension add --name containerapp --upgrade --yes --output none 2>/dev/null || true

GRAFANA_FQDN=$(az containerapp show --name "$GRAFANA_APP_NAME" --resource-group "$AZURE_RESOURCE_GROUP" \
  --query "properties.configuration.ingress.fqdn" -o tsv 2>/dev/null || true)
[[ -n "$GRAFANA_FQDN" ]] || { log "ERROR: Grafana $GRAFANA_APP_NAME has no FQDN"; exit 1; }

GRAFANA_URL="https://${GRAFANA_FQDN}"
mapfile -t _DS_URLS < <(grafana_datasource_urls \
  "$CAE_NAME" "$AZURE_RESOURCE_GROUP" "$PROM_APP_NAME" "$LOKI_APP_NAME" "$TEMPO_APP_NAME")
DS_PROM="${_DS_URLS[0]:-}"
DS_LOKI="${_DS_URLS[1]:-}"
DS_TEMPO="${_DS_URLS[2]:-}"

validate_ds_url() {
  local label=$1 url=$2
  [[ -n "$url" && "$url" == https://* ]] || {
    log "ERROR: invalid $label URL: '${url:-empty}'"
    exit 1
  }
}
validate_ds_url Prometheus "$DS_PROM"
validate_ds_url Loki "$DS_LOKI"
validate_ds_url Tempo "$DS_TEMPO"

log "Target Grafana: $GRAFANA_URL"
log "  Prometheus → $DS_PROM"
log "  Loki       → $DS_LOKI"
log "  Tempo      → $DS_TEMPO"

log "Updating Grafana Container App env vars (for provisioning on restart) ..."
az containerapp update \
  --name "$GRAFANA_APP_NAME" \
  --resource-group "$AZURE_RESOURCE_GROUP" \
  --set-env-vars \
    "PROMETHEUS_URL=${DS_PROM}" \
    "LOKI_URL=${DS_LOKI}" \
    "TEMPO_URL=${DS_TEMPO}" \
  --output none

log "Configuring datasources via Grafana API ..."
python3 - "$GRAFANA_URL" "$GRAFANA_ADMIN_PASSWORD" "$DS_PROM" "$DS_LOKI" "$DS_TEMPO" <<'PY'
import base64
import json
import sys
import urllib.error
import urllib.request

grafana, password, prom_url, loki_url, tempo_url = sys.argv[1:6]
auth = base64.b64encode(f"admin:{password}".encode()).decode()

def req(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(f"{grafana}{path}", data=data, method=method)
    r.add_header("Content-Type", "application/json")
    r.add_header("Authorization", f"Basic {auth}")
    try:
        with urllib.request.urlopen(r, timeout=45) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode() if exc.fp else ""
        raise SystemExit(f"{method} {path} → HTTP {exc.code}: {detail}") from exc

# Auth check
try:
    req("GET", "/api/datasources")
except SystemExit as exc:
    raise SystemExit(f"Grafana API auth failed at {grafana} — check GRAFANA_ADMIN_PASSWORD") from exc

def remove_existing(uid, name):
    for ds in req("GET", "/api/datasources"):
        if ds.get("uid") == uid or ds.get("name") == name:
            req("DELETE", f"/api/datasources/uid/{ds['uid']}")
            print(f"  removed old {name} (uid={ds.get('uid')})")

def create(name, ds_type, uid, url, extra_json=None, is_default=False):
    remove_existing(uid, name)
    payload = {
        "name": name,
        "type": ds_type,
        "access": "proxy",
        "url": url,
        "uid": uid,
        "orgId": 1,
        "isDefault": is_default,
        "jsonData": {"tlsSkipVerify": True, **(extra_json or {})},
    }
    result = req("POST", "/api/datasources", payload)
    print(f"  created {name} → {url} (id={result.get('datasource', {}).get('id', result.get('id', '?'))})")

# Order: Prometheus → Tempo → Loki (Loki derivedFields reference Tempo)
create("Prometheus", "prometheus", "prometheus-ds", prom_url, {
    "timeInterval": "10s",
    "exemplarTraceIdDestinations": [{"name": "trace_id", "datasourceUid": "tempo-ds"}],
}, is_default=True)
create("Tempo", "tempo", "tempo-ds", tempo_url, {
    "tracesToLogsV2": {"datasourceUid": "loki-ds", "filterByTraceID": True},
    "tracesToMetrics": {"datasourceUid": "prometheus-ds"},
    "serviceMap": {"datasourceUid": "prometheus-ds"},
    "lokiSearch": {"datasourceUid": "loki-ds"},
})
create("Loki", "loki", "loki-ds", loki_url, {
    "derivedFields": [{
        "datasourceUid": "tempo-ds",
        "matcherRegex": '"trace_id":"([a-f0-9]{32})"',
        "name": "trace_id",
        "url": "${__value.raw}",
    }],
})

print("\nDatasources in Grafana:")
for ds in req("GET", "/api/datasources"):
    uid = ds.get("uid", "?")
    url = ds.get("url", "?")
    ds_type = ds.get("type", "")
    if ds_type == "tempo":
        status = "OK (health API not supported by Tempo plugin)"
    else:
        try:
            health = req("GET", f"/api/datasources/uid/{uid}/health")
            status = health.get("status", health.get("message", "ok"))
        except SystemExit:
            status = "health check skipped"
    print(f"  - {ds.get('name')} ({uid}): {url} [{status}]")
PY

log "Re-importing dashboards with pinned datasource UIDs ..."
export GRAFANA_URL GRAFANA_ADMIN_PASSWORD
python3 "$ROOT/scripts/setup_grafana_local.py" --dashboards-only || {
  log "WARN: dashboard API import failed — rebuild Grafana image:"
  log "  ./scripts/rebuild-grafana-azure.sh"
}

upsert_env() {
  local key=$1 val=$2
  if grep -q "^${key}=" "$ENV_FILE" 2>/dev/null; then
    sed -i "s|^${key}=.*|${key}=${val}|" "$ENV_FILE"
  else
    echo "${key}=${val}" >> "$ENV_FILE"
  fi
}
upsert_env PROMETHEUS_URL "$DS_PROM"
upsert_env LOKI_URL "$DS_LOKI"
upsert_env TEMPO_URL "$DS_TEMPO"

echo ""
log "Done."
log "  1. Open: $GRAFANA_URL/connections/datasources"
log "  2. You should see Prometheus, Loki, Tempo (green health)"
log "  3. Open dashboard: $GRAFANA_URL/d/ai-telemetry-executive"
log "  4. Hard-refresh: Ctrl+Shift+R"
