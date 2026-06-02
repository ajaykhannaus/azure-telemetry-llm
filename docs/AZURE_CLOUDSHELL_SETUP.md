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

---

### Command 15 — optional: save secrets

```bash
cat .env.azure
```

Download via Cloud Shell **Download** if you want a copy for later.

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
| 16–17 | Grafana 404 fix (if needed) | ☐ |

---

## Re-run safely (containers already exist)

Bootstrap and deploy **reuse** same-named resources — they do not create duplicates or redeploy existing Container Apps.

| Re-run | Behavior |
|---|---|
| `./scripts/bootstrap-azure.sh` | Reuses ACR, CAE, Event Hub, Prometheus workspace, Managed Grafana, ADX; skips image build if app is running or `:latest` already in ACR; skips Grafana deploy only if `$GRAFANA_APP_NAME` is **Running** |
| `./scripts/bootstrap-azure.sh --grafana-only` | Redeploy self-hosted Grafana only (updates if stopped) |
| `./scripts/cloudshell-deploy.sh` | Deploys runner + Grafana + verify; skips runner if `$APP_NAME` already exists |
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
| Grafana **404** / app stopped | Commands 16–18 below |

---

### Command 16 — check Grafana Container App status

```bash
git pull
az containerapp show -n grafana-telemetry-dev -g az03-al-titan-sandbox-rg \
  --query "{status:properties.runningStatus,fqdn:properties.configuration.ingress.fqdn}" -o json
```

**Success:** `"status": "Running"` and an `fqdn` URL. Open `https://<fqdn>` (login: **admin** / **admin**).

---

### Command 17 — redeploy Grafana only

```bash
./scripts/bootstrap-azure.sh --grafana-only
```

Wait ~2–3 min, then open the `Grafana:` URL printed at the end.

---

### Command 18 — if Grafana still 404 (check logs)

```bash
az containerapp logs show -n grafana-telemetry-dev -g az03-al-titan-sandbox-rg --type console --tail 40
```

Or redeploy everything (runner + Grafana + verify):

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
| `infra/adx-schema.kql` | ADX database tables |
