#!/usr/bin/env bash
# Stop local telemetry stack (runner + Prometheus). Leaves Grafana/Docker running.
set -euo pipefail

echo "[stop-local] Stopping telemetry runner..."
pkill -f "python3 -m generator.runner" 2>/dev/null || true

echo "[stop-local] Stopping local Prometheus..."
lsof -ti :9090 | xargs kill -9 2>/dev/null || true

echo "[stop-local] Done. Grafana and Docker observability still running."
echo "  To stop Docker: docker compose -f docker-compose.observability.yml down"
