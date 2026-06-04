"""Tests for SQLite log persistence."""
from __future__ import annotations

import os
import tempfile
import time

from generator import log_store, plain_app_logs


def test_log_store_persists_plain_and_telemetry():
    with tempfile.TemporaryDirectory() as tmp:
        db = os.path.join(tmp, "logs.db")
        os.environ["LOG_DB_PATH"] = db
        os.environ["LOG_DB_ENABLED"] = "true"
        os.environ["LOG_DB_PUBLISH_EVENTHUB"] = "false"

        log_store._started = False
        while not log_store._queue.empty():
            try:
                log_store._queue.get_nowait()
                log_store._queue.task_done()
            except Exception:
                break
        log_store.start()

        plain_app_logs.record_request({
            "request_id": "req-db-1",
            "client_name": "acme-corp",
            "model_name": "gpt-4o",
            "operation_name": "chat_completion",
            "latency_ms": 100,
            "total_tokens": 50,
            "cost_usd": 0.002,
            "status": "success",
            "http_status_code": 200,
            "streaming": False,
        })
        log_store.save_telemetry_event({
            "event_type": "telemetry_event",
            "request_id": "req-db-1",
            "client_name": "acme-corp",
            "model_name": "gpt-4o",
            "status": "success",
            "latency_ms": 100,
            "cost_usd": 0.002,
            "total_tokens": 50,
        })

        deadline = time.time() + 3
        while time.time() < deadline:
            stats = log_store.stats()
            if stats.get("application_logs", 0) >= 2 and stats.get("telemetry_events", 0) >= 1:
                break
            time.sleep(0.1)

        stats = log_store.stats()
        assert stats["application_logs"] >= 2
        assert stats["telemetry_events"] >= 1

        rows = log_store.query_application_logs(10, log_kind="request")
        assert any("acme-corp" in r["line_text"] for r in rows)

        events = log_store.query_telemetry_events(10)
        assert events[-1]["request_id"] == "req-db-1"
        assert events[-1]["payload"]["model_name"] == "gpt-4o"
