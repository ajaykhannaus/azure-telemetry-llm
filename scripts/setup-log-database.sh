#!/usr/bin/env bash
# Initialize and verify the runner log database (SQLite local / ADX via Event Hub).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck source=scripts/lib/azure-deploy-common.sh
source "$ROOT/scripts/lib/azure-deploy-common.sh" 2>/dev/null || true

usage() {
  cat <<EOF
Usage: $0 [options]

Local SQLite (default):
  Creates/verifies \$LOG_DB_PATH and prints query URLs.

Azure ADX (optional — long-term warehouse):
  --enable-adx     Set PROVISION_ADX=true and run infra/adx-data-connection.sh
  --adx-only       Only provision ADX + schema instructions (skip SQLite demo)

Environment:
  LOG_DB_ENABLED=true
  LOG_DB_PATH=/tmp/telemetry_logs.db
  LOG_DB_RETENTION_DAYS=7
  LOG_DB_PUBLISH_EVENTHUB=true   # app.log → Event Hub → ADX ObservabilityLogs
EOF
}

ENABLE_ADX=false
ADX_ONLY=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --enable-adx) ENABLE_ADX=true; shift ;;
    --adx-only) ADX_ONLY=true; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; usage >&2; exit 1 ;;
  esac
done

if [[ "$ADX_ONLY" != "true" ]]; then
  LOG_DB_PATH="${LOG_DB_PATH:-/tmp/telemetry_logs.db}"
  export LOG_DB_ENABLED="${LOG_DB_ENABLED:-true}"
  export LOG_DB_PATH

  log "Initializing SQLite log database at $LOG_DB_PATH ..."
  ROOT="$ROOT" python3 - <<'PY'
import os, sys, time
sys.path.insert(0, os.environ["ROOT"])
from generator import log_store
from generator import plain_app_logs

log_store.start()
plain_app_logs.record_startup({"environment": "dev", "batch_interval_s": 5})
plain_app_logs.record_request({
    "request_id": "setup-test-001",
    "client_name": "setup-demo",
    "model_name": "gpt-4o",
    "operation_name": "chat_completion",
    "latency_ms": 42,
    "total_tokens": 10,
    "cost_usd": 0.0001,
    "status": "success",
    "http_status_code": 200,
    "streaming": False,
})
import time
time.sleep(0.5)
print("Stats:", log_store.stats())
print("Sample:", log_store.query_application_logs(3))
PY

  echo ""
  echo "SQLite ready."
  echo "  File:    $LOG_DB_PATH"
  echo "  Query:   curl http://localhost:8000/telemetry/logs/db?format=text"
  echo "  Events:  curl http://localhost:8000/telemetry/logs/db/events"
  echo "  Stats:   curl http://localhost:8000/telemetry/logs/db/stats"
  echo ""
fi

if [[ "$ENABLE_ADX" == "true" || "$ADX_ONLY" == "true" ]]; then
  BOOTSTRAP_CONFIG="${BOOTSTRAP_CONFIG:-$ROOT/azure/bootstrap-azure.sandbox.env}"
  if [[ -f "$BOOTSTRAP_CONFIG" ]]; then
    # shellcheck disable=SC1090
    source "$BOOTSTRAP_CONFIG"
  fi
  RG="${AZURE_RESOURCE_GROUP:-rg-telemetry-dev}"
  EH_NS="${EVENTHUB_NAMESPACE:-}"
  ADX_CLUSTER="${ADX_CLUSTER:-adxtelemetrydev}"
  ADX_DB="${ADX_DATABASE:-observability}"

  log "Provisioning ADX log warehouse (Event Hub → ObservabilityLogs) ..."
  if [[ -x "$ROOT/infra/adx-data-connection.sh" ]]; then
    args=(--resource-group "$RG" --cluster-name "$ADX_CLUSTER" --db-name "$ADX_DB")
    [[ -n "$EH_NS" ]] && args+=(--eventhub-ns "$EH_NS")
    "$ROOT/infra/adx-data-connection.sh" "${args[@]}"
  else
    log "WARN: infra/adx-data-connection.sh not found"
  fi

  echo ""
  echo "ADX schema: run infra/adx-schema.kql in Portal → cluster $ADX_CLUSTER → database $ADX_DB"
  echo "Query plain app logs in ADX:"
  echo "  ObservabilityLogs | where message contains \"InferenceService\" | take 20"
  echo ""
  echo "Enable in bootstrap: PROVISION_ADX=true LOG_DB_PUBLISH_EVENTHUB=true"
fi
