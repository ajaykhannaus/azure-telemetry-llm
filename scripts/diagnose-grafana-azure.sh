#!/usr/bin/env bash
# Diagnose Grafana datasource connectivity and Prometheus data on Azure.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=lib/azure-deploy-common.sh
source "$ROOT/scripts/lib/azure-deploy-common.sh"
ENV_FILE="${ENV_FILE:-$ROOT/.env.azure}"

log() { echo "[diagnose-grafana] $*"; }
ok() { log "OK  $*"; }
fail() { log "FAIL $*"; }

[[ -f "$ENV_FILE" ]] || { log "ERROR: Missing $ENV_FILE"; exit 1; }

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

GRAFANA_APP_NAME="${GRAFANA_APP_NAME:-grafana-telemetry-dev}"
GRAFANA_ADMIN_PASSWORD="${GRAFANA_ADMIN_PASSWORD:-admin}"
APP_NAME="${APP_NAME:-ai-telemetry-runner-dev}"
PROM_APP_NAME="${PROM_APP_NAME:-prometheus-scraper-dev}"

az account set --subscription "$AZURE_SUBSCRIPTION_ID"

GRAFANA_FQDN=$(az containerapp show --name "$GRAFANA_APP_NAME" --resource-group "$AZURE_RESOURCE_GROUP" \
  --query "properties.configuration.ingress.fqdn" -o tsv)
GRAFANA_URL="https://${GRAFANA_FQDN}"

log "Grafana: $GRAFANA_URL"
log "Runner FQDN: $(az containerapp show --name "$APP_NAME" --resource-group "$AZURE_RESOURCE_GROUP" \
  --query "properties.configuration.ingress.fqdn" -o tsv)"

python3 - "$GRAFANA_URL" "$GRAFANA_ADMIN_PASSWORD" <<'PY'
import base64
import json
import sys
import urllib.error
import urllib.request

grafana, password = sys.argv[1:3]
auth = base64.b64encode(f"admin:{password}".encode()).decode()

def req(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(f"{grafana}{path}", data=data, method=method)
    r.add_header("Content-Type", "application/json")
    r.add_header("Authorization", f"Basic {auth}")
    with urllib.request.urlopen(r, timeout=45) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else {}

print("\n=== Datasources ===")
for ds in req("GET", "/api/datasources"):
    uid = ds["uid"]
    print(f"  {ds['name']} ({uid}): {ds.get('url')}")
    if ds["type"] != "tempo":
        try:
            h = req("GET", f"/api/datasources/uid/{uid}/health")
            print(f"    health: {h.get('status', h)}")
        except urllib.error.HTTPError as exc:
            print(f"    health: HTTP {exc.code}")

print("\n=== Prometheus queries (via Grafana proxy) ===")
queries = [
    ("raw counter", "ai_gateway_request_count_total"),
    ("recording rule 6h SLI", "ai_gateway:sli:availability:6h"),
    ("runner batch metric", "ai_telemetry_runner_batch_duration_seconds_count"),
]
for label, promql in queries:
    try:
        body = {
            "queries": [{
                "refId": "A",
                "datasource": {"type": "prometheus", "uid": "prometheus-ds"},
                "expr": promql,
                "instant": True,
            }],
            "from": "now-1h",
            "to": "now",
        }
        result = req("POST", "/api/ds/query", body)
        frames = result.get("results", {}).get("A", {}).get("frames", [])
        n = sum(len(f.get("data", {}).get("values", [[]])[0]) for f in frames) if frames else 0
        print(f"  {label}: {n} series/points")
        if n == 0:
            print(f"    WARN: no data for `{promql}` — runner scrape or recording rules may be missing")
    except Exception as exc:
        print(f"  {label}: ERROR {exc}")

print("\n=== Dashboards in Grafana ===")
for d in req("GET", "/api/search?type=dash-db"):
    print(f"  {d.get('title')} uid={d.get('uid')} url={d.get('url')}")
PY

log "If Prometheus queries show 0 points, check scraper SCRAPE_TARGET on $PROM_APP_NAME"
log "If dashboards missing, run: ./scripts/fix-grafana-datasources.sh"
