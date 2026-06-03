# Azure manual step-by-step (no bash scripts)

> **Scripted alternative:** [AZURE_CLOUDSHELL_SETUP.md](./AZURE_CLOUDSHELL_SETUP.md) and [AZURE_CLOUDSHELL_ITERATIVE.md](./AZURE_CLOUDSHELL_ITERATIVE.md)  
> Use this doc when you want to run **one command at a time** or configure resources in the **Azure Portal**.

---

## Sandbox reference

| Item | Value |
|---|---|
| Subscription | `az-uc-analytics-sandbox-eastus` (`216d62c8-0f0c-4e5c-9cda-cc553e7ab186`) |
| Resource group | `az03-al-titan-sandbox-rg` |
| ACR name | **`acrtelemetrydevaj`** (not `acrtelemetrydevraj`) |
| ACR login server | `acrtelemetrydevaj.azurecr.io` |
| Container Apps env | `cae-telemetry-dev` |
| Runner app | `ai-telemetry-runner-dev` |
| Event Hub topic | `ai-telemetry-events` |
| Cloud Shell clone | `~/observability` |

---

## Before you start

Infra must already exist (ACR, Container Apps environment, Event Hub). If bootstrap never ran:

```bash
cd ~/observability
cp azure/bootstrap-azure.sandbox.env azure/bootstrap-azure.env
./scripts/bootstrap-azure.sh
```

That creates `.env.azure` with Event Hub secrets. Manual steps below assume bootstrap completed once.

---

## Step 1 — Confirm latest code

```bash
cd ~/observability
git pull
git log -1 --oneline
grep 'COPY observability/' Dockerfile.runner
grep 'runner import ok' Dockerfile.runner
```

**Pass:** both `grep` lines match. The fixed runner image must copy the `observability/` Python package or the container exits with code 1 immediately.

---

## Step 2 — Set subscription and verify ACR

```bash
az account set --subscription 216d62c8-0f0c-4e5c-9cda-cc553e7ab186
az account show --query "{name:name,id:id}" -o table
az acr list --resource-group az03-al-titan-sandbox-rg -o table
```

**Pass:** table shows **`acrtelemetrydevaj`** in `az03-al-titan-sandbox-rg`.

