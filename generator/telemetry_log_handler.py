"""Logging handler that mirrors stdout lines into the telemetry log buffer."""
from __future__ import annotations

import logging

from generator.azure_logger import record_to_log_doc
from generator.telemetry_log_buffer import buffer


class TelemetryLogHandler(logging.Handler):
    """Capture formatted log lines for /telemetry/logs HTTP endpoints."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            line = self.format(record)
            buffer.append_stdout(line, record_to_log_doc(record))
        except Exception:
            self.handleError(record)
