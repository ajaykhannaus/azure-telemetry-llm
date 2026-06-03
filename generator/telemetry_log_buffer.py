"""In-memory ring buffer of recent log lines for HTTP demo endpoints.

  - stdout lines → /telemetry/logs/raw   (exact container stdout / Log Analytics)
  - parsed docs  → /telemetry/logs        (formatted HTML table)
  - plain lines  → /telemetry/logs/demo   (legacy buffer; mirrors stdout in plain mode)
"""
from __future__ import annotations

import json
import os
import threading
from collections import deque
from typing import Any

_TELEMETRY_EVENT_TYPES = frozenset({
    "telemetry_event",
    "prompt_log_event",
    "startup_config",
})
_TELEMETRY_MESSAGES = frozenset({
    "telemetry_event",
    "prompt_log_event",
    "runner_startup",
})


class TelemetryLogBuffer:
    def __init__(self, max_size: int = 500) -> None:
        self._max_size = max(1, max_size)
        self._lock = threading.Lock()
        self._plain: deque[str] = deque(maxlen=self._max_size)
        self._raw: deque[str] = deque(maxlen=self._max_size)
        self._parsed: deque[dict[str, Any]] = deque(maxlen=self._max_size)

    def append_plain(self, line: str) -> None:
        line = line.rstrip("\n")
        if not line:
            return
        with self._lock:
            self._plain.append(line)

    def plain_lines(self, limit: int) -> str:
        limit = max(1, min(limit, self._max_size))
        with self._lock:
            lines = list(self._plain)[-limit:]
        if not lines:
            return ""
        return "\n".join(lines) + "\n"

    def append_stdout(self, line: str, doc: dict[str, Any] | None = None) -> None:
        line = line.rstrip("\n")
        if not line:
            return

        parsed: dict[str, Any]
        if doc is not None:
            parsed = doc
        else:
            try:
                loaded = json.loads(line)
                parsed = loaded if isinstance(loaded, dict) else {"_value": loaded}
            except json.JSONDecodeError:
                parsed = {"_unparsed": line}

        with self._lock:
            self._raw.append(line)
            if _is_telemetry_record(parsed):
                self._parsed.append(parsed)
            if not line.lstrip().startswith("{"):
                self._plain.append(line)

    def append_raw(self, line: str) -> None:
        """Backward-compatible alias for tests and direct buffer writes."""
        self.append_stdout(line)

    def raw_lines(self, limit: int) -> str:
        limit = max(1, min(limit, self._max_size))
        with self._lock:
            lines = list(self._raw)[-limit:]
        if not lines:
            return ""
        return "\n".join(lines) + "\n"

    def formatted(self, limit: int) -> list[dict[str, Any]]:
        limit = max(1, min(limit, self._max_size))
        with self._lock:
            items = list(self._parsed)
        selected: list[dict[str, Any]] = []
        for item in reversed(items):
            if _is_telemetry_record(item):
                selected.append(item)
            if len(selected) >= limit:
                break
        selected.reverse()
        return selected

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "plain_buffered": len(self._plain),
                "json_buffered": len(self._raw),
                "capacity": self._max_size,
            }


def _is_telemetry_record(doc: dict[str, Any]) -> bool:
    event_type = doc.get("event_type")
    if event_type in _TELEMETRY_EVENT_TYPES:
        return True
    return doc.get("message") in _TELEMETRY_MESSAGES


buffer = TelemetryLogBuffer(int(os.getenv("TELEMETRY_LOG_BUFFER_SIZE", "500")))