| Error | Fix |
|---|---|
| `registries could not be found in subscription` | Wrong subscription — run `az account set` above |
| Registry name typo (`acrtelemetrydevraj`) | Use **`acrtelemetrydevaj`** exactly |
| Empty ACR list | Run bootstrap (see [Before you start](#before-you-start)) |

---

## Step 3 — Build runner image in ACR

From repo root:

```bash
cd ~/observability

az acr build \
  --registry acrtelemetrydevaj \
  --resource-group az03-al-titan-sandbox-rg \
  --platform linux/amd64 \
  --image ai-telemetry-runner:latest \
  -f Dockerfile.runner \
  .
```

**Important:** the trailing **`.`** is the build context — do not omit it.

**Pass:** `Run succeeded` (~1–12 min). Build log must include:

```text
COPY observability/ /app/observability/
RUN python3 -c "... runner import ok"
```

If build skips `COPY observability/`, run `git pull` and rebuild.

---

## Step 4 — Redeploy Container App with new image

```bash
az containerapp update \
  --name ai-telemetry-runner-dev \
  --resource-group az03-al-titan-sandbox-rg \
  --image acrtelemetrydevaj.azurecr.io/ai-telemetry-runner:latest
```

Wait 2–5 minutes, then check:

```bash
az containerapp show \
  --name ai-telemetry-runner-dev \
  --resource-group az03-al-titan-sandbox-rg \
  --query "{status:properties.runningStatus,provisioning:properties.provisioningState,revision:properties.latestRevisionName}" \
  -o table

az containerapp replica list \
  --name ai-telemetry-runner-dev \
  --resource-group az03-al-titan-sandbox-rg \
  -o table
```

**Pass:** `provisioningState` = `Succeeded`, at least **1** replica.

### If update fails (registry auth)

Enable ACR admin user in Portal → ACR → **Access keys**, then:

```bash
ACR_USER=$(az acr credential show --name acrtelemetrydevaj --query username -o tsv)
ACR_PASS=$(az acr credential show --name acrtelemetrydevaj --query "passwords[0].value" -o tsv)

az containerapp update \
  --name ai-telemetry-runner-dev \
  --resource-group az03-al-titan-sandbox-rg \
  --image acrtelemetrydevaj.azurecr.io/ai-telemetry-runner:latest \
  --registry-server acrtelemetrydevaj.azurecr.io \
  --registry-username "$ACR_USER" \
  --registry-password "$ACR_PASS"
```

---

## Step 5 — Verify runner is healthy

```bash
RUNNER_FQDN=$(az containerapp show \
  --name ai-telemetry-runner-dev \
  --resource-group az03-al-titan-sandbox-rg \
  --query "properties.configuration.ingress.fqdn" -o tsv)

echo "Metrics: https://${RUNNER_FQDN}/metrics"
curl -sf "https://${RUNNER_FQDN}/metrics" | grep -m3 ai_gateway
```

Console logs (should show startup, not crash loop):

```bash
az containerapp logs show \
  --name ai-telemetry-runner-dev \
  --resource-group az03-al-titan-sandbox-rg \
  --type console --tail 20
```

**Good logs:** `Runner starting`, `Health server listening on :8080`  
**Bad logs:** `ModuleNotFoundError: observability` → rebuild image (Steps 1–3)  
**Bad logs:** `ContainerTerminated exit code 1` with Traceback → paste console output

---

## Step 6 — Continue full observability stack

After `/metrics` returns `ai_gateway` lines, either:

**One command (scripted):**

```bash
./scripts/cloudshell-setup-complete.sh
```

**Manual order:**

1. Deploy Loki, Tempo, Prometheus, OTel Collector (Portal or `./scripts/deploy-observability-stack.sh`)
2. Refresh Grafana datasources: `./scripts/bootstrap-azure.sh --grafana-only --no-build`
3. Verify: `./scripts/verify-observability.sh`

Grafana URL (if already deployed):

```bash
az containerapp show -n grafana-telemetry-dev -g az03-al-titan-sandbox-rg \
  --query "properties.configuration.ingress.fqdn" -o tsv
```

Login: **admin** / **admin**

---

## Portal-only alternative (same steps)

| Step | Portal path |
|---|---|
| Build image | **Container registries** → `acrtelemetrydevaj` → **Tasks** / build `Dockerfile.runner` |
| Update app | **Container Apps** → `ai-telemetry-runner-dev` → **Containers** → image `acrtelemetrydevaj.azurecr.io/ai-telemetry-runner:latest` |
| Env vars | See [runner template](../infra/runner-acr-admin.template.yaml) — ports 8000/8080, `ALLOW_MOCK_MODE=true`, Event Hub secrets |
| Logs | **Monitoring** → **Log stream** → Console |
| Metrics | Copy app **Application URL** → append `/metrics` |

---

## Troubleshooting quick reference

| Symptom | Likely cause | Fix |
|---|---|---|
| ACR not found | Wrong subscription or typo in name | Step 2 |
| Build OK, still crash loop | Old revision still running | Step 4 again; check console logs |
| `No module named observability'` | Image built from old Dockerfile | Step 1 → 3 |
| 404 on `/metrics` for minutes | Replica still starting | Wait 2–5 min; check replica count |
| No replicas | ACR pull failed | Step 4 registry auth block |

---

## Related docs

| Doc | Use for |
|---|---|
| [AZURE_CLOUDSHELL_SETUP.md](./AZURE_CLOUDSHELL_SETUP.md) | First-time bootstrap (numbered commands) |
| [AZURE_CLOUDSHELL_ITERATIVE.md](./AZURE_CLOUDSHELL_ITERATIVE.md) | Re-run, fix-runner, health checks |
| [HOW_IT_WORKS.md](./HOW_IT_WORKS.md) | Architecture and data flow |
