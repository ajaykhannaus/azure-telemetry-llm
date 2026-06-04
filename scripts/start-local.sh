#!/usr/bin/env bash
# Start the full AI Gateway Telemetry stack locally (mock mode, no Azure required).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

log() { echo "[start-local] $*"; }

# Load .env when present so mock mode + OTLP endpoint reach Loki via the collector.
if [[ -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT/.env"
  set +a
fi
export ALLOW_MOCK_MODE="${ALLOW_MOCK_MODE:-true}"
export OTEL_EXPORTER_OTLP_ENDPOINT="${OTEL_EXPORTER_OTLP_ENDPOINT:-http://localhost:4317}"
export ENVIRONMENT="${ENVIRONMENT:-dev}"

# ── 1. Python dependencies ───────────────────────────────────────────────────
log "Installing Python dependencies..."
python3 -m pip install -q -r generator/requirements.txt

# ── 2. Docker observability (OTel Collector, Tempo, Loki) ─────────────────────
log "Starting Docker observability stack..."
docker compose -f docker-compose.observability.yml up -d otel-collector tempo loki 2>/dev/null \
  || docker compose -f docker-compose.observability.yml up -d otel-collector tempo loki

# ── 3. Prometheus (local scrape config) ───────────────────────────────────────
if ! curl -sf http://localhost:9090/-/ready >/dev/null 2>&1; then
  log "Starting Prometheus (prometheus.local.yml)..."
  lsof -ti :9090 | xargs kill -9 2>/dev/null || true
  sleep 1
  nohup prometheus \
    --config.file="$ROOT/prometheus.local.yml" \
    --storage.tsdb.path=/tmp/prom-data-local \
    --web.listen-address=0.0.0.0:9090 \
    --log.level=warn \
    > /tmp/prom-local.log 2>&1 &
  sleep 2
else
  log "Prometheus already running on :9090"
fi

# ── 4. Grafana (Homebrew) ─────────────────────────────────────────────────────
if ! curl -sf http://localhost:3000/api/health >/dev/null 2>&1; then
  log "Starting Grafana via Homebrew..."
  brew services start grafana
  sleep 3
else
  log "Grafana already running on :3000"
fi

# ── 5. Telemetry runner (mock mode) ───────────────────────────────────────────
if ! curl -sf http://localhost:8080/healthz >/dev/null 2>&1; then
  log "Starting telemetry runner (mock mode)..."
  pkill -f "python3 -m generator.runner" 2>/dev/null || true
  sleep 1
  nohup env EVENTHUB_CONNECTION_STRING= EVENTHUB_NAMESPACE= \
    ALLOW_MOCK_MODE="$ALLOW_MOCK_MODE" \
    OTEL_EXPORTER_OTLP_ENDPOINT="$OTEL_EXPORTER_OTLP_ENDPOINT" \
    ENVIRONMENT="$ENVIRONMENT" \
    python3 -m generator.runner \
    > /tmp/telemetry-runner.log 2>&1 &
  sleep 2
else
  log "Telemetry runner already running on :8080"
fi

# ── 6. Grafana datasources + dashboards ───────────────────────────────────────
log "Regenerating Grafana dashboards (01–09)..."
python3 "$ROOT/dashboards/generate_dashboards.py"
log "Configuring Grafana datasources and dashboards..."
python3 "$ROOT/scripts/setup_grafana_local.py"

# ── 7. Wait for first Prometheus scrape + Loki telemetry logs ───────────────
log "Waiting for Prometheus scrape and Loki telemetry events..."
LOKI_COUNT="0"
for i in $(seq 1 30); do
  COUNT=$(curl -sf 'http://localhost:9090/api/v1/query?query=sum(ai_gateway_request_count_total)' \
    | python3 -c "import sys,json; r=json.load(sys.stdin)['data']['result']; print(r[0]['value'][1] if r else '0')" 2>/dev/null || echo "0")
  LOKI_COUNT=$(curl -sf 'http://localhost:3100/loki/api/v1/query' \
    --data-urlencode 'query=sum(count_over_time({service_name=~".+"} | json | line_format "{{.body}}" | json | event_type="telemetry_event" [5m]))' \
    | python3 -c "import sys,json; r=json.load(sys.stdin)['data']['result']; print(r[0]['value'][1] if r else '0')" 2>/dev/null || echo "0")
  if [ "$COUNT" != "0" ] && [ "$LOKI_COUNT" != "0" ]; then
    break
  fi
  sleep 2
done

# ── 8. Summary ────────────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════════════════"
echo "  AI Gateway Telemetry — local stack is running"
echo "════════════════════════════════════════════════════════════"
echo "  Runner metrics : http://localhost:8000/metrics"
echo "  Telemetry logs : http://localhost:8000/telemetry/logs"
echo "  Raw stdout     : http://localhost:8000/telemetry/logs/raw"
echo "  Demo app logs  : http://localhost:8000/telemetry/logs/demo"
echo "  Health         : http://localhost:8080/healthz"
echo "  Prometheus     : http://localhost:9090"
echo "  Grafana        : http://localhost:3000  (admin / admin)"
echo "  Dashboards     : http://localhost:3000/d/ai-telemetry-executive  (1–9 via nav bar)"
echo "  OTel Collector : localhost:4317 (gRPC)"
echo "  Tempo          : http://localhost:3200"
echo "  Loki           : http://localhost:3100"
echo "────────────────────────────────────────────────────────────"
echo "  Total requests scraped: ${COUNT:-0}"
echo "  Loki telemetry (5m):    ${LOKI_COUNT:-0}"
echo "  Runner log  : /tmp/telemetry-runner.log"
echo "  Prometheus  : /tmp/prom-local.log"
echo "════════════════════════════════════════════════════════════"
