# Dashboard Metrics Guide

**Audience:** Developers learning what each Grafana panel shows, which metric powers it, and why that metric exists.

**Prerequisites:** Read [BEGINNER_GUIDE.md](./BEGINNER_GUIDE.md) first if you are new to Prometheus and Grafana.

---

## How metrics get from Python to a dashboard

```
generate_event() in synthetic_generator.py
        │
        ▼
record_metrics(event) in otel_metrics.py     ← creates the numbers
        │
        ▼
OpenTelemetry SDK → OTLP → OTel Collector → Prometheus
        │
        ▼
Grafana dashboard panel runs a PromQL query   ← reads the numbers
```

Every request triggers `record_metrics()` once. Dashboards **query** the stored time series — they do not compute costs or latency themselves.

**Source code:** `generator/otel_metrics.py` → `record_metrics()`  
**Canonical names:** `generator/semantic_conventions.py` → `METRIC_*` constants  
**Alert rules:** `rules.yml`  
**Dashboards:** `dashboards/01-*.json` through `dashboards/09-*.json`

---

## Prometheus naming (read this once)

OpenTelemetry metric names get transformed when they land in Prometheus:

| Defined in code | Appears in Prometheus as | Type |
|-----------------|--------------------------|------|
| `ai_gateway_request_count` | `ai_gateway_request_count_total` | Counter |
| `ai_gateway_request_duration` (unit: ms) | `ai_gateway_request_duration_milliseconds_bucket`, `_sum`, `_count` | Histogram |
| `ai_gateway_request_token` | `ai_gateway_request_token_total` | Counter |
| `ai_gateway_request_cost` (unit: USD) | `ai_gateway_request_cost_USD_total` | Counter |
| `ai_gateway_exception_count` | `ai_gateway_exception_count_total` | Counter |
| `ai_telemetry_runner_batch_duration_seconds` | `ai_telemetry_runner_batch_duration_seconds_bucket`, `_sum`, `_count` | Histogram |
| `ai_telemetry_runner_publish_errors_total` | (same) | Counter |
| `ai_telemetry_runner_kafka_queue_depth` | (same) | Gauge |

**Counter** = always goes up (request count, total cost). Use `rate()` or `increase()` in queries.  
**Histogram** = distribution of values (latency). Use `histogram_quantile()` for p50/p95/p99.  
**Gauge** = current value at a point in time (queue depth).

---

## Labels (dimensions you can filter by)

Every gateway metric shares these labels (from `record_metrics()`):

| Label | Meaning | Example values |
|-------|---------|----------------|
| `tenant_id` | Client / team using the gateway | `healthcare-portal`, `legal-firm` |
| `model_name` | LLM model used | `claude-sonnet-4-5`, `gpt-4o-mini` |
| `model_provider` | Vendor | `anthropic`, `openai`, `google` |
| `operation_name` | What the request did | `chat_completion`, `code_generation` |
| `status` | Outcome | `success`, `error` |
| `environment` | Deployment | `dev`, `staging`, `prod` |
| `region` | Cloud region | `us-east-1` |
| `service` | Logical service name | `ai-gateway` |

**Error-only extra labels** on `ai_gateway_exception_count_total`:

| Label | Meaning | Example |
|-------|---------|---------|
| `error_type` | Specific failure | `rate_limit`, `timeout`, `model_unavailable` |
| `error_category` | Grouped failure class | `throttling`, `availability`, `auth` |
| `http_status` | HTTP code | `429`, `504`, `500` |

**Token metric extra label** on `ai_gateway_request_token_total`:

| Label | Meaning |
|-------|---------|
| `token_type` | `prompt`, `completion`, or `cache_read` |

---

## Core application metrics (the five golden metrics)

These five are recorded for **every LLM request**.

### 1. `ai_gateway_request_count_total`

| | |
|---|---|
| **Type** | Counter |
| **Meaning** | Number of LLM requests processed |
| **Recorded when** | Every event, success or error (+1 each time) |
| **Unit** | requests |
| **Why it exists** | Traffic volume is the most basic health signal — are requests flowing? |

**Typical queries:**

```promql
# Requests per minute
sum(rate(ai_gateway_request_count_total[1m])) * 60

# By model
sum by (model_name) (rate(ai_gateway_request_count_total[2m])) * 60
```

**Used in dashboards:** 01, 02, 04 (filters), 07 (filters)  
**Key panels:** "Requests / min", "Request Rate by Model", "Requests by Tenant"

---

### 2. `ai_gateway_request_duration_milliseconds` (histogram)

