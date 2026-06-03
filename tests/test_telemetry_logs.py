"""Tests for plain application logs and HTTP log endpoints."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

from generator import plain_app_logs, runner_http
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


def test_plain_request_line_looks_like_app_log():
    line = plain_app_logs.format_request_line({
        "request_id": "a8702644-a880-4c22-8e2d-9e4e13c0b25a",
        "trace_id": "127d86aa370614d7a742483b7a1ed71e",
        "client_name": "healthcare-portal",
        "model_name": "claude-haiku-3-5",
        "operation_name": "clinical_note_analysis",
        "latency_ms": 678.21,
        "total_tokens": 739,
        "cost_usd": 0.00120152,
        "status": "success",
        "http_status_code": 200,
        "streaming": False,
    })
    assert "InferenceService" in line
    assert "healthcare-portal" in line
    assert "/v1/clinical/analyze" in line
    assert "latencyMs=678" in line
    assert "{" not in line


def test_buffer_plain_and_json_separate():
    buf = TelemetryLogBuffer(max_size=10)
    buf.append_plain("2026-06-03 12:00:00.000  INFO app : request done")
    buf.append_raw(json.dumps({"message": "telemetry_event", "event_type": "telemetry_event"}))

    assert "request done" in buf.plain_lines(10)
    assert "telemetry_event" in buf.raw_lines(10)
    assert "request done" not in buf.raw_lines(10)


def test_runner_http_plain_raw_endpoint():
    runner_http._started = False
    runner_http._server = None
    buffer._plain.clear()
    buffer._raw.clear()
    buffer._parsed.clear()

    buffer.append_plain(
        "2026-06-03 12:00:00.000  INFO 28372 --- [http-nio-8080-exec-1] "
        "c.e.ai.gateway.InferenceService : /v1/chat/completions completed "
        "status=200 latencyMs=120 tenant=demo-client model=claude-sonnet "
        "tokens=100 costUsd=0.001000 requestId=req-1 traceId=abcd1234",
    )
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

    port = _free_port()
    server = runner_http.start(port)
    assert server is not None
    try:
        time.sleep(0.1)

        status, body, content_type = _get(f"http://127.0.0.1:{port}/telemetry/logs/raw")
        assert status == 200
        assert "text/plain" in content_type
        text = body.decode()
        assert "InferenceService" in text
        assert "demo-client" in text
        assert "{" not in text

        status, body, _ = _get(f"http://127.0.0.1:{port}/telemetry/logs/json")
        assert status == 200
        assert '"telemetry_event"' in body.decode()

        status, body, content_type = _get(f"http://127.0.0.1:{port}/telemetry/logs")
        assert status == 200
        assert "text/html" in content_type
        assert b"/telemetry/logs/raw" in body
    finally:
        server.shutdown()
        runner_http._started = False
        runner_http._server = None
