# Documentation index

Pick the doc that matches your level.

| Doc | Level | Start here if… |
|-----|-------|----------------|
| **[BEGINNER_GUIDE.md](./BEGINNER_GUIDE.md)** | **New to the project** | You are learning what observability is, or what Prometheus/Tempo/Loki mean |
| [DASHBOARD_METRICS.md](./DASHBOARD_METRICS.md) | Beginner → intermediate | You want to know what each Grafana panel metric means and why it exists |
| [HOW_IT_WORKS.md](./HOW_IT_WORKS.md) | Intermediate | You know the basics and want architecture diagrams + every service explained |
| [ARCHITECTURE.md](./ARCHITECTURE.md) | Intermediate | You want visual Azure/CI/CD architecture diagrams |
| [semantic-conventions.md](./semantic-conventions.md) | Advanced | You are adding spans, metrics, or dashboards and need naming rules |
| [improvement-plan.md](./improvement-plan.md) | Advanced | You want the roadmap and future gateway cutover plan |

**Repo root docs:**

| Doc | Purpose |
|-----|---------|
| [../README.md](../README.md) | Quick start, deploy commands, environment variables |
| [../PRODUCTION_GUIDE.md](../PRODUCTION_GUIDE.md) | Production operations |
| [../COMPANY_VM_SETUP.md](../COMPANY_VM_SETUP.md) | Company VM / self-hosted GitHub runner |
| [AZURE_CLOUDSHELL_SETUP.md](./AZURE_CLOUDSHELL_SETUP.md) | Azure Cloud Shell provisioning (Bash) — **first-time setup** |
| [AZURE_CLOUDSHELL_ITERATIVE.md](./AZURE_CLOUDSHELL_ITERATIVE.md) | Azure Cloud Shell — **repeat commands** (verify, redeploy, fix) |
| [AZURE_MANUAL_STEP_BY_STEP.md](./AZURE_MANUAL_STEP_BY_STEP.md) | **Manual one-command-at-a-time** runner deploy (no scripts) |

## Recommended reading order

```
BEGINNER_GUIDE  →  DASHBOARD_METRICS  →  HOW_IT_WORKS  →  generator/runner.py  →  semantic-conventions  →  README (deploy)
```