| | |
|---|---|
| **Type** | Histogram |
| **Meaning** | How long each request took (end-to-end latency) |
| **Recorded when** | Every event — value = `event["latency_ms"]` |
| **Unit** | milliseconds |
| **Why it exists** | Users care about speed. Percentiles (p50/p95/p99) show typical vs worst-case experience. |

**Typical queries:**

```promql
# p99 latency over last 5 minutes
histogram_quantile(0.99,
  sum by (le) (rate(ai_gateway_request_duration_milliseconds_bucket[5m]))
)

# Average latency
sum(rate(ai_gateway_request_duration_milliseconds_sum[5m]))
/ sum(rate(ai_gateway_request_duration_milliseconds_count[5m]))
```

**Used in dashboards:** 01, 03  
**Key panels:** "p99 Latency (5m)", "Request Latency — p50/p95/p99", "p95 Latency by Model"

**SLO alert:** p99 > 5000 ms for 5 minutes → `AIGatewayHighLatencyP99` in `rules.yml`

**Exemplars:** When recorded inside an active trace span, Grafana can link a latency point to a Tempo trace (panel: "p99 Latency with Trace Exemplars").

---

### 3. `ai_gateway_request_token_total`

| | |
|---|---|
| **Type** | Counter |
| **Meaning** | Total tokens consumed, split by type |
| **Recorded when** | Every event — three increments per request (prompt, completion, cache_read) |
| **Unit** | tokens |
| **Why it exists** | Token usage drives LLM cost and capacity planning. Cache-read tokens indicate cost savings from prompt caching. |

**Typical queries:**

```promql
# Total tokens in last 24h
sum(increase(ai_gateway_request_token_total[24h]))

# Prompt tokens only
sum(increase(ai_gateway_request_token_total{token_type="prompt"}[24h]))

# Token rate by type
sum(rate(ai_gateway_request_token_total{token_type="completion"}[5m]))
```

**Used in dashboards:** 04  
**Key panels:** "Total Tokens Today", "Prompt/Completion/Cache Read Tokens", "Token Consumption Rate by Type"

---

### 4. `ai_gateway_request_cost_USD_total`

| | |
|---|---|
| **Type** | Counter |
| **Meaning** | Cumulative spend in US dollars |
| **Recorded when** | Every event — value = `event["cost_usd"]` (calculated from model pricing × tokens) |
| **Unit** | USD |
| **Why it exists** | FinOps and tenant chargeback — who is spending how much, on which model? |

**Typical queries:**

```promql
# Total cost today
sum(increase(ai_gateway_request_cost_USD_total[24h]))

# Cost per minute by tenant
sum by (tenant_id) (rate(ai_gateway_request_cost_USD_total[5m])) * 60

# Cost share by model (last hour)
sort_desc(sum by (model_name) (increase(ai_gateway_request_cost_USD_total[1h])))
```

**Used in dashboards:** 01, 04  
**Key panels:** "Total Cost Today", "Cost Rate by Model/Tenant", "Daily Budget Utilisation"

---

### 5. `ai_gateway_exception_count_total`

| | |
|---|---|
| **Type** | Counter |
| **Meaning** | Number of **failed** requests only |
| **Recorded when** | Only when `event["status"] == "error"` (+1 per error) |
| **Unit** | errors |
| **Why it exists** | Separates failure analysis from total traffic. Lets you break down errors by type, HTTP code, and tenant without mixing in successes. |

**Typical queries:**

```promql
# Error rate as percentage
sum(rate(ai_gateway_exception_count_total[5m]))
/ sum(rate(ai_gateway_request_count_total[5m])) * 100

# Errors by type
sum by (error_type) (rate(ai_gateway_exception_count_total[5m]))
```

**Used in dashboards:** 01, 02  
**Key panels:** "Error Rate", "Error Rate by Type", "Errors by HTTP Status Code"

**Note:** Error **rate** is usually computed as `exceptions / total_requests`, not by reading this counter alone.

---

## Runner self-metrics (observe the observer)

These measure the **telemetry pipeline itself**, not LLM traffic. Recorded in `record_self_metric()` at the end of each batch.

### 6. `ai_telemetry_runner_batch_duration_seconds`

| | |
|---|---|
| **Type** | Histogram |
| **Meaning** | Wall-clock time to process one full batch (all events + flush) |
| **Why it exists** | If batches take longer than `BATCH_INTERVAL_S` (5s), the runner falls behind. Detects performance regressions in the pipeline code. |

