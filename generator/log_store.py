"""Persist application and telemetry logs to SQLite (+ optional Event Hub → ADX).

Local/demo: query via GET /telemetry/logs/db
Azure: publish ``app.log`` envelopes to Event Hub → ADX ``ObservabilityLogs`` table
"""
from __future__ import annotations

import json
import logging
import os
import queue
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

_MAX_QUEUE = int(os.getenv("LOG_DB_QUEUE_SIZE", "5000"))

_lock = threading.Lock()
_started = False
_queue: queue.Queue[dict[str, Any] | None] = queue.Queue(maxsize=_MAX_QUEUE)
_publisher: Any = None
_publisher_lock = threading.Lock()


def _enabled() -> bool:
    return os.getenv("LOG_DB_ENABLED", "true").lower() == "true"


def _db_path() -> str:
    return os.getenv("LOG_DB_PATH", "/tmp/telemetry_logs.db")


def _retention_days() -> int:
    return int(os.getenv("LOG_DB_RETENTION_DAYS", "7"))


def _publish_eh() -> bool:
    return os.getenv("LOG_DB_PUBLISH_EVENTHUB", "true").lower() == "true"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    path = _db_path()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS application_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            log_kind TEXT NOT NULL,
            line_text TEXT NOT NULL,
            tenant_id TEXT,
            request_id TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_application_logs_created
            ON application_logs(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_application_logs_kind
            ON application_logs(log_kind);

        CREATE TABLE IF NOT EXISTS telemetry_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            request_id TEXT,
            trace_id TEXT,
            tenant_id TEXT,
            model_name TEXT,
            operation_name TEXT,
            status TEXT,
            latency_ms REAL,
            cost_usd REAL,
            total_tokens INTEGER,
            payload_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_telemetry_events_created
            ON telemetry_events(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_telemetry_events_request
            ON telemetry_events(request_id);
        """,
    )
    conn.commit()


def _purge_old(conn: sqlite3.Connection) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=_retention_days())).isoformat()
    conn.execute("DELETE FROM application_logs WHERE created_at < ?", (cutoff,))
    conn.execute("DELETE FROM telemetry_events WHERE created_at < ?", (cutoff,))
    conn.commit()


def _get_publisher() -> Any:
    global _publisher
    with _publisher_lock:
        if _publisher is not None:
            return _publisher
        if not _publish_eh():
            return None
        try:
            from observability.publisher import EventHubPublisher

            _publisher = EventHubPublisher()
        except Exception as exc:
            logger.warning("Log store Event Hub publisher unavailable: %s", exc)
            _publisher = None
        return _publisher


def _publish_app_log(
    line: str,
    *,
    log_kind: str,
    tenant_id: str = "",
    request_id: str = "",
    level: str = "INFO",
) -> None:
    pub = _get_publisher()
    if pub is None or pub.mock_mode:
        return
    try:
        from observability.envelope import EVENT_APP_LOG, build_envelope

        envelope = build_envelope(
            EVENT_APP_LOG,
            {
                "level": level,
                "logger": "ai-gateway.application",
                "message": line,
                "attributes": {
                    "log_kind": log_kind,
                    "tenant_id": tenant_id,
                    "request_id": request_id,
                    "format": "plain",
                },
            },
            event_id=str(uuid.uuid4()),
            tenant_id=tenant_id or None,
            correlation_id=request_id or None,
        )
        pub._publish_envelope(envelope)
    except Exception as exc:
        logger.debug("app.log publish skipped: %s", exc)


def _worker() -> None:
    pending_purge = True

    while True:
        item = _queue.get()
        if item is None:
            break
        conn = _connect()
        try:
            _init_schema(conn)
            if pending_purge:
                _purge_old(conn)
                pending_purge = False
            kind = item["kind"]
            if kind == "plain":
                conn.execute(
                    """
                    INSERT INTO application_logs
                        (created_at, log_kind, line_text, tenant_id, request_id)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        item["created_at"],
                        item["log_kind"],
                        item["line_text"],
                        item.get("tenant_id") or "",
                        item.get("request_id") or "",
                    ),
                )
                _publish_app_log(
                    item["line_text"],
                    log_kind=item["log_kind"],
                    tenant_id=item.get("tenant_id") or "",
                    request_id=item.get("request_id") or "",
                )
            elif kind == "telemetry":
                doc = item["doc"]
                conn.execute(
                    """
                    INSERT INTO telemetry_events
                        (created_at, request_id, trace_id, tenant_id, model_name,
                         operation_name, status, latency_ms, cost_usd, total_tokens,
                         payload_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        item["created_at"],
                        doc.get("request_id"),
                        doc.get("trace_id"),
                        doc.get("client_name") or doc.get("tenant_id"),
                        doc.get("model_name"),
                        doc.get("operation_name"),
                        doc.get("status"),
                        doc.get("latency_ms"),
                        doc.get("cost_usd"),
                        doc.get("total_tokens"),
                        json.dumps(doc, default=str),
                    ),
                )
            conn.commit()
        except Exception as exc:
            logger.error("Log store write failed: %s", exc)
        finally:
            conn.close()
            _queue.task_done()


def start() -> None:
    global _started
    if not _enabled() or _started:
        return
    with _lock:
        if _started:
            return
        threading.Thread(target=_worker, name="log-store", daemon=True).start()
        _started = True
        logger.info(
            "Log store enabled → %s (retention %dd)",
            _db_path(),
            _retention_days(),
        )


def _enqueue(item: dict[str, Any]) -> None:
    if not _enabled():
        return
    start()
    try:
        _queue.put_nowait(item)
    except queue.Full:
        logger.warning("Log store queue full — dropping log line")


def save_plain(
    log_kind: str,
    line: str,
    *,
    tenant_id: str = "",
    request_id: str = "",
) -> None:
    _enqueue({
        "kind": "plain",
        "created_at": _utc_now(),
        "log_kind": log_kind,
        "line_text": line,
        "tenant_id": tenant_id,
        "request_id": request_id,
    })


def save_telemetry_event(doc: dict[str, Any]) -> None:
    if doc.get("event_type") != "telemetry_event" and doc.get("message") != "telemetry_event":
        return
    _enqueue({
        "kind": "telemetry",
        "created_at": _utc_now(),
        "doc": doc,
    })


def query_application_logs(
    limit: int = 200,
    log_kind: str | None = None,
) -> list[dict[str, Any]]:
    if not _enabled() or not os.path.exists(_db_path()):
        return []
    limit = max(1, min(limit, 1000))
    conn = _connect()
    try:
        _init_schema(conn)
        if log_kind:
            rows = conn.execute(
                """
                SELECT created_at, log_kind, line_text, tenant_id, request_id
                FROM application_logs
                WHERE log_kind = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (log_kind, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT created_at, log_kind, line_text, tenant_id, request_id
                FROM application_logs
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        out = [dict(row) for row in rows]
        out.reverse()
        return out
    finally:
        conn.close()


def query_telemetry_events(limit: int = 200) -> list[dict[str, Any]]:
    if not _enabled() or not os.path.exists(_db_path()):
        return []
    limit = max(1, min(limit, 1000))
    conn = _connect()
    try:
        _init_schema(conn)
        rows = conn.execute(
            """
            SELECT created_at, request_id, trace_id, tenant_id, model_name,
                   operation_name, status, latency_ms, cost_usd, total_tokens,
                   payload_json
            FROM telemetry_events
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            try:
                item["payload"] = json.loads(item.pop("payload_json"))
            except Exception:
                item["payload"] = {}
            out.append(item)
        out.reverse()
        return out
    finally:
        conn.close()


def stats() -> dict[str, Any]:
    if not _enabled():
        return {"enabled": False}
    path = _db_path()
    if not os.path.exists(path):
        return {
            "enabled": True,
            "path": path,
            "application_logs": 0,
            "telemetry_events": 0,
        }
    conn = _connect()
    try:
        _init_schema(conn)
        app_count = conn.execute("SELECT COUNT(*) FROM application_logs").fetchone()[0]
        tel_count = conn.execute("SELECT COUNT(*) FROM telemetry_events").fetchone()[0]
        return {
            "enabled": True,
            "path": path,
            "application_logs": app_count,
            "telemetry_events": tel_count,
            "retention_days": _retention_days(),
        }
    finally:
        conn.close()
