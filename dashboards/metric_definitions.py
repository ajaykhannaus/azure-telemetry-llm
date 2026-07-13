"""Panel title → info-tooltip text for Grafana metric panels (ⓘ icon)."""

METRIC_DEFINITIONS: dict[str, str] = {
    # 1 — Infrastructure observability
    "CPU utilization": (
        "How hard the gateway servers are working. High means they are under heavy load."
    ),
    "Model throughput": (
        "How many AI output tokens the system produces per second."
    ),
    "OOM failures": (
        "Times a container ran out of memory and was killed in the last 24 hours."
    ),
    "Pod/container health": (
        "How many gateway pods are up and ready. 100% means all are healthy."
    ),
    "Auto-scaling events": (
        "How often the system added or removed pods in the last 24 hours."
    ),
    "API error rate": (
        "Percent of requests that failed. Lower is better."
    ),
    "Errors summary — API error rate": (
        "Failed requests in the last 5 minutes. Green is healthy."
    ),
    "Errors summary — Exceptions (1h)": (
        "Total failures in the last hour. Zero or low is normal."
    ),
    "Errors summary — By type": (
        "Which error happened most. Longest bar = main problem."
    ),
    "Errors summary — By category": (
        "What kind of problem it is. Biggest slice = check that first."
    ),
    "Errors summary — Recent error logs": (
        "Latest failed requests. Newest at the top."
    ),
    "Errors (5m)": (
        "Failures in the last 5 minutes. Shown beside the tabs."
    ),
    "AI errors (5m)": (
        "AI failures in the last 5 minutes. Shown beside the tabs."
    ),
    "AI — Errors (5m)": (
        "AI request failures in the last 5 minutes."
    ),
    "AI — Evaluator Errors (24h)": (
        "Quality-check failures in the last 24 hours."
    ),
    "Safety alerts (24h)": (
        "PII detected in the last 24 hours. Review if high."
    ),
    "User errors (24h)": (
        "User request failures in the last 24 hours."
    ),
    "HPA Current vs Desired Replicas": (
        "How many pods are running vs how many the system wants."
    ),
    "Pod Restart Rate": (
        "How often pods restart. Frequent restarts may mean crashes."
    ),
    "Container Memory RSS by Pod": (
        "Memory used by each gateway pod."
    ),
    "Container CPU Usage by Pod": (
        "CPU used by each gateway pod."
    ),
    "Node Memory Available Over Time": (
        "Free memory on cluster machines over time."
    ),
    "Node CPU Usage (user mode)": (
        "CPU used by applications on each cluster machine."
    ),
    "Batch Duration Heatmap": (
        "How long each telemetry batch took to process."
    ),
    "Kafka Queue Depth": (
        "How many events are waiting to be sent. A growing queue means backlog."
    ),
    "Publish Error Rate by Reason": (
        "How many events failed to send, and why."
    ),
    "Runner Event Publish Rate": (
        "How many events the system sends per second."
    ),
    "Batch Duration p99": (
        "Slowest 1% of batch processing times. High means occasional delays."
    ),
    "Collector Exporter Queue Size": (
        "How full the telemetry export queues are."
    ),
    "Collector Export Failures": (
        "How often sending traces or logs to storage failed."
    ),
    "Collector Export Throughput & Failures": (
        "How much telemetry is exported and how many exports fail."
    ),

    # 2 — Network observability
    "End-to-end response latency": (
        "Average time from request to full response, in milliseconds."
    ),
    "Request Latency — p50 / p95 / p99": (
        "Typical and worst-case response times. p99 is the slowest 1% of requests."
    ),
    "Queue delays": (
        "Time requests wait in queue before the model starts. High means congestion."
    ),

    # 3 — AI observability
    "Model Specific Latency": (
        "Response time by AI model. Compare which models are slower."
    ),
    "First token latency (Model Based)": (
        "Time until the first word appears in a streaming reply, by model."
    ),
    "Hallucination rate": (
        "Percent of answers flagged as not factual. Lower is better."
    ),
    "Hallucination rate over time": (
        "How often answers are flagged as not factual over time."
    ),
    "Factual accuracy": (
        "How factually correct answers are judged to be. Higher is better."
    ),
    "Relevance score": (
        "How well answers match the question. Higher is better."
    ),
    "Groundedness score": (
        "How well answers stay supported by provided context. Higher is better."
    ),
    "Evaluation Coverage": (
        "Percent of requests that received a quality check."
    ),
    "Evaluator Errors (24h)": (
        "Quality checks that failed in the last 24 hours."
    ),
    "Low-Quality Responses (hallucination flagged)": (
        "Individual answers flagged as low quality. Use for review."
    ),
    "Live token generation rate": (
        "How fast each model is producing output right now."
    ),
    "Streaming response latency": (
        "How long streaming replies take, by model."
    ),
    "Streaming tokens/sec": (
        "Streaming speed by model. Higher means faster output."
    ),
    "Avg stream tokens/s": (
        "Average streaming speed across all models."
    ),

    # 4 — Data observability
    "Total requests": (
        "Total number of requests in the selected time range."
    ),
    "RPM": (
        "Requests per minute over time."
    ),
    "RPM by Model": (
        "Requests per minute for each AI model."
    ),
    "RPM by Model (current)": (
        "Current requests per minute, ranked by model."
    ),
    "RPM Share by Model": (
        "Each model's share of total traffic."
    ),
    "Error RPM by Model": (
        "Failed requests per minute for each model."
    ),
    "Error Rate by Model": (
        "Percent of each model's requests that failed."
    ),
    "Model Provider Distribution": (
        "Traffic split across vendors (e.g. Anthropic, OpenAI, Google)."
    ),
    "Model Distribution (last 1h)": (
        "Which models handled the most requests in the last hour."
    ),
    "Requests / min by Model": (
        "Live request rate for each model."
    ),
    "Requests / min by Department": (
        "Live request rate for each team or department."
    ),
    "Requests / min by Operation": (
        "Live request rate by use case (e.g. chat, code)."
    ),
    "Error Rate by Type": (
        "Failures over time, split by error type."
    ),
    "Errors by HTTP Status Code (last 1h)": (
        "Failures by HTTP code (e.g. 429, 500). Tallest bar = most common."
    ),
    "Error Category Mix": (
        "Failures by category. Biggest slice = main issue."
    ),
    "SLA Breach Rate by Department": (
        "Percent of failed requests per department. High means missing targets."
    ),
    "Total Requests by Routing Reason (last 1h)": (
        "Why each model was chosen (cost, speed, fallback, etc.)."
    ),
    "Live Telemetry Events": (
        "Live stream of recent requests for debugging."
    ),

    # 5 — User observability
    "Active users": (
        "People using the system in the last 5 minutes."
    ),
    "Active sessions": (
        "Open sessions in the last 5 minutes."
    ),
    "Logins (24h)": (
        "New sign-ins or session starts in the last 24 hours."
    ),
    "Active users (24h)": (
        "People who used the system in the last 24 hours."
    ),
    "Active users by department (24h)": (
        "Active users per team in the last 24 hours."
    ),
    "Monthly active users (30d)": (
        "People who logged in at least once in the last 30 days."
    ),
    "LLM usage spike (15m vs prev 15m)": (
        "Sudden jump in token usage compared to the previous 15 minutes."
    ),
    "Login track": (
        "Logins over time."
    ),
    "Users added (daily active logins)": (
        "People who logged in today."
    ),
    "Daily active users (24h)": (
        "People who logged in during the last 24 hours."
    ),
    "Top 10 users — tokens (24h)": (
        "Who used the most tokens in the last 24 hours."
    ),
    "Top 10 users — token rate (5m)": (
        "Who is using the most tokens right now."
    ),
    "Top 10 users — session time (6h)": (
        "Who spent the most time in sessions recently."
    ),
    "Session usage by user": (
        "Token usage per person and department."
    ),
    "Top users by tokens (6h)": (
        "Heaviest token users in the last 6 hours."
    ),
    "Session time by user (top 10, 5m)": (
        "Who spent the most session time in the last 5 minutes."
    ),
    "Token volume — spike detector (5m buckets)": (
        "Token usage spikes compared to the recent average."
    ),
    "Top 10 users — spike ratio (15m vs prev 15m)": (
        "Users whose usage jumped compared to the prior 15 minutes."
    ),
    "Recent login events": (
        "Latest sign-ins with user, team, and method."
    ),

    # 6 — Cost & Usage Observability
    "Cost per request": (
        "Average dollar cost of one request."
    ),
    "Cost per user/session": (
        "Average cost per request over time."
    ),
    "Daily/monthly spend": (
        "Total spend in the last day and last month."
    ),
    "Cost by department": (
        "Which teams spent the most in the last 24 hours."
    ),
    "Total cost breakdown": (
        "Which models cost the most in the last 24 hours."
    ),
    "Model-wise cost breakdown": (
        "Spend ranked by model."
    ),
    "Cache hit savings": (
        "Money saved by reusing cached prompt content."
    ),
    "Output tokens": (
        "Total AI output tokens in the selected time range."
    ),
    "Avg tokens / request": (
        "Average tokens used per request."
    ),
    "Context fill": (
        "How full the model's context window is on average. Very high may truncate input."
    ),
    "Output Token Count": (
        "Output tokens over time, split by model."
    ),
    "Output tokens by model (now)": (
        "Current output speed by model."
    ),
    "Token type mix": (
        "Split between input, output, and cached tokens."
    ),
    "Total tokens per request": (
        "Average total tokens per request over time."
    ),
    "Prompt size by model": (
        "Average input size by model."
    ),
    "Context Window Utilization (%)": (
        "How full prompts are on average. High means little room left."
    ),
    "Context fill by model": (
        "How full each model's context window is."
    ),
    "Prompt size trend": (
        "Average input size over time. Larger prompts cost more and can be slower."
    ),
    "Errors by type (5m)": (
        "Failures in the last 5 minutes by type. Longest bar = main problem."
    ),
    "Prompt size": (
        "Average input tokens per request."
    ),
    "Tokens/sec": (
        "How fast tokens are streamed during responses."
    ),
    "Real-time error spikes": (
        "Sudden increases in failures."
    ),

    # 7 — Safety and security
    "Toxicity score": (
        "How toxic or harmful prompt content is rated. Lower is better."
    ),
    "PII detection rate": (
        "Percent of prompts that contained personal information."
    ),
    "Prompt injection attempts": (
        "Attempts to manipulate the model with hidden instructions."
    ),
    "Jailbreak attempts": (
        "Attempts to bypass safety rules."
    ),
    "Compliance violations": (
        "Requests that broke policy or classification rules."
    ),
    "Prompt injection attempts / min": (
        "Injection attempts per minute over time."
    ),
    "Jailbreak attempts / min": (
        "Jailbreak attempts per minute over time."
    ),
    "Compliance violations / min": (
        "Policy violations per minute over time."
    ),
    "PII Events Today": (
        "Prompts with personal information detected today."
    ),
    "PHI Requests Today": (
        "Health-related sensitive requests today."
    ),
    "PII Requests Today": (
        "Personal-information requests today."
    ),
    "Unique Prompt Hashes (24h)": (
        "How many distinct prompts were logged (without storing raw text)."
    ),
    "Data Classification Distribution": (
        "Mix of sensitivity levels (public, internal, PII, PHI, etc.)."
    ),
    "PII Events by Department": (
        "Which teams sent prompts with personal information."
    ),
    "PHI + PII Volume by Department (last 1h)": (
        "Sensitive requests per team in the last hour."
    ),
    "Prompt Log Events (PII-scrubbed)": (
        "Audit log of prompts with sensitive content removed."
    ),
    "PHI / PII Requests with Trace Links": (
        "Sensitive requests you can trace for investigation."
    ),
    "Safety incidents (injection, jailbreak, compliance)": (
        "Combined log of security and policy incidents."
    ),
}