**Used in:** Dashboard 07, alert `AITelemetryRunnerStuck` (zero batch rate for 2 min)

---

### 7. `ai_telemetry_runner_publish_errors_total`

| | |
|---|---|
| **Type** | Counter |
| **Label** | `reason` — e.g. `exception`, `flush_error` |
| **Meaning** | Times Event Hubs publish failed after retries |
| **Why it exists** | Silent data loss is worse than loud failure. Surfaces Kafka/Event Hubs connectivity issues. |

**Used in:** Dashboard 07, alert `AITelemetryPublishErrors`

---

### 8. `ai_telemetry_runner_kafka_queue_depth`

| | |
|---|---|
| **Type** | Gauge |
| **Meaning** | Messages waiting in the local Kafka producer buffer |
| **Why it exists** | Rising queue depth = broker slow or network congested. Early warning before publish errors spike. |

**Used in:** Dashboard 07 — "Kafka Queue Depth"

---

## Derived metrics (computed by Prometheus rules)

These do **not** come directly from the runner. Prometheus pre-computes them in `rules.yml` so dashboards and alerts query stable series.

| Metric | Formula (simplified) | Meaning | Why derived |
|--------|---------------------|---------|-------------|
| `ai_gateway:sli:availability:5m` | success requests ÷ total requests (5m window) | Availability SLI | Reused by alerts and multiple panels |
| `ai_gateway:sli:availability:30m` | same, 30m window | Longer-window availability | Slow-burn alert |
| `ai_gateway:sli:availability:1h` | same, 1h window | Hourly availability | Fast-burn alert |
| `ai_gateway:sli:availability:6h` | same, 6h window | Half-day availability | Executive dashboard headline |
| `ai_gateway:sli:latency_p99_ms:5m` | p99 of latency histogram | Latency SLI | Shared by dashboard 01 and 03 |
| `ai_gateway:slo:error_budget_remaining` | how much of 99.5% SLO budget is left | Error budget (0–100%) | Executive "are we on track for the month?" |
| `ai_gateway:pods_running:current` | count of Running pods | Infra health | Dashboard 07 |

**SLO target:** 99.5% availability over 30 days (0.5% error budget).

**Burn rate panels** on dashboard 01 show how fast you are consuming that budget:

```promql
(1 - ai_gateway:sli:availability:1h) / 0.005
```

A value of `14.4` means "burning 14.4× faster than sustainable" → page on-call.

---

## Dashboard-by-dashboard metric map

### Dashboard 1 — Request & Traffic Metrics

**Audience:** Product / ops — "How much traffic is flowing and to whom?"

| Panel | Metric / query | What it tells you |
|-------|----------------|-------------------|
| Total requests | `increase(request_count[6h])` | Request volume in the selected window |
| RPM | `rate(request_count) × 60` | Current requests per minute |
| RPM By Model | `rate(request_count)` by `model_name` | Which models are busiest |
| Active users/sessions | distinct `user_id` / `session_id` in Loki (5m) | Live user and session count |
| Error Rate By Model | `exception_count / request_count` by model | Per-model failure rate |
| Model Provider Distribution | by `model_provider` | Vendor mix (Anthropic, OpenAI, Google) |
| Model Distribution (last 1h) | by `model_name` | Hourly model share |

---

### Dashboard 2 — Traffic & Request Analytics

**Audience:** Product / ops — "Who is using what?"

| Panel | Metric / query | What it tells you |
|-------|----------------|-------------------|
| Requests / min by Model | `rate(request_count)` by `model_name` | Model popularity |
| Requests / min by Tenant | by `tenant_id` | Client traffic share |
| Requests / min by Operation | by `operation_name` | Use-case mix (chat vs code vs summarisation) |
| Model Distribution | `increase(request_count[1h])` | Hourly model share |
| Model Provider Distribution | by `model_provider` | Anthropic vs OpenAI vs Google split |
| Error Rate by Type | `rate(exception_count)` by `error_type` | rate_limit vs timeout vs auth failures |
| Errors by HTTP Status | by `http_status` | 429 vs 504 vs 500 breakdown |
| Error Category Mix | by `error_category` | throttling vs availability vs validation |
| SLA Breach Rate by Tenant | error rate filtered by tenant | Which clients hit SLA limits |
| Routing Reason (Loki) | log query on `routing_reason` | Why a model was chosen (cost vs latency vs fallback) |
| Live Telemetry Events (Loki) | log stream | Raw event feed for debugging |

---

### Dashboard 03 — Latency & Performance Metrics

**Audience:** SRE — "Why is it slow?"

