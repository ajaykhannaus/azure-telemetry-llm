"""Plain-text application logs for client demos.

Production apps typically emit human-readable log lines to stdout (Spring Boot,
FastAPI/Uvicorn, nginx access logs). Structured JSON is an observability export;
this module generates the readable lines clients expect on /telemetry/logs/raw.
"""
from __future__ import annotations

import os
import random
from datetime import datetime, timezone
from typing import Any

from generator.telemetry_log_buffer import buffer

_SERVICE = os.getenv("AI_SERVICE", "ai-gateway")
_ENV = os.getenv("ENVIRONMENT", "prod")
_THREAD_NAMES = (
    "http-nio-8080-exec-1",
    "http-nio-8080-exec-2",
    "http-nio-8080-exec-3",
    "pool-2-thread-1",
    "pool-2-thread-5",
    "pool-2-thread-8",
)

_OP_PATH: dict[str, str] = {
    "chat_completion":         "/v1/chat/completions",
    "code_generation":         "/v1/code/generate",
    "code_review":             "/v1/code/review",
    "summarisation":           "/v1/summarize",
    "clinical_note_analysis":  "/v1/clinical/analyze",
    "product_description":     "/v1/products/describe",
    "data_analysis":           "/v1/data/analyze",
    "document_qa":             "/v1/documents/qa",
    "embedding":               "/v1/embeddings",
}


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _level_for_event(event: dict[str, Any]) -> str:
    if event.get("status") == "error":
        return "ERROR"
    if event.get("sla_breached"):
        return "WARN"
    return "INFO"


def _http_path(operation_name: str | None) -> str:
    op = operation_name or "inference"
    return _OP_PATH.get(op, f"/v1/{op.replace('_', '/')}")


def _http_status(event: dict[str, Any]) -> int:
    code = event.get("http_status_code")
    if isinstance(code, int) and code > 0:
        return code
    return 500 if event.get("status") == "error" else 200


def _short_id(value: str | None, n: int = 8) -> str:
    if not value:
        return "-"
    return value if len(value) <= n else value[:n]


def format_request_line(event: dict[str, Any]) -> str:
    """Spring Boot–style inference completion line."""
    level = _level_for_event(event)
    thread = random.choice(_THREAD_NAMES)
    path = _http_path(event.get("operation_name"))
    status = _http_status(event)
    latency = event.get("latency_ms", 0)
    tenant = event.get("client_name") or event.get("tenant_id") or "unknown"
    model = event.get("model_name") or "unknown"
    tokens = event.get("total_tokens", 0)
    cost = event.get("cost_usd", 0)
    req_id = _short_id(event.get("request_id"), 36)
    trace = _short_id(event.get("trace_id"), 16)

    if event.get("status") == "error":
        err = event.get("error_type") or "unknown_error"
        return (
            f"{_ts()}  {level} 28372 --- [{thread}] c.e.ai.gateway.InferenceService "
            f": {path} FAILED status={status} latencyMs={latency:.0f} tenant={tenant} "
            f"model={model} error={err} requestId={req_id} traceId={trace}"
        )

    stream = " stream" if event.get("streaming") else ""
    return (
        f"{_ts()}  {level} 28372 --- [{thread}] c.e.ai.gateway.InferenceService "
        f": {path} completed status={status} latencyMs={latency:.0f}{stream} "
        f"tenant={tenant} model={model} tokens={tokens} costUsd={cost:.6f} "
        f"requestId={req_id} traceId={trace}"
    )


def format_access_line(event: dict[str, Any]) -> str:
    """nginx-style access log line (common on API gateways)."""
    tenant = event.get("client_name") or "unknown"
    path = _http_path(event.get("operation_name"))
    status = _http_status(event)
    latency = int(event.get("latency_ms") or 0)
    tokens = event.get("total_tokens", 0)
    cost = event.get("cost_usd", 0)
    model = event.get("model_name") or "-"
    req_id = _short_id(event.get("request_id"), 12)
    now = datetime.now(timezone.utc).strftime("%d/%b/%Y:%H:%M:%S +0000")
    return (
        f'{tenant} - - [{now}] "POST {path} HTTP/1.1" {status} {latency} '
        f'tokens={tokens} cost={cost:.4f} model="{model}" req="{req_id}"'
    )


def format_prompt_audit_line(
    event: dict[str, Any],
    *,
    pii_detected: bool = False,
    entity_counts: dict[str, int] | None = None,
    prompt_hash: str = "",
) -> str:
    thread = random.choice(_THREAD_NAMES)
    tenant = event.get("client_name") or event.get("tenant_id") or "unknown"
    req_id = _short_id(event.get("request_id"), 36)
    entities = ",".join(f"{k}:{v}" for k, v in (entity_counts or {}).items()) or "none"
    pii_flag = "true" if pii_detected else "false"
    hash_short = _short_id(prompt_hash, 12)
    return (
        f"{_ts()}  INFO 28372 --- [{thread}] c.e.ai.gateway.audit.PromptAuditService "
        f": prompt audit requestId={req_id} tenant={tenant} piiDetected={pii_flag} "
        f"entities={entities} promptHash={hash_short}"
    )


def format_batch_line(summary: dict[str, Any]) -> str:
    thread = random.choice(_THREAD_NAMES)
    return (
        f"{_ts()}  INFO 28372 --- [{thread}] c.e.ai.gateway.worker.BatchScheduler "
        f": batch finished size={summary.get('batch_size', 0)} "
        f"ok={summary.get('successes', 0)} errors={summary.get('errors', 0)} "
        f"slaBreaches={summary.get('sla_breaches', 0)} "
        f"costUsd={summary.get('total_cost_usd', 0):.5f} "
        f"durationMs={int(float(summary.get('batch_duration_s', 0)) * 1000)}"
    )


def format_startup_line(config: dict[str, Any]) -> str:
    env = config.get("environment") or _ENV
    interval = config.get("batch_interval_s", "?")
    return (
        f"{_ts()}  INFO 28372 --- [main] c.e.ai.gateway.AiGatewayApplication "
        f": Started AiGatewayApplication env={env} service={_SERVICE} "
        f"batchIntervalSec={interval}"
    )


def _append(kind: str, line: str, *, tenant_id: str = "", request_id: str = "") -> None:
    buffer.append_plain(line)


def record_request(event: dict[str, Any]) -> None:
    """Buffer plain-text request + access lines for one LLM event."""
    tenant = str(event.get("client_name") or event.get("tenant_id") or "")
    req_id = str(event.get("request_id") or "")
    _append("request", format_request_line(event), tenant_id=tenant, request_id=req_id)
    _append("access", format_access_line(event), tenant_id=tenant, request_id=req_id)


def record_prompt_audit(
    event: dict[str, Any],
    *,
    pii_detected: bool = False,
    entity_counts: dict[str, int] | None = None,
    prompt_hash: str = "",
) -> None:
    tenant = str(event.get("client_name") or event.get("tenant_id") or "")
    req_id = str(event.get("request_id") or "")
    _append(
        "audit",
        format_prompt_audit_line(
            event,
            pii_detected=pii_detected,
            entity_counts=entity_counts,
            prompt_hash=prompt_hash,
        ),
        tenant_id=tenant,
        request_id=req_id,
    )


def record_batch(summary: dict[str, Any]) -> None:
    _append("batch", format_batch_line(summary))


def record_startup(config: dict[str, Any]) -> None:
    _append("startup", format_startup_line(config))
