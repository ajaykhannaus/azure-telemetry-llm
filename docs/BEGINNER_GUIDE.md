# Beginner Guide — Start Here

**Audience:** Developers new to this repo **and** new to observability (Prometheus, traces, etc.).

**Time to read:** ~20 minutes. **Time to run locally:** ~10 minutes.

Other docs assume more context. Read this first, then move to [HOW_IT_WORKS.md](./HOW_IT_WORKS.md) when you want diagrams and deployment detail.

---

## Part 1 — What is this project?

This is **not** a chatbot or an LLM app.

It is a **telemetry pipeline** — software that:

1. Creates fake LLM gateway requests (for now)
2. Sends data about those requests to storage and dashboards
3. Lets operators answer: *How busy? How fast? How expensive? Any errors?*

**Real-world analogy:** A factory that makes sample products every 5 seconds and ships reports about each product to different departments (billing, ops, support).

**Important:** The fake traffic generator is temporary. The **pipeline** (publish, metrics, traces, logs, dashboards) is the real product.

---

## Part 2 — Glossary (learn these first)

Read this section once. Every other doc uses these words.

### Application terms

| Term | Plain English |
|------|----------------|
| **Event** | One fake LLM request, stored as a Python dictionary (`request_id`, `model_name`, `latency_ms`, `cost_usd`, …) |
| **Batch** | A group of ~8 events processed together, every ~5 seconds |
| **Runner** | The main Python program (`generator/runner.py`) that runs the batch loop forever |
| **Mock mode** | Running without Azure — events print to the terminal instead of going to the cloud |
| **START / END** | Two Kafka messages per request: “started” and “finished” |

### Observability terms (the “three signals”)

| Term | Plain English | Example question |
|------|----------------|------------------|
| **Metrics** | Numbers over time (counts, averages) | “How many errors in the last hour?” |
| **Traces** | Step-by-step timeline of **one** request | “Why was request `abc-123` slow?” |
| **Logs** | Text/JSON lines about what happened | “Show everything client X did at 3pm” |

### Tools in this project

| Tool | Type | One-line job |
|------|------|--------------|
| **Prometheus** | Metrics database | Stores numbers for charts and alerts |
| **Tempo** | Trace database | Stores request timelines (span trees) |
| **Loki** | Log database | Stores searchable log lines |
| **Grafana** | Dashboard UI | Shows Prometheus + Tempo + Loki in one place |
| **OTel Collector** | Middleware | Receives telemetry from the app, routes it to Prometheus/Tempo/Loki |
| **OpenTelemetry (OTel)** | Standard + libraries | How the app creates and exports metrics/traces |
| **OTLP** | Network protocol | How the app sends data to the OTel Collector (`:4317`) |
| **Azure Event Hubs** | Message queue (Kafka-compatible) | Durable storage of raw START/END events |
| **Log Analytics** | Azure log warehouse | Where Container App stdout (JSON logs) lands |

### How they connect (memorize this)

```
Runner  ──OTLP──►  OTel Collector  ──►  Prometheus  (metrics)
                         │          ──►  Tempo       (traces)
                         │          ──►  Loki        (logs)
                         │
Runner  ──Kafka──►  Event Hubs       (raw events)
Runner  ──stdout──► Log Analytics    (JSON logs, Azure path)

Grafana reads Prometheus + Tempo + Loki (+ Log Analytics)
```

---

## Part 3 — The story of one request

Follow one fake request through the system. This is the mental model for everything else.

### Step 0 — The loop wakes up

Every ~5 seconds, `run_one_batch()` in `generator/runner.py` runs.

### Step 1 — Generate

`synthetic_generator.generate_event()` builds a dict:

```python
{
  "request_id": "abc-123",
  "client_name": "healthcare-portal",
  "model_name": "claude-sonnet-4-5",
  "latency_ms": 1420.5,
  "prompt_tokens": 680,
  "completion_tokens": 310,
  "cost_usd": 0.00891,
  "status": "success",
}
```

### Step 2 — Trace (Tempo path)

`otel_tracing.py` opens spans — a tree showing where time was spent:

```
ai.batch.run
└── ai.request
    ├── ai.request.queue_wait
    ├── ai.request.model_inference
    ├── ai.publish.start_event
    └── ai.publish.end_event
```

### Step 3 — Publish (Event Hubs path)

`kafka_publisher.py` sends two messages:

- `usage_event_type: "start"` — request began
- `usage_event_type: "end"` — request finished (with latency, tokens, cost)

Each message includes a `traceparent` header so it links to the trace.

### Step 4 — Metrics (Prometheus path)

`otel_metrics.py` increments counters and records latency:

- `ai.request.count` +1
- `ai.request.duration` ← 1420.5 ms
- `ai.request.cost` ← $0.00891

Sent via OTLP → OTel Collector → Prometheus.

### Step 5 — Log (Log Analytics path)

`azure_logger.py` writes one JSON line to stdout. Azure ships it to Log Analytics.

### Step 6 — Sleep

Runner sleeps until the next batch. Repeat.

---

## Part 4 — Why an OTel Collector?

**Without it:** the Python app would need separate code/config for Tempo, Prometheus, and Loki, plus sampling rules in every service.

**With it:** the app sends everything to **one address** (`localhost:4317`). The Collector:

| Job | Example in this project |
|-----|-------------------------|
| **Route** | Traces → Tempo, metrics → Prometheus, logs → Loki |
| **Sample** | Keep 100% of error traces, only 10% of success traces |
| **Protect** | Strip high-cardinality fields (`request_id`) from metrics before Prometheus |
| **Batch** | Group exports every 5s for efficiency |

**You write:** Python in `generator/`. **You configure:** `infra/otel-collector-config.yaml`.

---

## Part 5 — Code map (read in this order)

