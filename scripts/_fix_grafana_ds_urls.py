#!/usr/bin/env python3
"""Point Grafana datasources at docker-compose service names (not localhost)."""
from __future__ import annotations

import base64
import json
import os
import urllib.request

GRAFANA = os.getenv("GRAFANA_URL", "http://localhost:3001").rstrip("/")
AUTH = base64.b64encode(b"admin:admin").decode()
URLS = {
    "Prometheus": os.getenv("PROMETHEUS_URL", "http://prometheus:9090"),
    "Loki": os.getenv("LOKI_URL", "http://loki:3100"),
    "Tempo": os.getenv("TEMPO_URL", "http://tempo:3200"),
}


def _req(method: str, path: str, body: dict | None = None) -> dict | list:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{GRAFANA}{path}", data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Basic {AUTH}")
    with urllib.request.urlopen(req) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else {}


def main() -> None:
    for ds in _req("GET", "/api/datasources"):
        name = ds.get("name", "")
        if name not in URLS:
            continue
        body = dict(ds)
        body["url"] = URLS[name]
        _req("PUT", f"/api/datasources/{ds['id']}", body)
        print(f"  {name} -> {body['url']}")


if __name__ == "__main__":
    main()
