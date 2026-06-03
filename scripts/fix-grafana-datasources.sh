#!/usr/bin/env bash
# Patch Grafana Prometheus/Loki/Tempo datasource URLs via API (no image rebuild).
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

log "Patching datasources on $GRAFANA_URL"
log "  Prometheus → $DS_PROM"
log "  Loki       → $DS_LOKI"
log "  Tempo      → $DS_TEMPO"

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
        with urllib.request.urlopen(r, timeout=30) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode() if exc.fp else ""
        raise SystemExit(f"{method} {path} → HTTP {exc.code}: {detail}") from exc

def upsert(name, ds_type, uid, url, extra_json=None):
    payload = {
        "name": name,
        "type": ds_type,
        "access": "proxy",
        "url": url,
        "uid": uid,
        "isDefault": ds_type == "prometheus",
        "jsonData": {"tlsSkipVerify": True, **(extra_json or {})},
    }
    existing = next((d for d in req("GET", "/api/datasources") if d.get("uid") == uid), None)
    if existing:
        payload["id"] = existing["id"]
        payload["orgId"] = existing.get("orgId", 1)
        req("PUT", f"/api/datasources/uid/{uid}", payload)
        print(f"  updated {name} → {url}")
    else:
        req("POST", "/api/datasources", payload)
        print(f"  created {name} → {url}")

upsert("Prometheus", "prometheus", "prometheus-ds", prom_url, {
    "timeInterval": "10s",
    "exemplarTraceIdDestinations": [{"name": "trace_id", "datasourceUid": "tempo-ds"}],
})
upsert("Loki", "loki", "loki-ds", loki_url, {
    "derivedFields": [{
        "datasourceUid": "tempo-ds",
        "matcherRegex": '"trace_id":"([a-f0-9]{32})"',
        "name": "trace_id",
        "url": "${__value.raw}",
    }],
})
upsert("Tempo", "tempo", "tempo-ds", tempo_url, {
    "tracesToLogsV2": {"datasourceUid": "loki-ds", "filterByTraceID": True},
    "tracesToMetrics": {"datasourceUid": "prometheus-ds"},
    "serviceMap": {"datasourceUid": "prometheus-ds"},
    "lokiSearch": {"datasourceUid": "loki-ds"},
})
PY

# Persist corrected URLs for future Grafana redeploys.
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

log "Done — refresh Grafana in your browser (Ctrl+Shift+R)"
