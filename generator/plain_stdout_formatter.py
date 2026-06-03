"""Plain-text stdout formatter — production-style gateway log lines."""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from generator import plain_app_logs
from generator.azure_logger import record_to_event


class PlainStdoutFormatter(logging.Formatter):
    """Format log records as human-readable gateway lines (Spring Boot / nginx style)."""

    def format(self, record: logging.LogRecord) -> str:
        event_type = getattr(record, "event_type", None)
        event = record_to_event(record)

        if event_type == "telemetry_event":
            return plain_app_logs.format_request_line(event)
        if event_type == "access_log":
            return plain_app_logs.format_access_line(event)
        if event_type == "prompt_log_event":
            return plain_app_logs.format_prompt_audit_line(
                event,
                pii_detected=bool(event.get("pii_detected")),
                entity_counts=event.get("pii_entity_counts") or {},
                prompt_hash=str(event.get("prompt_hash") or ""),
            )
        if event_type == "startup_config":
            return plain_app_logs.format_startup_line(event)
        if event_type == "batch_summary":
            return plain_app_logs.format_batch_line(event)

        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S.%f",
        )[:-3]
        return f"{ts}  {record.levelname:5} [{record.name}] {record.getMessage()}"
