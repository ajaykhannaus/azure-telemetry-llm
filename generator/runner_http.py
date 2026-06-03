"""Combined runner HTTP server on PROMETHEUS_PORT.

Serves:
  /metrics              — Prometheus scrape endpoint
  /telemetry/logs       — formatted telemetry view (HTML or JSON)
  /telemetry/logs/raw   — plain-text application logs (real-world style)
  /telemetry/logs/json  — structured JSON stdout (Log Analytics Log_s style)
"""
from __future__ import annotations

import html
import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from generator.telemetry_log_buffer import buffer

logger = logging.getLogger(__name__)

_server: ThreadingHTTPServer | None = None
_started = False


def _prometheus_payload() -> tuple[bytes, str]:
    try:
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

        return generate_latest(), CONTENT_TYPE_LATEST
    except ImportError:
        return b"# prometheus_client not installed\n", "text/plain; charset=utf-8"


def _parse_limit(query: dict[str, list[str]], default: int = 200) -> int:
    raw = query.get("limit", [str(default)])[0]
    try:
        return max(1, min(int(raw), 1000))
    except ValueError:
        return default


def _format_html(entries: list[dict[str, Any]], limit: int) -> str:
    stats = buffer.stats()
    rows: list[str] = []
    for item in entries:
        rows.append(
            "<tr>"
            f"<td>{html.escape(str(item.get('timestamp', '')))}</td>"
            f"<td>{html.escape(str(item.get('event_type') or item.get('message', '')))}</td>"
            f"<td>{html.escape(str(item.get('client_name') or item.get('tenant_id', '')))}</td>"
            f"<td>{html.escape(str(item.get('model_name', '')))}</td>"
            f"<td>{html.escape(str(item.get('status', '')))}</td>"
            f"<td>{html.escape(str(item.get('latency_ms', '')))}</td>"
            f"<td>{html.escape(str(item.get('cost_usd', '')))}</td>"
            f"<td><code>{html.escape(str(item.get('request_id', '')))}</code></td>"
            "</tr>",
        )

    body_rows = "\n".join(rows) if rows else (
        "<tr><td colspan='8'>No telemetry events buffered yet — wait for the next batch.</td></tr>"
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta http-equiv="refresh" content="5">
  <title>AI Telemetry Logs</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 1.5rem; color: #111; }}
    h1 {{ font-size: 1.25rem; margin-bottom: 0.25rem; }}
    p {{ color: #444; }}
    nav {{ margin: 1rem 0; }}
    nav a {{ margin-right: 1rem; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 0.85rem; }}
    th, td {{ border: 1px solid #ddd; padding: 0.35rem 0.5rem; text-align: left; }}
    th {{ background: #f5f5f5; }}
    code {{ font-size: 0.8rem; }}
  </style>
</head>
<body>
  <h1>AI Telemetry — structured log view</h1>
  <p>Parsed telemetry events for demos. Auto-refreshes every 5s. Showing up to {limit} records
     ({stats['json_buffered']}/{stats['capacity']} JSON lines buffered).</p>
  <nav>
    <a href="/telemetry/logs/raw">Application logs (plain text)</a>
    <a href="/telemetry/logs/json">Structured JSON logs</a>
    <a href="/telemetry/logs?format=json">JSON API</a>
    <a href="/metrics">Prometheus /metrics</a>
  </nav>
  <table>
    <thead>
      <tr>
        <th>Timestamp</th><th>Event</th><th>Client</th><th>Model</th>
        <th>Status</th><th>Latency ms</th><th>Cost USD</th><th>Request ID</th>
      </tr>
    </thead>
    <tbody>
      {body_rows}
    </tbody>
  </table>
</body>
</html>"""


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args: Any) -> None:
        logger.debug("runner http " + fmt, *args)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)
        limit = _parse_limit(query)

        if path == "/metrics":
            body, content_type = _prometheus_payload()
            self._respond(200, body, content_type)
            return

        if path == "/telemetry/logs/raw":
            payload = buffer.plain_lines(limit).encode("utf-8")
            self._respond(200, payload, "text/plain; charset=utf-8")
            return

        if path == "/telemetry/logs/json":
            payload = buffer.raw_lines(limit).encode("utf-8")
            self._respond(200, payload, "text/plain; charset=utf-8")
            return

        if path == "/telemetry/logs":
            accept = self.headers.get("Accept", "")
            if "application/json" in accept or query.get("format") == ["json"]:
                doc = {
                    "count": len(buffer.formatted(limit)),
                    "limit": limit,
                    "entries": buffer.formatted(limit),
                    "stats": buffer.stats(),
                }
                payload = json.dumps(doc, indent=2, default=str).encode("utf-8")
                self._respond(200, payload, "application/json")
                return

            html_page = _format_html(buffer.formatted(limit), limit)
            self._respond(200, html_page.encode("utf-8"), "text/html; charset=utf-8")
            return

        payload = json.dumps({"error": "not found", "path": self.path}).encode("utf-8")
        self._respond(404, payload, "application/json")

    def _respond(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start(port: int) -> ThreadingHTTPServer | None:
    """Start the combined metrics + telemetry log server once."""
    global _server, _started
    if port <= 0:
        logger.info("Runner HTTP server disabled (PROMETHEUS_PORT<=0)")
        return None
    if _started:
        return _server

    try:
        _server = ThreadingHTTPServer(("0.0.0.0", port), _Handler)
    except OSError as exc:
        logger.error("Runner HTTP bind failed on port %d: %s", port, exc)
        return None

    threading.Thread(
        target=_server.serve_forever,
        name="runner-http",
        daemon=True,
    ).start()
    _started = True
    logger.info(
        "Runner HTTP listening on :%d (/metrics, /telemetry/logs, /telemetry/logs/raw, /telemetry/logs/json)",
        port,
    )
    return _server
