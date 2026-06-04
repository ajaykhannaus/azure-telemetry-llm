"""Panel title → info-tooltip text for Grafana metric panels (ⓘ icon)."""

METRIC_DEFINITIONS: dict[str, str] = {
    # Dashboard 1 — Request & Traffic Metrics
    "Total requests": (
        "Count of gateway requests in the selected time range. "
        "Source: Prometheus counter `ai_gateway_request_count_total` (use `increase` over the window)."
    ),
    "RPM": (
        "Requests per minute — current traffic rate. "
        "Source: `rate(ai_gateway_request_count_total[1m]) × 60`."
    ),
    "RPM By Model": (
        "Request rate per minute split by `model_name`. "
        "Shows which LLM models are receiving the most traffic."
    ),
    "Active users/sessions": (
        "Distinct `user_id` and `session_id` values seen in telemetry logs in the last 5 minutes. "
        "Source: Loki `telemetry_event` logs (not Prometheus)."
    ),
    "Error Rate By Model": (
        "Percentage of requests that failed, per model: "
        "`exception_count / request_count × 100`. "
        "Spikes often indicate rate limits, timeouts, or model outages for that model."
    ),
    "Model Provider Distribution": (
        "Share of requests by vendor (`model_provider`: anthropic, openai, google, etc.) over the last hour."
    ),
    "Model Distribution (last 1h)": (
        "Share of requests by `model_name` over the last hour. "
        "Useful for capacity and cost planning per model."
    ),

    # Dashboard 2 — Traffic & Request Analytics
    "Requests / min by Model": (
        "Live request rate per model (`rate × 60`). "
        "Filtered by tenant template variable when set."
    ),
    "Requests / min by Tenant": (
        "Live request rate per `tenant_id` — which clients drive load."
    ),
    "Requests / min by Operation": (
        "Traffic by `operation_name` (e.g. chat_completion, code_generation) — use-case mix."
    ),
    "Error Rate by Type": (
        "Failed requests per second by `error_type` (rate_limit, timeout, model_unavailable, etc.)."
    ),
    "Errors by HTTP Status Code (last 1h)": (
        "Volume of exceptions in the last hour grouped by `http_status` (429, 504, 500, …)."
    ),
    "Error Category Mix": (
        "Failures grouped by `error_category` (throttling, availability, auth, validation)."
    ),
    "SLA Breach Rate by Tenant": (
        "Per-tenant error rate (%): requests with `status=error` ÷ all requests. "
        "High values mean that tenant is missing SLA targets."
    ),
    "Total Requests by Routing Reason (last 1h)": (
        "Why the gateway chose a model (`routing_reason` from logs): cost, latency, fallback, policy, etc. "
        "Source: Loki `telemetry_event`."
    ),
    "Live Telemetry Events": (
        "Streaming audit of recent `telemetry_event` log lines — request id, model, latency, tenant, routing. "
        "Use for live debugging; not aggregated metrics."
    ),

    # Dashboard 3 — Latency & Performance Metrics
    "End-to-end response latency": (
        "Average gateway response time in ms: histogram `_sum / _count` on `ai_gateway_request_duration_milliseconds`. "
        "Includes queue, model, and streaming time."
    ),
    "Request Latency — p50 / p95 / p99": (
        "Latency percentiles from the request duration histogram. "
        "p99 is the slowest 1% — the usual SLO pain metric."
    ),
    "Model Specific Latency": (
        "p95 end-to-end latency per `model_name`. "
        "Compares which models are consistently slower."
    ),
    "First token latency (Model Based)": (
        "Average `first_token_ms` for streaming requests, by model. "
        "Source: Loki logs — time until the first token is returned to the client."
    ),
    "Queue delays": (
        "Average `queue_wait_ms` before the model starts processing. "
        "Source: Loki — separates queue congestion from model inference time."
    ),

    # Dashboard 4 — Cost & Usage Metrics
    "Cost per request": (
        "Average USD cost per request from log field `cost_usd`. "
        "Source: Loki `telemetry_event` (synthetic generator computes per-model pricing)."
    ),
    "Cost per user/session": (
        "Average spend per active user or session in the window — total cost ÷ distinct users/sessions in logs."
    ),
    "Daily/monthly spend": (
        "Total USD spent: 24h and 30d `increase` on `ai_gateway_request_cost_USD_total`."
    ),
    "Total cost breakdown": (
        "Share of 24h spend by `tenant_id` — who is driving FinOps charges."
    ),
    "Model-wise cost breakdown": (
        "24h spend ranked by `model_name` — which models are most expensive."
    ),
    "Cache hit savings": (
        "USD saved via prompt cache hits (`cache_savings_usd` in logs). "
        "Higher values mean caching is reducing billable prompt tokens."
    ),

    # Dashboard 5 — Model Quality Metrics
    "Hallucination rate": (
        "% of judged responses where `faithfulness < 5` (0–10 judge scale). "
        "Source: Loki `eval_result` events (~sampled traffic). Requires evaluator enabled."
    ),
    "Hallucination rate over time": (
        "Rolling 5m percentage of judged responses flagged as hallucinating (`faithfulness < 5`). "
        "Source: Loki `eval_result` events."
    ),
    "Factual accuracy": (
        "Mean judge `faithfulness` × 10, shown as 0–100%. "
        "Higher is more factually aligned with sources/context."
    ),
    "Relevance score": (
        "Mean judge `relevance` (0–10): does the answer address the user question?"
    ),
    "Groundedness score": (
        "Mean judge `groundedness` (0–10): are claims supported by provided context/sources?"
    ),
    "Evaluation Coverage": (
        "% of telemetry events that also have an `eval_result` log — how much traffic is quality-judged."
    ),
    "Evaluator Errors (24h)": (
        "Count of eval runs that failed (e.g. judge timeout) in 24h. "
        "Non-zero means quality pipeline is unhealthy."
    ),
    "Low-Quality Responses (hallucination flagged)": (
        "Raw `eval_result` logs where faithfulness failed — drill-down for bad responses."
    ),

    # Dashboard 6 — Safety & Security Metrics
    "Toxicity score": (
        "Average content-safety `toxicity_score` on prompt logs, scaled to 0–100%. "
        "Source: Loki `prompt_log_event`."
    ),
    "PII detection rate": (
        "% of prompt logs with `pii_detected=true`. "
        "PII must stay in logs, not Prometheus labels."
    ),
    "Prompt injection attempts": (
        "Count of prompts flagged `prompt_injection_detected=true` in 24h."
    ),
    "Jailbreak attempts": (
        "Count of prompts flagged `jailbreak_attempt=true` (role-override / DAN-style) in 24h."
    ),
    "Compliance violations": (
        "Count of prompts with `compliance_violation=true` (policy / classification breach) in 24h."
    ),
    "Prompt injection attempts / min": (
        "Rate of detected injection attempts per minute — live security trend."
    ),
    "Jailbreak attempts / min": (
        "Rate of jailbreak detections per minute."
    ),
    "Compliance violations / min": (
        "Rate of compliance violations per minute."
    ),
    "PII Events Today": (
        "Total prompt logs with PII detected in the last 24h."
    ),
    "PHI Requests Today": (
        "Telemetry events with `data_classification=phi` (protected health information) in 24h."
    ),
    "PII Requests Today": (
        "Telemetry events with `data_classification=pii` in 24h."
    ),
    "Unique Prompt Hashes (24h)": (
        "Distinct `prompt_hash` values audited — coverage of prompt logging without storing raw text."
    ),
    "Data Classification Distribution": (
        "Mix of `data_classification` labels (phi, pii, confidential, internal, …) in the last hour."
    ),
    "PII Events by Tenant": (
        "PII detections per `tenant_id` over time — which clients send sensitive prompts."
    ),
    "PHI + PII Volume by Tenant (last 1h)": (
        "Requests handling phi or pii classification, by tenant, last hour."
    ),
    "Prompt Log Events (PII-scrubbed)": (
        "Audit stream of `prompt_log_event` entries — content is scrubbed; use for security review."
    ),
    "PHI / PII Requests with Trace Links": (
        "Table of sensitive requests with `request_id`, tenant, model, and `trace_id` for Tempo drill-down."
    ),
    "Safety incidents (injection, jailbreak, compliance)": (
        "Log lines where any safety flag fired — combined injection, jailbreak, or compliance events."
    ),

    # Dashboard 7 — Infrastructure Metrics
    "CPU utilization": (
        "Average CPU usage per running gateway pod: "
        "`rate(container_cpu_usage_seconds_total) / running_pod_count × 100`."
    ),
    "Model throughput": (
        "Completion (output) tokens per second: "
        "`rate(ai_gateway_request_token_total{token_type=\"completion\"})`."
    ),
    "OOM failures": (
        "Container out-of-memory kills in the gateway namespace (`kube_pod_container_oom_killed_total`)."
    ),
    "Pod/container health": (
        "Deployment readiness: available replicas ÷ desired replicas × 100."
    ),
    "Auto-scaling events": (
        "HPA scale-up/down events in 24h (`kube_horizontalpodautoscaler_scaling_events_total`)."
    ),
    "API error rate": (
        "Gateway API errors: `request_count{status=error}` ÷ total requests × 100."
    ),
    "HPA Current vs Desired Replicas": (
        "Horizontal Pod Autoscaler current, desired, min, and max replica counts."
    ),
    "Pod Restart Rate": (
        "Container restart rate per pod — elevated values suggest crash loops."
    ),
    "Container Memory RSS by Pod": (
        "Resident memory (`container_memory_rss`) per ai-gateway pod."
    ),
    "Container CPU Usage by Pod": (
        "CPU cores used per pod (`rate(container_cpu_usage_seconds_total)`)."
    ),
    "Node Memory Available Over Time": (
        "Cluster node memory available vs total — capacity headroom."
    ),
    "Node CPU Usage (user mode)": (
        "Node CPU time in user mode — host-level utilization."
    ),
    "Batch Duration Heatmap": (
        "Distribution of synthetic telemetry runner batch processing times (`ai_telemetry_runner_batch_duration_seconds`)."
    ),
    "Kafka Queue Depth": (
        "Current depth of the runner publish queue (`ai_telemetry_runner_kafka_queue_depth` gauge)."
    ),
    "Publish Error Rate by Reason": (
        "Failed event publishes per second by `reason` label on `ai_telemetry_runner_publish_errors_total`."
    ),
    "Batch Duration p99": (
        "99th percentile batch processing duration — tail latency of the telemetry pipeline."
    ),
    "Collector Exporter Queue Size": (
        "OTel Collector exporter queue depth (Tempo, Prometheus remote write, Loki) — backpressure indicator."
    ),
    "Collector Export Failures": (
        "Rate of failed span and log exports from the OTel Collector."
    ),

    # Dashboard 8 — Token & Context Metrics
    "Output Token Count": (
        "Completion (output) token throughput per second, total and by model."
    ),
    "Total tokens per request": (
        "Average prompt + completion + cache tokens per request from Prometheus token counters."
    ),
    "Context Window Utilization (%)": (
        "How full the model context window is (`context_window_utilization_pct` in logs). "
        "High values risk truncation errors."
    ),
    "Prompt size": (
        "Average prompt (input) tokens per request — drives cost and latency."
    ),
    "Live token generation rate": (
        "1-minute rate of completion tokens — near-real-time streaming throughput."
    ),
    "Streaming response latency": (
        "Average `stream_response_ms` for streaming responses — time to finish sending the body."
    ),
    "Tokens/sec": (
        "Observed `tokens_per_second` from streaming requests in logs."
    ),
    "Real-time error spikes": (
        "Exception count increase over 5m and per-minute error rate — detects sudden failure bursts."
    ),

    # Dashboard 9 — User-Level Observability
    "Logins (24h)": (
        "Count of `login_event` logs in 24h — emitted when a new session starts (turn 1)."
    ),
    "Active users (24h)": (
        "Distinct `user_id` values with at least one `telemetry_event` in 24h."
    ),
    "Monthly active users (30d)": (
        "Distinct users with a `login_event` in the last 30 days — monthly active user (MAU) proxy."
    ),
    "LLM usage spike (15m vs prev 15m)": (
        "Percent change in total tokens: last 15m vs the prior 15m window "
        "(computed as [15m] ÷ ([30m] − [15m])). High values indicate sudden platform-wide LLM usage growth."
    ),
    "Login track": (
        "Login/session-start events per 5m bucket from `login_event` logs."
    ),
    "Users added (daily active logins)": (
        "Distinct users who logged in per day — cumulative user growth trend (daily active users)."
    ),
    "Top 10 users — tokens (24h)": (
        "Users ranked by sum of `total_tokens` over 24h — who is consuming the most tokens."
    ),
    "Top 10 users — token rate (5m)": (
        "Live top 10 users by tokens consumed in each 5m window."
    ),
    "Top 10 users — session time (latency sum, 6h)": (
        "Users ranked by summed `latency_ms` across requests — proxy for time spent in sessions."
    ),
    "Session usage by user": (
        "Per `user_id` + `session_id` token totals (top 50) — drill into individual sessions."
    ),
    "Session time by user (top 10, 5m)": (
        "Top 10 users by summed request latency per 5m — who is actively spending time right now."
    ),
    "Token volume — spike detector (5m buckets)": (
        "Total token volume per 5m vs 1h rolling average — visual spike detection for LLM usage."
    ),
    "Top 10 users — spike ratio (15m vs 1h baseline)": (
        "Per-user ratio: tokens in last 15m ÷ (tokens in last 1h × 0.25). "
        "Values above ~1.5 mean usage in the last 15m exceeds a fair share of the hourly baseline."
    ),
    "Recent login events": (
        "Live stream of `login_event` logs with user, session, tenant, and auth method."
    ),
}
