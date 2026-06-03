"""Tests for telemetry log buffer and runner HTTP endpoints."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from generator import runner_http
from generator.telemetry_log_buffer import TelemetryLogBuffer, buffer


def _free_port() -> int:
    import socket

    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _get(url: str, headers: dict[str, str] | None = None) -> tuple[int, bytes, str]:
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=2) as resp:
            return resp.status, resp.read(), resp.headers.get("Content-Type", "")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), exc.headers.get("Content-Type", "")


def test_buffer_raw_and_formatted_filter():
    buf = TelemetryLogBuffer(max_size=10)
    buf.append_raw(json.dumps({"message": "batch done", "level": "INFO"}))
    buf.append_raw(json.dumps({
        "message": "telemetry_event",
        "event_type": "telemetry_event",
        "request_id": "abc",
        "model_name": "gpt-4o",
    }))

    raw = buf.raw_lines(10)
    assert "batch done" in raw
    assert "telemetry_event" in raw

    formatted = buf.formatted(10)
    assert len(formatted) == 1
    assert formatted[0]["request_id"] == "abc"


def test_runner_http_telemetry_endpoints():
    runner_http._started = False
    runner_http._server = None
    buffer._raw.clear()
    buffer._parsed.clear()

    buffer.append_raw(json.dumps({
        "timestamp": "2026-06-01T12:00:00+00:00",
        "message": "telemetry_event",
        "event_type": "telemetry_event",
        "request_id": "req-1",
        "client_name": "demo-client",
        "model_name": "claude-sonnet",
        "status": "success",
        "latency_ms": 120,
        "cost_usd": 0.001,
    }))
    buffer.append_raw(json.dumps({"message": "noise", "level": "INFO"}))

    port = _free_port()
    server = runner_http.start(port)
    assert server is not None
    try:
        time.sleep(0.1)

        status, body, content_type = _get(f"http://127.0.0.1:{port}/telemetry/logs/raw")
        assert status == 200
        assert "text/plain" in content_type
        assert "req-1" in body.decode()
        assert "noise" in body.decode()

        status, body, content_type = _get(
            f"http://127.0.0.1:{port}/telemetry/logs?format=json",
        )
        assert status == 200
        doc = json.loads(body.decode())
        assert doc["count"] == 1
        assert doc["entries"][0]["request_id"] == "req-1"

        status, body, content_type = _get(f"http://127.0.0.1:{port}/telemetry/logs")
        assert status == 200
        assert "text/html" in content_type
        assert b"req-1" in body
        assert b"/telemetry/logs/raw" in body
    finally:
        server.shutdown()
        runner_http._started = False
        runner_http._server = None