Do not read the whole repo. Start with these five files:

| Order | File | Read for |
|-------|------|----------|
| 1 | `generator/runner.py` | Main loop — search for `run_one_batch` and `main` |
| 2 | `generator/synthetic_generator.py` | Search for `generate_event` — see event shape |
| 3 | `generator/kafka_publisher.py` | Search for `publish_start_event` / `publish_end_event` |
| 4 | `generator/otel_metrics.py` | Search for `record_metrics` |
| 5 | `generator/otel_tracing.py` | Search for `request_span` |

**After those five:** skim `infra/otel-collector-config.yaml` to see where data goes after it leaves Python.

---

## Part 6 — Hands-on lab (do this on your machine)

### Lab A — Minimal (no Docker, no Azure)

```bash
cd Telemetry
cp .env.example .env
```

Edit `.env` — set these two lines:

```env
ENVIRONMENT=dev
ALLOW_MOCK_MODE=true
```

```bash
pip install -r generator/requirements.txt
python3 -m generator.runner
```

**You should see:**

```
batch=8 ok=8 err=0 sla_breach=0 cost=$0.00xxx tokens=xxxx dur=0.0xs
[MOCK traceparent=...] → {"usage_event_type": "start", ...}
[MOCK traceparent=...] → {"usage_event_type": "end", ...}
```

**What you learned:** the batch loop works; Kafka is mocked; metrics/traces export if OTel SDK is installed.

Press `Ctrl+C` to stop.

### Lab B — Validate fake data quality

```bash
python3 validation/check_data.py
```

Generates 1,000 events and checks fields, error rate, and cost math. Exit code 0 = pass.

### Lab C — Full stack with Grafana (optional, needs Docker)

```bash
docker compose -f docker-compose.observability.yml up -d
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317 python3 -m generator.runner
```

Open http://localhost:3000 (Grafana — default login `admin` / `admin`).

| URL | What it is |
|-----|------------|
| http://localhost:3000 | Grafana dashboards |
| http://localhost:9090 | Prometheus — raw metrics |
| http://localhost:3200 | Tempo — traces API |
| http://localhost:3100 | Loki — logs API |

---

## Part 7 — Folder map (what to ignore for now)

```
Telemetry/
├── generator/          ← START HERE (the application)
├── tests/              ← read after you understand runner.py
├── validation/         ← data quality script (Lab B)
├── dashboards/         ← Grafana JSON — look after you see metrics in Grafana
├── infra/              ← Azure + OTel Collector config — read when deploying
├── docs/               ← you are here
├── function_app/       ← alternative deployment — skip for now
└── .github/workflows/  ← CI/CD — skip until you understand the app
```

---

## Part 8 — FAQ

### Is this using real AI / calling ChatGPT?

**No.** `synthetic_generator.py` fakes the numbers. Optional `evaluator.py` can call OpenAI for quality scoring, but it is off by default.

### What is Kafka / Event Hubs?

A **durable message queue**. Events sit there until another system reads them (billing, analytics). The app uses Event Hubs because it speaks the Kafka protocol without running your own Kafka cluster.

### What is the difference between Prometheus and Log Analytics?

Both store data you can query. **Prometheus** = aggregated numbers (fast charts/alerts). **Log Analytics** = raw JSON log lines from stdout (Azure-native, good for compliance). This project uses both.

### What is a span?

One step in a trace. “Queue wait took 50ms” = one span. Spans form a tree under a parent request span.

### What happens if I don't set up Azure?

Set `ALLOW_MOCK_MODE=true`. The app runs fully locally; Event Hubs messages print to the terminal.

### What is `traceparent`?

A standard header that links a Kafka message to its Tempo trace. Lets you jump from an event to its timeline.

---

## Part 9 — Learning path (what to read next)

```
You are here
    │
    ▼
docs/BEGINNER_GUIDE.md          ← this file
    │
    ▼
docs/DASHBOARD_METRICS.md       ← what each Grafana metric means
    │
    ▼
docs/HOW_IT_WORKS.md            ← architecture diagrams, every service explained
    │
    ├── docs/ARCHITECTURE.md    ← visual diagrams (CI/CD, Azure layout)
    │
    ▼
generator/runner.py             ← read the code
    │
    ▼
docs/semantic-conventions.md    ← naming rules (when you add metrics/spans)
    │
    ▼
README.md                       ← deploy to Azure, env vars, CI/CD
```

---

## Part 10 — Cheat sheet (print this)

| I want to… | Do this |
|------------|---------|
| Run locally | `python3 -m generator.runner` with `ALLOW_MOCK_MODE=true` |
| Understand dashboard metrics | [DASHBOARD_METRICS.md](./DASHBOARD_METRICS.md) |
| Find the main loop | `generator/runner.py` → `run_one_batch()` |
| See event shape | `generator/synthetic_generator.py` → `generate_event()` |
| Understand metrics | Prometheus — numbers, charts, alerts |
| Debug one slow request | Tempo — span tree |
| Search log lines | Loki or Log Analytics |
| See where OTLP goes | `infra/otel-collector-config.yaml` |
| Run tests | `pytest` |
| Check fake data | `python3 validation/check_data.py` |

---

## Quick reference — three tools side by side

| | Prometheus | Tempo | Loki |
|---|------------|-------|------|
| **Stores** | Numbers | Request timelines | Log lines |
| **Question** | “How many errors?” | “Why was abc-123 slow?” | “What did client X do?” |
| **Query language** | PromQL | TraceQL | LogQL |
| **Fed by** | OTel Collector | OTel Collector | OTel Collector |
| **Shown in** | Grafana charts | Grafana trace view | Grafana log explorer |

**Grafana** = the window that shows all three. **OTel Collector** = the post office that sorts and delivers to all three.
