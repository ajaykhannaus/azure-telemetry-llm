# Azure Cloud Shell Setup (Beginner — All on Azure Bash, No Mac)

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

## Part E — ADX schema (Portal, one-time)

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

### Command 14 — deploy Container App + Grafana + verify

```bash
./scripts/cloudshell-deploy.sh
```

**Success:** `Done — app is running in Azure.`

**Typical runtime:** 8–15 min on first deploy (Container App create can sit on `Running ..` for several minutes with no new lines — that is normal).

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
| 14 | `cloudshell-deploy.sh` | ☐ |
| 15b | Grafana URL + health curl | ☐ |
| 16–20 | Grafana 404 fix (if needed) | ☐ |

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
| Grafana **404** / app stopped | Command 19 (`fix-grafana.sh`) or 16–20 |
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

## Scripts (all in repo)

| Script | Purpose |
|---|---|
| `scripts/cloudshell-prepare.sh` | Copy config + chmod |
| `scripts/bootstrap-azure.sh` | Create Azure resources |
| `scripts/cloudshell-deploy.sh` | Deploy app from Cloud Shell |
| `scripts/fix-grafana.sh` | Diagnose + repair Grafana 404 |
| `infra/adx-schema.kql` | ADX database tables |
