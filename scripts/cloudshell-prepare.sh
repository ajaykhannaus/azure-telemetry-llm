#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "=== Azure Cloud Shell — full setup (no Mac) ==="
echo ""

if [[ ! -f azure/bootstrap-azure.env ]]; then
  cp azure/bootstrap-azure.sandbox.env azure/bootstrap-azure.env
  echo "Created azure/bootstrap-azure.env from sandbox template"
fi

chmod +x scripts/bootstrap-azure.sh infra/bootstrap.sh infra/adx-data-connection.sh
chmod +x scripts/cloudshell-prepare.sh scripts/cloudshell-deploy.sh scripts/deploy-local.sh
chmod +x scripts/cloudshell-setup-complete.sh scripts/deploy-observability-stack.sh
chmod +x scripts/verify-observability.sh scripts/fix-grafana.sh scripts/fix-grafana-acr.sh scripts/fix-runner.sh

echo ""
echo "Run these commands ONE AT A TIME:"
echo ""
echo "  az account set --subscription \"216d62c8-0f0c-4e5c-9cda-cc553e7ab186\""
echo "  ./scripts/bootstrap-azure.sh --preflight"
echo "  ./scripts/bootstrap-azure.sh"
echo "  ./scripts/cloudshell-deploy.sh"
echo ""
echo "After bootstrap, apply infra/adx-schema.kql in ADX Portal (see docs/AZURE_CLOUDSHELL_SETUP.md)"
echo ""
