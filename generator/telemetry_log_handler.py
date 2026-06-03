"""Logging handler that mirrors stdout JSON lines into the telemetry log buffer."""
from __future__ import annotations

import logging

from generator.telemetry_log_buffer import buffer


class TelemetryLogHandler(logging.Handler):
    """Capture formatted log lines for /telemetry/logs HTTP endpoints."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            buffer.append_raw(self.format(record))
        except Exception:
            self.handleError(record)
