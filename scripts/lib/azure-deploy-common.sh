# Shared helpers for Azure Container Apps deploy scripts.
# shellcheck shell=bash

[[ -n "${_AZURE_DEPLOY_COMMON_LOADED:-}" ]] && return 0
_AZURE_DEPLOY_COMMON_LOADED=1

# Escape a value for use as the replacement side of awk gsub().
awk_escape() {
  printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/&/\\&/g'
}

# OTLP endpoint for Container Apps (never localhost on Azure).
resolve_azure_otel_endpoint() {
  local cae_name=$1 rg=$2 otel_app=${3:-otel-collector-dev}
  local env_ep=${OTEL_EXPORTER_OTLP_ENDPOINT:-}
  if [[ -z "$env_ep" || "$env_ep" == *localhost* || "$env_ep" == *127.0.0.1* ]]; then
    local domain
    domain=$(az containerapp env show --name "$cae_name" --resource-group "$rg" \
      --query properties.defaultDomain -o tsv 2>/dev/null || true)
    if [[ -n "$domain" ]]; then
      echo "http://${otel_app}.internal.${domain}:4317"
      return 0
    fi
  fi
  [[ -n "$env_ep" ]] && echo "$env_ep" || echo ""
}

acr_admin_credentials() {
  local acr_name=$1
  az acr update --name "$acr_name" --admin-enabled true --output none 2>/dev/null || true
  ACR_ADMIN_USER=$(az acr credential show --name "$acr_name" --query username -o tsv 2>/dev/null || true)
  ACR_ADMIN_PASS=$(az acr credential show --name "$acr_name" --query 'passwords[0].value' -o tsv 2>/dev/null || true)
}

# True when /metrics returns Prometheus text with runner instruments (not just HTTP 200).
runner_metrics_ok() {
  local metrics_url=$1 body
  body=$(curl -sf --compressed --max-time 30 "$metrics_url" 2>/dev/null | head -c 65536 || true)
  [[ -n "$body" ]] || return 1
  echo "$body" | grep -qE 'ai_gateway|kube_pod_info|ai_telemetry_runner|# TYPE|# HELP'
}

# HTTPS URL for a Container App on internal ingress (same CAE as Grafana).
cae_internal_https_url() {
  local app=$1 cae_name=$2 rg=$3
  local domain
  domain=$(az containerapp env show --name "$cae_name" --resource-group "$rg" \
    --query properties.defaultDomain -o tsv 2>/dev/null || true)
  [[ -n "$domain" ]] || return 1
  echo "https://${app}.internal.${domain}"
}

grafana_datasource_urls() {
  local cae_name=$1 rg=$2 prom_app=$3 loki_app=$4 tempo_app=$5
  local prom="${PROMETHEUS_URL:-}" loki="${LOKI_URL:-}" tempo="${TEMPO_URL:-}"

  if [[ -z "$prom" ]]; then
    prom=$(cae_internal_https_url "$prom_app" "$cae_name" "$rg" || true)
  fi
  if [[ -z "$loki" ]]; then
    loki=$(cae_internal_https_url "$loki_app" "$cae_name" "$rg" || true)
  fi
  if [[ -z "$tempo" ]]; then
    tempo=$(cae_internal_https_url "$tempo_app" "$cae_name" "$rg" || true)
  fi

  # Legacy deploys used http://*.internal.*:port — normalize to ingress HTTPS.
  prom="${prom/http:\/\//https:\/\/}"
  prom="${prom/:9090/}"
  loki="${loki/http:\/\//https:\/\/}"
  loki="${loki/:3100/}"
  tempo="${tempo/http:\/\//https:\/\/}"
  tempo="${tempo/:3200/}"

  printf '%s\n' "$prom" "$loki" "$tempo"
}

prometheus_deploy_sandbox() {
  local prom_app=$1 cae_name=$2 rg=$3 acr_name=$4 acr_login=$5 runner_fqdn=$6
  local user pass

  if [[ -z "$runner_fqdn" ]]; then
    echo "[prometheus] ERROR: runner FQDN required" >&2
    return 1
  fi

  acr_admin_credentials "$acr_name"
  user="$ACR_ADMIN_USER"
  pass="$ACR_ADMIN_PASS"

  bind_prometheus_acr_registry() {
    az containerapp registry set \
      --name "$prom_app" \
      --resource-group "$rg" \
      --server "$acr_login" \
      --username "$user" \
      --password "$pass" \
      --output none
  }

  if az containerapp show --name "$prom_app" --resource-group "$rg" >/dev/null 2>&1; then
    echo "[prometheus] Updating $prom_app ..."
    bind_prometheus_acr_registry
    az containerapp update \
      --name "$prom_app" \
      --resource-group "$rg" \
      --image "${acr_login}/prometheus-scraper:latest" \
      --set-env-vars "SCRAPE_TARGET=${runner_fqdn}" \
      --output none
  else
    echo "[prometheus] Creating $prom_app ..."
    az containerapp create \
      --name "$prom_app" \
      --resource-group "$rg" \
      --environment "$cae_name" \
      --image "${acr_login}/prometheus-scraper:latest" \
      --registry-server "$acr_login" \
      --registry-username "$user" \
      --registry-password "$pass" \
      --ingress internal --target-port 9090 \
      --min-replicas 1 --max-replicas 1 \
      --cpu 0.25 --memory 0.5Gi \
      --env-vars "SCRAPE_TARGET=${runner_fqdn}" \
      --output none
  fi
}