| Panel | Metric / query | What it tells you |
|-------|----------------|-------------------|
| End-to-end response latency | `_sum / _count` on duration histogram | Average gateway response time |
| Request Latency — p50 / p95 / p99 | `histogram_quantile` on duration | Full latency distribution |
| Model Specific Latency | p95 by `model_name` | Which models are slowest |
| First token latency (Model Based) | Loki `first_token_ms` (streaming) | Time-to-first-token |
| Queue delays | Loki `queue_wait_ms` | Time waiting before model inference |

**Why Loki for phase breakdown?** Phase timings (`queue_wait_ms`, etc.) are high-cardinality per request — stored in logs and traces, not Prometheus counters.

---

### Dashboard 4 — Cost & Usage Metrics

**Audience:** FinOps — "How much are we spending?"

| Panel | Metric / query | What it tells you |
|-------|----------------|-------------------|
| Cost per request | Loki `cost_usd` avg | Average USD per request |
| Cost per user/session | total cost ÷ active users/sessions | Spend per active user or session |
| Daily/monthly spend | `increase(cost[24h])` / `[30d]` | Rolling spend totals |
| Total cost breakdown | by `tenant_id` | Who drives FinOps charges |
| Model-wise cost breakdown | by `model_name` | Which models are most expensive |
| Cache hit savings | Loki `cache_savings_usd` | USD saved via prompt cache hits |

---

### Dashboard 08 — Token & Context Metrics

**Audience:** ML ops / platform — "Are we filling context windows and streaming efficiently?"

| Panel | Metric / query | What it tells you |
|-------|----------------|-------------------|
| Output Token Count | `rate(ai_gateway_request_token_total{token_type="completion"})` | Completion (output) token throughput |
| Total tokens per request | Loki `total_tokens` | Prompt + completion + cache per request |
| Context Window Utilization | Loki `context_window_utilization_pct` | How full the model context window is |
| Prompt size | Loki `prompt_tokens` | Input token volume per request |
| Live token generation rate | `rate(completion tokens[1m])` | Near-real-time output token rate |
| Streaming response latency | Loki `stream_response_ms` (streaming only) | Time spent streaming the response body |
| Tokens/sec | Loki `tokens_per_second` (streaming only) | Observed streaming throughput |
| Real-time error spikes | `rate(ai_gateway_exception_count_total[1m])` vs 5m baseline | Sudden failure bursts |

---

### Dashboard 05 — Model Quality Metrics

**Audience:** ML ops — "Are answers good?" (requires evaluator enabled / `ALLOW_MOCK_MODE=true`)

Most panels use **Loki log queries** on `event_type="eval_result"`, not Prometheus:

| Panel | Source field | Meaning |
|-------|--------------|---------|
| Hallucination rate | `faithfulness < 5` ÷ eval count | % of judged responses flagged as hallucinating |
| Factual accuracy | `faithfulness × 10` | Judge faithfulness on 0–100 % scale |
| Relevance score | `relevance` (0–10) | Does it answer what was asked? |
| Groundedness score | `groundedness` (0–10) | Are claims supported by sources? |
| Evaluation Coverage | eval events ÷ total events | What % of traffic is being judged |
| Low-Quality Responses | `faithfulness < 5` | Flagged bad responses (log panel) |

**Why logs not metrics?** Quality scoring is sampled (~1%) and rich — easier to store as structured log events than as Prometheus labels.

---

### Dashboard 6 — Safety & Security Metrics

**Audience:** Security / compliance

Uses **Loki** on `prompt_log_event` and `telemetry_event` logs:

| Panel | Source | Meaning |
|-------|--------|---------|
| Toxicity score | `avg(toxicity_score)` on prompt logs | Content-safety severity (0–100 %) |
| PII detection rate | `pii_detected=true` ÷ total prompt logs | % of prompts containing PII |
| Prompt injection attempts | `prompt_injection_detected=true` | Heuristic injection detections |
| Jailbreak attempts | `jailbreak_attempt=true` | Role-override / DAN-style attempts |
| Compliance violations | `compliance_violation=true` | Policy / classification breaches |
| PII Hits (24h) | count of PII detections | Volume of redactions |
| PHI / PII Request Count | `data_classification` label | Requests handling sensitive data |
| Unique Prompts Audited | distinct `prompt_hash` | Audit coverage |
| Data Classification Mix | by `data_classification` | phi vs pii vs confidential vs internal |
| PII by Tenant | grouped by `tenant_id` | Which clients send sensitive data |

