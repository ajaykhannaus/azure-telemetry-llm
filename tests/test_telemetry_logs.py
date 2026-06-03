"""Tests for runner HTTP log endpoints."""
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


def test_buffer_plain_and_stdout_separate():
    buf = TelemetryLogBuffer(max_size=10)
    buf.append_plain("2026-06-03 12:00:00.000  INFO demo gateway line")
    buf.append_raw(json.dumps({"message": "telemetry_event", "event_type": "telemetry_event"}))

    assert "demo gateway" in buf.plain_lines(10)
    assert "telemetry_event" in buf.raw_lines(10)
    assert "demo gateway" not in buf.raw_lines(10)


def test_runner_http_raw_is_stdout_not_demo():
    runner_http._started = False
    runner_http._server = None
    buffer._plain.clear()
    buffer._raw.clear()
    buffer._parsed.clear()

    buffer.append_stdout(
        "2026-06-03 12:00:00.000  INFO 28372 --- [http-nio-8080-exec-1] "
        "c.e.ai.gateway.InferenceService : /v1/chat/completions completed "
        "status=200 latencyMs=100 tenant=healthcare-portal model=gpt-4o "
        "tokens=50 costUsd=0.002000 requestId=req-raw-1 traceId=127d86aa",
        {
            "timestamp": "2026-06-01T12:00:00+00:00",
            "message": "telemetry_event",
            "event_type": "telemetry_event",
            "request_id": "req-raw-1",
        },
    )
    buffer.append_plain("2026-06-03 12:00:00.000  INFO legacy demo-only buffer line")

    port = _free_port()
    server = runner_http.start(port)
    assert server is not None
    try:
        time.sleep(0.1)

        status, body, content_type = _get(f"http://127.0.0.1:{port}/telemetry/logs/raw?header=0")
        assert status == 200
        text = body.decode()
        assert "req-raw-1" in text
        assert "InferenceService" in text

        status, body, _ = _get(f"http://127.0.0.1:{port}/telemetry/logs/demo")
        assert status == 200
        assert b"InferenceService" in body
        assert b"legacy demo-only" in body
    finally:
        server.shutdown()
        runner_http._started = False
        runner_http._server = None


def test_plain_demo_line_is_not_raw_stdout():
    line = plain_app_logs.format_request_line({
        "request_id": "abc",
        "client_name": "healthcare-portal",
        "model_name": "gpt-4o",
        "operation_name": "chat_completion",
        "latency_ms": 100,
        "total_tokens": 50,
        "cost_usd": 0.002,
        "status": "success",
        "http_status_code": 200,
        "streaming": False,
    })
    assert "InferenceService" in line
    assert not line.strip().startswith("{")
