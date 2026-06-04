"""Structured JSON logging for Azure Container Apps / Log Analytics.

When running on Azure Container Apps, stdout is collected automatically and
appears in Log Analytics under the table ContainerAppConsoleLogs_CL (field: Log_s).
Because every line is valid JSON, KQL can parse fields with parse_json(Log_s).

Public API
----------
setup_structured_logging()       — call once at the very top of main()
log_event(event: dict)           — call per LLM event inside run_one_batch()
log_login_event(event: dict)     — call when a new session starts (turn 1)
log_startup_config(config: dict) — call once after setup to record runner config
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from generator.log_sanitize import sanitize_string, sanitize_value

_SERVICE = os.getenv("OTEL_SERVICE_NAME", "ai-telemetry")
_ENV     = os.getenv("ENVIRONMENT", "prod")

# Standard LogRecord attributes — must never appear in exported JSON logs.
_LOG_RECORD_STD_KEYS = frozenset({
    "args", "asctime", "created", "exc_info", "exc_text", "filename",
    "funcName", "levelname", "levelno", "lineno", "module", "msecs",
    "message", "msg", "name", "pathname", "process", "processName",
    "relativeCreated", "stack_info", "thread", "threadName", "taskName",
})


class JSONFormatter(logging.Formatter):
    """Format every log record as a single-line JSON object.

    Standard fields: timestamp, level, logger, message, module, funcName,
                     service_name, environment, exception (when present).
    Extra fields: any key injected via logging.info(..., extra={...}).
    """

    def format(self, record: logging.LogRecord) -> str:
        doc: dict[str, Any] = {
            "timestamp":    datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level":        record.levelname,
            "logger":       record.name,
            "message":      sanitize_string(record.getMessage()),
            "module":       record.module,
            "funcName":     record.funcName,
            "service_name": _SERVICE,
            "environment":  _ENV,
        }
        if record.exc_info:
            doc["exception"] = sanitize_string(self.formatException(record.exc_info))

        # Carry through caller `extra=` fields only — never LogRecord internals.
        for key, val in record.__dict__.items():
            if key not in _LOG_RECORD_STD_KEYS and key not in doc:
                doc[key] = sanitize_value(val)

        return json.dumps(doc, default=str)


def setup_structured_logging() -> None:
    """Replace all root logger handlers with a single JSON-to-stdout handler.

    Call this once at the very start of main(), before any other logging call.
    Safe to call multiple times — subsequent calls replace the handler cleanly.
    Also wires OTLP log export when OTEL_EXPORTER_OTLP_ENDPOINT is set.
    """
    root = logging.getLogger()
    for h in root.handlers[:]:
        root.removeHandler(h)
    formatter = JSONFormatter()
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root.addHandler(handler)
    root.setLevel(logging.INFO)

    from generator import otel_logging  # noqa: WPS433 — avoid circular import at module load

    otel_logging.setup_otel_logging(json_formatter=formatter)


def log_event(event: dict[str, Any]) -> None:
    """Emit one structured JSON log line per LLM event.

    Fields are chosen to be useful as Log Analytics filter/aggregate dimensions.

    Example KQL to query in Log Analytics:
        ContainerAppConsoleLogs_CL
        | extend e = parse_json(Log_s)
        | where e.event_type == "telemetry_event"
        | summarize avg(todouble(e.latency_ms)) by tostring(e.model_name)
    """
    from generator.prompt_logger import _current_trace_id

    logging.getLogger("generator.telemetry_event").info(
        "telemetry_event",
        extra={
            # ── Identity ─────────────────────────────────────────────────
            "event_type":          "telemetry_event",
            "request_id":          event.get("request_id"),
            "trace_id":            _current_trace_id() or event.get("trace_id"),
            "session_id":          event.get("session_id"),
            "turn_number":         event.get("turn_number"),
            "user_id":             event.get("user_id"),
            "client_name":         event.get("client_name"),
            "tenant_id":           event.get("client_name"),
            "data_classification": event.get("data_classification"),

            # ── Routing ──────────────────────────────────────────────────
            "model_name":          event.get("model_name"),
            "model_provider":      event.get("model_provider"),
            "capability_tier":     event.get("capability_tier"),
            "routing_reason":      event.get("routing_reason"),
            "operation_name":      event.get("operation_name"),
            "region":              event.get("region"),

            # ── Performance ──────────────────────────────────────────────
            "latency_ms":          event.get("latency_ms"),
            "queue_wait_ms":       event.get("queue_wait_ms"),
            "model_inference_ms":  event.get("model_inference_ms"),
            "first_token_ms":      event.get("first_token_ms"),
            "stream_response_ms":  event.get("stream_response_ms"),
            "streaming":           event.get("streaming"),
            "tokens_per_second":   event.get("tokens_per_second"),
            "sla_tier":            event.get("sla_tier"),
            "sla_target_ms":       event.get("sla_target_ms"),
            "sla_breached":        event.get("sla_breached"),

            # ── Tokens & cost ────────────────────────────────────────────
            "prompt_tokens":       event.get("prompt_tokens"),
            "completion_tokens":   event.get("completion_tokens"),
            "cache_read_tokens":   event.get("cache_read_tokens"),
            "total_tokens":        event.get("total_tokens"),
            "context_window_tokens":          event.get("context_window_tokens"),
            "context_window_utilization_pct": event.get("context_window_utilization_pct"),
            "cost_usd":            event.get("cost_usd"),
            "cache_savings_usd":   event.get("cache_savings_usd"),
            "daily_spend_usd":     event.get("daily_spend_usd"),
            "budget_exhausted":    event.get("budget_exhausted"),

            # ── Outcome ──────────────────────────────────────────────────
            "status":              event.get("status"),
            "http_status_code":    event.get("http_status_code"),
            "error_type":          event.get("error_type"),
            "error_category":      event.get("error_category"),
            "is_retried":          event.get("is_retried"),
            "retry_count":         event.get("retry_count"),

            # ── Safety & security ────────────────────────────────────────
            "toxicity_score":              event.get("toxicity_score"),
            "prompt_injection_detected":   event.get("prompt_injection_detected"),
            "jailbreak_attempt":           event.get("jailbreak_attempt"),
            "compliance_violation":        event.get("compliance_violation"),
        },
    )


def log_login_event(event: dict[str, Any]) -> None:
    """Emit a login/session-start event for user-level observability dashboards."""
    from generator.prompt_logger import _current_trace_id

    logging.getLogger("generator.login_event").info(
        "login_event",
        extra={
            "event_type":   "login_event",
            "user_id":      event.get("user_id"),
            "user_email":   event.get("user_email"),
            "session_id":   event.get("session_id"),
            "tenant_id":    event.get("client_name"),
            "client_name":  event.get("client_name"),
            "auth_method":  event.get("auth_method"),
            "trace_id":     _current_trace_id() or event.get("trace_id"),
            "project_id":   event.get("project_id"),
        },
    )


def log_startup_config(config: dict[str, Any]) -> None:
    """Emit runner startup configuration as a structured JSON line."""
    logging.getLogger("generator.runner").info(
        "runner_startup",
        extra={"event_type": "startup_config", **config},
    )
