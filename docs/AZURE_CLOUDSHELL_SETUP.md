# Azure Cloud Shell Setup (Beginner — All on Azure Bash, No Mac)

> **Re-run / fix / verify commands:** see [AZURE_CLOUDSHELL_ITERATIVE.md](./AZURE_CLOUDSHELL_ITERATIVE.md)  
> **Manual step-by-step (no scripts):** see [AZURE_MANUAL_STEP_BY_STEP.md](./AZURE_MANUAL_STEP_BY_STEP.md)

Open [Azure Cloud Shell](https://shell.azure.com) → choose **Bash**.

Run **one command at a time**. Wait for each to finish.

| Setting | Value |
|---|---|
| Subscription ID | `216d62c8-0f0c-4e5c-9cda-cc553e7ab186` |
| Resource group | `az03-al-titan-sandbox-rg` |

---

## Part A — Check access

### Command 1

```bash
az account set --subscription "216d62c8-0f0c-4e5c-9cda-cc553e7ab186"
```

**Success:** no output.

---

### Command 2

```bash
az group show --name "az03-al-titan-sandbox-rg" -o table
```

**Success:** table with your resource group.

---

### Command 3

```bash
az role assignment list --assignee "$(az ad signed-in-user show --query id -o tsv)" --resource-group "az03-al-titan-sandbox-rg" -o table
```

**Success:** role **Contributor**.

---

## Part B — Get the project

### Command 4

```bash
git clone https://github.com/ajaykhannaus/observability.git
```

---

### Command 5

```bash
cd observability
```

---

### Command 6

```bash
git pull
```

---

## Part C — Prepare config

### Command 7

```bash
cp azure/bootstrap-azure.sandbox.env azure/bootstrap-azure.env
```

---

### Command 8

```bash
chmod +x scripts/cloudshell-prepare.sh && ./scripts/cloudshell-prepare.sh
```

---

## Part D — Bootstrap (creates Azure resources)

### Command 9 — safe test

```bash
./scripts/bootstrap-azure.sh --preflight
```

**Success:** `preflight ok`

---

### Command 10 (only if ADX name conflict)

Defaults are already `acrtelemetrydevaj` and `evhns-telemetry-devaj`. If ADX cluster name is taken:

```bash
sed -i 's/adxtelemetrydev/adxtelemetrydevaj/g' azure/bootstrap-azure.env
```

Then re-run command 9.

---

### Command 11 — full bootstrap (~15–25 min)

```bash
./scripts/bootstrap-azure.sh
```

**Success:** ends with `Done`. Do not close Cloud Shell.

---

## Part E — ADX schema (Portal, optional)

Skip this section if `PROVISION_ADX=false` in `azure/bootstrap-azure.env` (default sandbox).

### Command 12 — show schema

```bash
cat infra/adx-schema.kql
```

Copy output → Azure Portal → **Azure Data Explorer** → cluster `adxtelemetrydev` → database `observability` → **Run**.

---

## Part F — Deploy app (still in Cloud Shell, no Mac)

### Command 13

```bash
chmod +x scripts/cloudshell-deploy.sh
```

---

### Command 14 — deploy full observability stack (~20–35 min first time)

Deploys **everything end-to-end**: runner → OTLP/logs/traces/metrics → Loki/Tempo/Prometheus → Grafana (7 dashboards).

```bash
./scripts/cloudshell-deploy.sh
```

This runs `cloudshell-setup-complete.sh` which:

1. **Runner** — metrics on `/metrics`, Event Hub events, OTLP export to collector
2. **Loki** — log store (OTLP logs from runner)
3. **Tempo** — trace store (OTLP traces from runner)
4. **Prometheus scraper** — scrapes runner `/metrics` (sandbox mode, no Azure Managed Prometheus)
5. **OTel Collector** — receives OTLP on port 4317, routes to Loki/Tempo/Prometheus
6. **Grafana** — Prometheus + Loki + Tempo datasources wired, 7 dashboards pre-loaded

**Success:** ends with `Full observability stack is ready` and verify checks passing.

**Typical runtime:** 20–35 min on first deploy (includes ACR builds for tempo/collector/prometheus/grafana images).

**Data paths after deploy:**

| Signal | Path | Grafana datasource |
|---|---|---|
| Metrics | runner `/metrics` → Prometheus scraper | Prometheus |
| Traces | runner OTLP → OTel Collector → Tempo | Tempo |
| Logs (OTLP) | runner OTLP → OTel Collector → Loki | Loki |
| Events | runner → Event Hub | (ADX when enabled) |
| Platform logs | Container App stdout → Log Analytics | Azure Portal |

**Success (legacy):** `Done — full observability stack is running in Azure.`

---

### Command 14b — optional second Cloud Shell tab (status only)

Open a **second** Cloud Shell tab while command 14 is still running. **Read-only checks only** — do **not** run deploy or Grafana commands here (that can conflict with the first tab).

```bash
cd observability

# Telemetry runner
az containerapp show -n ai-telemetry-runner-dev -g az03-al-titan-sandbox-rg \
  --query "{name:name,status:properties.runningStatus,replicas:properties.template.scale}" -o json

# Grafana
az containerapp show -n grafana-telemetry-dev -g az03-al-titan-sandbox-rg \
  --query "{name:name,status:properties.runningStatus,fqdn:properties.configuration.ingress.fqdn}" -o json

# Grafana health (404 fix: must return JSON, not an HTML error page)
GRAFANA_FQDN=$(az containerapp show -n grafana-telemetry-dev -g az03-al-titan-sandbox-rg \
  --query "properties.configuration.ingress.fqdn" -o tsv)
curl -sf "https://${GRAFANA_FQDN}/api/health"
```

**Grafana is truly up** when `curl` returns JSON like `{"database":"ok",...}`. If you get **404** while status is `Running`, use commands 18–20.

**While deploy is in progress:** status may be `Processing` or `Running` — wait for command 14 to finish in the first tab.

**If one step has no new output for 20+ min:** note the last line in tab 1, run the checks above in tab 2, then decide whether to wait or `Ctrl+C` and re-run command 14.

---

### Command 15 — optional: save secrets

```bash
cat .env.azure
```

Download via Cloud Shell **Download** if you want a copy for later.

---

### Command 15b — open Grafana + verify runner (after deploy)

```bash
# Grafana login page + health
GRAFANA_FQDN=$(az containerapp show -n grafana-telemetry-dev -g az03-al-titan-sandbox-rg \
  --query "properties.configuration.ingress.fqdn" -o tsv)
echo "Grafana: https://${GRAFANA_FQDN}  (admin / admin)"
curl -sf "https://${GRAFANA_FQDN}/api/health"

# Runner metrics (optional)
RUNNER_FQDN=$(az containerapp show -n ai-telemetry-runner-dev -g az03-al-titan-sandbox-rg \
  --query "properties.configuration.ingress.fqdn" -o tsv)
curl -sf "https://${RUNNER_FQDN}/metrics" | grep -m3 ai_gateway

# Runner log viewers (client demo)
echo "Formatted: https://${RUNNER_FQDN}/telemetry/logs"
echo "Raw stdout: https://${RUNNER_FQDN}/telemetry/logs/raw"
curl -sf "https://${RUNNER_FQDN}/telemetry/logs/raw" | tail -5
```

---

## Checklist (all Azure Bash)

| # | Command | Done? |
|---|---|---|
| 1 | `az account set ...` | ☐ |
| 2 | `az group show ...` | ☐ |
| 3 | `az role assignment list ...` | ☐ |
| 4–6 | clone + cd + pull | ☐ |
| 7–8 | copy config + prepare | ☐ |
| 9 | preflight | ☐ |
| 11 | bootstrap | ☐ |
| 12 | ADX schema in Portal | ☐ |
| 14 | `cloudshell-deploy.sh` (full stack) | ☐ |
| 15b | Grafana URL + health curl | ☐ |
| 16–20 | Grafana 404 fix (if needed) | ☐ |
| 21 | Runner 404 fix (if needed) | ☐ |
| 21b | Runner health check (replicas + metrics curl) | ☐ |
| 22 | Verify full stack (optional) | ☐ |

---

## Re-run safely (containers already exist)

Bootstrap and deploy **reuse** same-named resources — they do not create duplicates or redeploy existing Container Apps.

| Re-run | Behavior |
|---|---|
| `./scripts/bootstrap-azure.sh` | Reuses ACR, CAE, Event Hub, Prometheus workspace, Managed Grafana, ADX; skips image build if app is serving or `:latest` already in ACR; skips Grafana deploy only if `/api/health` succeeds |
| `./scripts/bootstrap-azure.sh --grafana-only` | Redeploy self-hosted Grafana only (updates if not serving traffic) |
| `./scripts/cloudshell-deploy.sh` | Deploys runner + Grafana + verify; skips runner if `$APP_NAME` already exists |
| Force Grafana recreate | `export GRAFANA_RECREATE=true` then `--grafana-only` |
| Force Container App update | `export FORCE_CONTAINER_DEPLOY=true` before deploy |
| Force image rebuild | `export FORCE_IMAGE_BUILD=true` before bootstrap |

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `Authorization failed` | Need Contributor (command 3) |
| ACR / Event Hub name taken | Command 10, then 9 again |
| `.env.azure not found` | Run command 11 first |
| Deploy fails on Event Hub | Re-run command 11 |
| `SecretRef 'eventhub-namespace' not found` | `git pull` then re-run command 14 |
| Deploy seems slow (10–15 min) | Normal on first create; use command 14b in a second tab |
| Grafana **404** / app stopped | Command 19 (`fix-grafana.sh`) or 19b (`fix-grafana-acr.sh`) |
| Runner **404** / no metrics | Command 21 (`fix-runner.sh`) or 21b (replicas + metrics curl) |
| `AuthorizationFailed` / async hash on create | Close other Cloud Shell tabs; wait 2 min; re-run command 19 |
| `Operation expired` on revision | Normal on slow sandbox — re-run command 19; script now polls up to 10 min |

---

### Command 16 — check Grafana status + health

```bash
git pull
az containerapp show -n grafana-telemetry-dev -g az03-al-titan-sandbox-rg \
  --query "{status:properties.runningStatus,fqdn:properties.configuration.ingress.fqdn}" -o json

GRAFANA_FQDN=$(az containerapp show -n grafana-telemetry-dev -g az03-al-titan-sandbox-rg \
  --query "properties.configuration.ingress.fqdn" -o tsv)
curl -sf "https://${GRAFANA_FQDN}/api/health"
```

**Success:** `"status": "Running"` **and** `curl` returns JSON (not 404 HTML). Open `https://<fqdn>` (login: **admin** / **admin**).

**If `Running` but curl fails:** continue to command 18 — the app exists but no healthy replica is serving traffic.

---

### Command 17 — redeploy Grafana only

```bash
./scripts/bootstrap-azure.sh --grafana-only
```

Wait ~2–3 min, then open the `Grafana:` URL printed at the end.

---

### Command 18 — if Grafana still 404 (check logs)

```bash
az containerapp replica list -n grafana-telemetry-dev -g az03-al-titan-sandbox-rg -o table
az containerapp logs show -n grafana-telemetry-dev -g az03-al-titan-sandbox-rg --type console --tail 40
```

### Command 19 — one-command Grafana repair (404 / no replicas)

Most 404s are **failed image pull from ACR** (app shows `Running` but has zero healthy replicas). This script diagnoses, rebuilds the image, recreates the app, and waits for `/api/health`.

```bash
git pull
chmod +x scripts/fix-grafana.sh
./scripts/fix-grafana.sh
```

**Success:** `Grafana is healthy: https://...`

### Command 19b — ACR auth only (401 / ImagePullBackOff, no delete/recreate)

Use when system logs show `401`, `FetchingKeyVaultSecretFailed`, or `managed identity` + `token exchange`. **Uses ACR admin credentials by default** (most reliable in sandbox).

```bash
git pull
chmod +x scripts/fix-grafana-acr.sh
./scripts/fix-grafana-acr.sh --force
```

**Stuck on `Waiting ... 60/60`?** You are on an old script — run `git pull` first (need commit `d48e021+`). Then:

```bash
./scripts/fix-grafana-acr.sh --force
```

**`provisioningState=Failed` or `secret set busy` on `--recreate`?** Pull latest — create now embeds ACR admin auth in YAML (one blocking create, no post-create secret set):

```bash
git pull
./scripts/fix-grafana-acr.sh --recreate
```

Optional — try managed identity first (usually fails in sandbox without AcrPull permission):

```bash
./scripts/fix-grafana-acr.sh --try-managed-identity
```

**If you see `ContainerAppSecretRefNotFound` / `grafana-admin-password` not found:** Pull latest — scripts preserve `grafana-admin-password` when updating registry auth.

**If you see `AuthorizationFailed` on AcrPull:** Your account cannot assign RBAC roles — that is OK in sandbox. Pull latest and run command 19b; scripts use **ACR admin credentials** instead (no AcrPull needed).

**If you see `unrecognized arguments: --password-secret`:** Pull latest — fixed to use `--password` (Cloud Shell CLI version).

**If you see `ContainerAppOperationInProgress`:** Azure is still finishing a prior change (often from registry remove). Close other Cloud Shell tabs, wait **2 minutes**, pull latest, and re-run command 19b — the script now waits and retries automatically.

**If you see `waiting for provisioning` for many minutes:** The old script waited for Azure before granting ACR pull access (image pull fails without it). Pull latest code — `fix-grafana.sh` now assigns AcrPull within ~1 min, then refreshes the revision.

**If you see `AuthorizationFailed` / `content hash` / `ContainerAppOperationInProgress`:** Azure is still finishing a delete/create/update from this or another tab. Close other Cloud Shell tabs, wait **2 minutes**, then run command 19 again (do not run deploy in parallel).

**If you see `Operation expired`:** The CLI timed out waiting for the revision — Grafana may still be starting in the background. Wait **2 minutes**, run command 19 again, or run command 20 to poll `/api/health` manually.

**If you see `ContainerAppProbeInitialDelaySecondsOutOfRange` or `ContainerAppProbeFailureThresholdOutOfRange`:** Your Cloud Shell copy is stale. Run `git pull`, confirm probes look like below, then re-run command 19:

```bash
git pull
grep -E 'initialDelaySeconds|failureThreshold' infra/grafana.template.yaml
# initialDelaySeconds must be <= 60, failureThreshold <= 30
```

Manual equivalent:

```bash
git pull
export GRAFANA_RECREATE=true
export FORCE_IMAGE_BUILD=true
./scripts/bootstrap-azure.sh --grafana-only
```

Wait until you see `grafana: healthy at https://...` then open that URL (login: **admin** / **admin**).

---

### Command 20 — confirm Grafana is fixed

```bash
GRAFANA_FQDN=$(az containerapp show -n grafana-telemetry-dev -g az03-al-titan-sandbox-rg \
  --query "properties.configuration.ingress.fqdn" -o tsv)
curl -sf "https://${GRAFANA_FQDN}/api/health"
echo "Open: https://${GRAFANA_FQDN}"
```

Or redeploy everything:

```bash
./scripts/cloudshell-deploy.sh
```

Force a full Container App update:

```bash
export FORCE_CONTAINER_DEPLOY=true
./scripts/cloudshell-deploy.sh
```

---

### Command 21 — fix runner 404 (no `/metrics`)

Same root cause as Grafana: **ACR image pull failed** (app shows `Running` but has no healthy replicas).

```bash
git pull
chmod +x scripts/fix-runner.sh
./scripts/fix-runner.sh
```

**Success:** `Runner is healthy: https://.../metrics`

If image missing, add `--build`:

```bash
./scripts/fix-runner.sh --build
```

Then verify + refresh Grafana dashboards:

```bash
RUNNER_FQDN=$(az containerapp show -n ai-telemetry-runner-dev -g az03-al-titan-sandbox-rg \
  --query "properties.configuration.ingress.fqdn" -o tsv)
curl -sf "https://${RUNNER_FQDN}/metrics" | grep -m3 ai_gateway
```

---

### Command 21b — runner health check (replicas + metrics)

Use while `fix-runner.sh` is polling, or after you see **1 replica** in the list.

```bash
export RG="az03-al-titan-sandbox-rg"
export RUNNER="ai-telemetry-runner-dev"

az containerapp replica list -n "$RUNNER" -g "$RG" -o table

az containerapp show -n "$RUNNER" -g "$RG" \
  --query "{status:properties.runningStatus,provisioning:properties.provisioningState,revision:properties.latestRevisionName}" -o json

RUNNER_FQDN=$(az containerapp show -n "$RUNNER" -g "$RG" \
  --query "properties.configuration.ingress.fqdn" -o tsv)
echo "Metrics: https://${RUNNER_FQDN}/metrics"
curl -sf "https://${RUNNER_FQDN}/metrics" | grep -m3 ai_gateway
```

**If still 404 with replicas:**

```bash
az containerapp logs show -n "$RUNNER" -g "$RG" --type console --tail 30
az containerapp logs show -n "$RUNNER" -g "$RG" --type system --tail 20
```

**When metrics show `ai_gateway` — continue full stack:**

```bash
git pull
./scripts/cloudshell-setup-complete.sh
# or step by step:
# ./scripts/deploy-observability-stack.sh
# export FORCE_CONTAINER_DEPLOY=true && ./scripts/bootstrap-azure.sh --grafana-only --no-build
# ./scripts/verify-observability.sh
```

More detail: [AZURE_CLOUDSHELL_ITERATIVE.md — Runner health check](./AZURE_CLOUDSHELL_ITERATIVE.md#runner-health-check-while-waiting-or-after-4040)

---

### Command 22 — verify full observability stack

Run after command 14 (or anytime) to confirm runner, Loki, Tempo, Prometheus, Collector, and Grafana are healthy:

```bash
git pull
chmod +x scripts/verify-observability.sh
./scripts/verify-observability.sh
```

**Success:** `All checks passed` plus Grafana URL.

**Re-deploy backend only** (refresh Loki/Tempo/Prometheus/Collector, then Grafana datasources):

```bash
git pull
./scripts/deploy-observability-stack.sh --build
export FORCE_CONTAINER_DEPLOY=true
./scripts/bootstrap-azure.sh --grafana-only
./scripts/verify-observability.sh
```

---

## Scripts (all in repo)

| Script | Purpose |
|---|---|
| `scripts/cloudshell-prepare.sh` | Copy config + chmod |
| `scripts/bootstrap-azure.sh` | Create Azure resources |
| `scripts/cloudshell-deploy.sh` | Full stack: runner + Loki/Tempo/Prometheus/Collector + Grafana |
| `scripts/cloudshell-setup-complete.sh` | Same as cloudshell-deploy (orchestrator) |
| `scripts/deploy-observability-stack.sh` | Loki + Tempo + Prometheus + OTel Collector only |
| `scripts/verify-observability.sh` | Health-check runner, backend, Grafana |
| `scripts/fix-grafana.sh` | Diagnose + repair Grafana 404 |
| `scripts/fix-grafana-acr.sh` | Fix Grafana ACR 401 / image pull (no delete/recreate) |
| `scripts/fix-runner.sh` | Fix runner 404 / ACR pull (recreate with admin auth) |
| `infra/adx-schema.kql` | ADX database tables |
