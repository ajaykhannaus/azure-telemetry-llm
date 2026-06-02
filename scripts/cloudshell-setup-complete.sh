#!/usr/bin/env bash
# End-to-end Azure observability: runner → logs/traces/metrics → Grafana.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${ENV_FILE:-$ROOT/.env.azure}"
SKIP_PULL=false

usage() {
  cat <<EOF
Usage: $0 [--no-git-pull]

  One-shot Cloud Shell setup after bootstrap-azure.sh:
    1. Fix/deploy telemetry runner (ACR admin, OTLP wired)
    2. Deploy Loki + Tempo + Prometheus + OTel Collector
    3. Redeploy Grafana with Prometheus/Loki/Tempo datasources
    4. Verify health of all components

  Run from ~/observability in Azure Cloud Shell (single tab).
EOF
}

for arg in "$@"; do
  case "$arg" in
    --no-git-pull) SKIP_PULL=true ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $arg" >&2; usage >&2; exit 1 ;;
  esac
done

log() { echo "[setup-complete] $*"; }

if [[ "$SKIP_PULL" != "true" && -d "$ROOT/.git" ]]; then
  log "Updating repo..."
  git -C "$ROOT" pull --ff-only origin master 2>/dev/null \
    || git -C "$ROOT" pull --ff-only origin main 2>/dev/null \
    || log "WARN: git pull failed"
fi

[[ -f "$ENV_FILE" ]] || { log "ERROR: Missing $ENV_FILE — run ./scripts/bootstrap-azure.sh first"; exit 1; }

chmod +x "$ROOT/scripts/fix-runner.sh" \
         "$ROOT/scripts/deploy-observability-stack.sh" \
         "$ROOT/scripts/bootstrap-azure.sh" \
         "$ROOT/scripts/verify-observability.sh"

log "Step 1/4 — Runner (metrics + Event Hub + OTLP)"
"$ROOT/scripts/fix-runner.sh" --no-git-pull --build

log "Step 2/4 — Observability backend (Loki, Tempo, Prometheus, OTel Collector)"
"$ROOT/scripts/deploy-observability-stack.sh" --no-git-pull --skip-runner-otlp

log "Step 3/4 — Grafana (7 dashboards + Prometheus/Loki/Tempo datasources)"
export FORCE_CONTAINER_DEPLOY=true
export BOOTSTRAP_CONFIG="${BOOTSTRAP_CONFIG:-$ROOT/azure/bootstrap-azure.env}"
export WRITE_ENV_FILE="$ENV_FILE"
"$ROOT/scripts/bootstrap-azure.sh" --grafana-only

log "Step 4/4 — Verify"
"$ROOT/scripts/verify-observability.sh"

echo ""
echo "============================================================"
echo "  Full observability stack is ready"
echo "============================================================"
echo "  Open Grafana URL from verify output (login: admin / admin)"
echo "  Allow 2–3 minutes for dashboards to populate after first deploy"
echo "============================================================"
