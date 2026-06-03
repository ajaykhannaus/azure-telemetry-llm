"""Tests for plain-text stdout logging."""
from __future__ import annotations

import json
import logging

import pytest

from generator import azure_logger
from generator.telemetry_log_buffer import buffer


@pytest.fixture(autouse=True)
def _reset_logging(monkeypatch):
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    for h in logging.getLogger().handlers[:]:
        logging.getLogger().removeHandler(h)
    buffer._plain.clear()
    buffer._raw.clear()
    buffer._parsed.clear()
    yield
    for h in logging.getLogger().handlers[:]:
        logging.getLogger().removeHandler(h)


def test_log_event_emits_plain_stdout(monkeypatch, capsys):
    monkeypatch.setenv("LOG_STDOUT_FORMAT", "plain")
    azure_logger.setup_structured_logging()

    azure_logger.log_event({
        "request_id": "req-plain-1",
        "trace_id": "trace-abc",
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

    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert "InferenceService" in out
    assert "healthcare-portal" in out
    assert "req-plain-1" in out
    assert not out.lstrip().startswith("{")


def test_log_event_emits_json_stdout_when_configured(monkeypatch, capsys):
    monkeypatch.setenv("LOG_STDOUT_FORMAT", "json")
    azure_logger.setup_structured_logging()

    azure_logger.log_event({
        "request_id": "req-json-1",
        "client_name": "acme",
        "model_name": "gpt-4o",
        "operation_name": "chat_completion",
        "latency_ms": 50,
        "total_tokens": 10,
        "cost_usd": 0.001,
        "status": "success",
        "http_status_code": 200,
    })

    captured = capsys.readouterr()
    line = (captured.out + captured.err).strip().splitlines()[0]
    doc = json.loads(line)
    assert doc["event_type"] == "telemetry_event"
    assert doc["request_id"] == "req-json-1"


def test_plain_stdout_populates_structured_buffer(monkeypatch):
    monkeypatch.setenv("LOG_STDOUT_FORMAT", "plain")
    azure_logger.setup_structured_logging()

    azure_logger.log_event({
        "request_id": "req-buffer-1",
        "client_name": "acme",
        "model_name": "gpt-4o",
        "operation_name": "chat_completion",
        "latency_ms": 50,
        "total_tokens": 10,
        "cost_usd": 0.001,
        "status": "success",
        "http_status_code": 200,
    })

    entries = buffer.formatted(10)
    assert any(e.get("request_id") == "req-buffer-1" for e in entries)
    raw = buffer.raw_lines(10)
    assert "InferenceService" in raw
    assert not raw.lstrip().startswith("{")


def test_default_plain_when_mock_mode(monkeypatch):
    monkeypatch.delenv("LOG_STDOUT_FORMAT", raising=False)
    monkeypatch.setenv("ALLOW_MOCK_MODE", "true")
    assert azure_logger.stdout_format() == "plain"


def test_default_json_in_production_profile(monkeypatch):
    monkeypatch.delenv("LOG_STDOUT_FORMAT", raising=False)
    monkeypatch.setenv("ALLOW_MOCK_MODE", "false")
    assert azure_logger.stdout_format() == "json"