**Why not Prometheus?** PII details must never become metric labels (cardinality + compliance risk).

---

### Dashboard 7 — Infrastructure Metrics

**Audience:** Platform team — "Is the pipeline healthy?"

Mix of **simulated Kubernetes metrics** (from `pod_metrics_simulator.py` in dev), **gateway OTel metrics**, **runner self-metrics**, and **OTel Collector metrics**:

| Panel | Metric | Meaning |
|-------|--------|---------|
| CPU utilization | `container_cpu_usage_seconds_total` ÷ running pods | Average CPU load per gateway pod |
| Model throughput | `rate(ai_gateway_request_token_total{token_type="completion"})` | Completion tokens per second |
| OOM failures | `kube_pod_container_oom_killed_total` | Out-of-memory container terminations |
| Pod/container health | `replicas_available / spec_replicas` | Deployment readiness % |
| Auto-scaling events | `kube_horizontalpodautoscaler_scaling_events_total` | HPA scale-up / scale-down count |
| API error rate | `request_count{status="error"}` ÷ total requests | Gateway API error percentage |
| HPA Current/Desired | `kube_hpa_status_*` | Replica targets |
| Pod Restarts | `kube_pod_container_status_restarts_total` | Crash loops |
| Batch Duration p99 | `ai_telemetry_runner_batch_duration_seconds` | Runner processing speed |
| Kafka Queue Depth | `ai_telemetry_runner_kafka_queue_depth` | Publish backlog |
| Collector Export Queue | `otelcol_exporter_queue_size` | Collector backpressure |

---

### Dashboard 9 — User-Level Observability

**Audience:** Product / platform — "Who is using the gateway and are usage patterns spiking?"

Uses **Loki** on `event_type="login_event"` and `event_type="telemetry_event"`:

| Panel | Source field | Meaning |
|-------|--------------|---------|
| Logins (24h) | `login_event` count | New session starts (turn 1) |
| Active users (24h) | distinct `user_id` in telemetry | Daily active users |
| Monthly active users (30d) | distinct `user_id` in login events | MAU proxy |
| LLM usage spike (15m vs prev 15m) | token volume comparison | Sudden platform-wide usage growth |
| Login track | `login_event` per 5m | Session-start trend |
| Users added (daily active logins) | distinct login users per day | User growth |
| Top 10 users — tokens | `total_tokens` by `user_id` | Heaviest token consumers |
| Top 10 users — token rate (5m) | live token rate by user | Who is active right now |
| Top 10 users — session time | summed `latency_ms` by user | Time spent in sessions |
| Session usage by user | tokens by `user_id` + `session_id` | Per-session drill-down |
| Token volume — spike detector | 5m buckets vs 1h rolling avg | Visual spike detection |
| Top 10 users — spike ratio | 15m tokens ÷ hourly baseline share | Per-user usage anomalies |
| Recent login events | `login_event` log stream | Live login audit |

**Note:** `login_event` is emitted once per session when `turn_number == 1`.

---

## Prometheus vs Loki in dashboards — quick rule

| Use Prometheus when… | Use Loki (logs) when… |
|----------------------|------------------------|
| Aggregating over many requests | Need per-request detail |
| Charting rates, percentiles, totals | Phase timings, routing reason, PII flags |
| Alerting (SLO burn, error rate) | Audit trails, eval scores, budget status |
| Low-cardinality labels | High-cardinality or sensitive fields |

---

## Common PromQL patterns used in this project

| Pattern | Example | Meaning |
|---------|---------|---------|
| **Rate per second** | `rate(metric[5m])` | How fast counter is increasing |
| **Rate per minute** | `rate(metric[5m]) * 60` | Requests/min, USD/min |
| **Total in window** | `increase(metric[24h])` | "Today" totals |
| **Percentage** | `a / clamp_min(b, 1e-9) * 100` | Error rate % (avoid divide-by-zero) |
| **Percentile** | `histogram_quantile(0.99, ...)` | p99 latency |
| **Top N** | `sort_desc(sum by (label) (...))` | Rank tenants/models by volume |

---

## Where to go next

| Topic | Doc |
|-------|-----|
| Metric naming contract | [semantic-conventions.md](./semantic-conventions.md) |
| How metrics are recorded in code | `generator/otel_metrics.py` |
| Alert thresholds | `rules.yml` |
| Architecture overview | [HOW_IT_WORKS.md](./HOW_IT_WORKS.md) |
| Beginner glossary | [BEGINNER_GUIDE.md](./BEGINNER_GUIDE.md) |
