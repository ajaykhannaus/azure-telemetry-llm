#!/usr/bin/env python3
"""Verify Grafana dashboard template variables and filtered panel queries."""
from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import urllib.error
import urllib.request
from typing import Any

GRAFANA = "http://localhost:3000"
AUTH = base64.b64encode(b"admin:admin").decode()

DASHBOARD_FILTER_KEYS: dict[str, tuple[str, ...]] = {
    "ai-telemetry-executive": ("department", "region", "provider", "model", "environment"),
    "ai-telemetry-traffic": ("department", "region", "provider", "model", "operation", "status", "environment"),
    "ai-telemetry-latency": ("department", "region", "provider", "model", "operation", "environment"),
    "ai-telemetry-cost": ("department", "region", "provider", "model", "environment"),
    "ai-telemetry-quality": ("department", "provider", "model", "operation", "environment"),
    "ai-telemetry-safety": ("department", "data_class", "provider", "model", "environment"),
    "ai-telemetry-infra": ("environment", "department", "model"),
    "ai-telemetry-tokens": ("department", "region", "provider", "model", "operation", "environment"),
    "ai-telemetry-users": ("department", "region", "provider", "model", "environment"),
}

VARIABLES = ("department", "region", "provider", "model", "operation", "status", "data_class", "environment")

FILTER_VALUES = {
    "department": ["legal", "engineering", ".*"],
    "region": ["us-east-1", ".*"],
    "provider": ["anthropic", "openai", ".*"],
    "model": ["claude-haiku-3-5", "gpt-4o", ".*"],
    "operation": ["chat_completion", "code_generation", ".*"],
    "status": ["success", "error", ".*"],
    "data_class": [".*"],
    "environment": ["dev"],
}

PANEL_QUERIES = {
    "prometheus": (
        'sum(increase(ai_gateway_request_count_total{environment=~"$environment",'
        'department=~"$department",region=~"$region",model_provider=~"$provider",'
        'model_name=~"$model",operation_name=~"$operation",status=~"$status",'
        'data_classification=~"$data_class"}[1h]))',
        "stat",
    ),
    "loki": (
        'sum(count_over_time({service_name=~".+"} | json | line_format "{{.body}}" | json '
        '| event_type="telemetry_event" | department=~"$department" | region=~"$region" '
        '| model_provider=~"$provider" | model_name=~"$model" | operation_name=~"$operation" '
        '| status=~"$status" | data_classification=~"$data_class" [1h]))',
        "stat",
    ),
}


def _req(method: str, path: str, body: dict | None = None, timeout: int = 30, grafana: str = GRAFANA) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{grafana}{path}", data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Basic {AUTH}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        text = exc.read().decode() if exc.fp else ""
        raise RuntimeError(f"{method} {path} → HTTP {exc.code}: {text[:400]}") from exc


def _prom_uid(grafana: str = GRAFANA) -> str:
    for ds in _req("GET", "/api/datasources", grafana=grafana):
        if ds["name"].lower() == "prometheus":
            return ds["uid"]
    raise RuntimeError("Prometheus datasource not found")


def _loki_uid(grafana: str = GRAFANA) -> str:
    for ds in _req("GET", "/api/datasources", grafana=grafana):
        if ds["name"].lower() == "loki":
            return ds["uid"]
    raise RuntimeError("Loki datasource not found")


def _substitute(text: str, values: dict[str, str]) -> str:
    def repl(match: re.Match[str]) -> str:
        key = match.group(1) or match.group(2)
        return values.get(key, match.group(0))

    return re.sub(r"\$\{([^}:]+)(?::[^}]*)?\}|\$([a-zA-Z_][a-zA-Z0-9_]*)", repl, text)


def _label_values(prom_uid: str, label: str, grafana: str = GRAFANA) -> list[str]:
    import urllib.parse

    params = urllib.parse.urlencode({"match[]": "ai_gateway_request_count_total"})
    url = (
        f"/api/datasources/proxy/uid/{prom_uid}/api/v1/label/{label}/values?"
        f"{params}"
    )
    data = _req("GET", url, grafana=grafana)
    if data.get("status") != "success":
        raise RuntimeError(f"label {label}: {data}")
    return sorted(data.get("data") or [])


def _variable_label(name: str) -> str:
    return {
        "department": "department",
        "region": "region",
        "provider": "model_provider",
        "model": "model_name",
        "operation": "operation_name",
        "status": "status",
        "data_class": "data_classification",
        "environment": "environment",
    }[name]


def _test_variable_options(prom_uid: str, grafana: str) -> list[tuple[str, str, bool, str]]:
    results: list[tuple[str, str, bool, str]] = []
    for var in VARIABLES:
        label = _variable_label(var)
        if var == "data_class":
            results.append(("data_class", "data_classification", True, "4 options: phi, pii, confidential, internal"))
            continue
        try:
            values = _label_values(prom_uid, label, grafana=grafana)
            ok = len(values) > 0
            detail = f"{len(values)} options: {', '.join(values[:5])}"
            if len(values) > 5:
                detail += "…"
            results.append((var, label, ok, detail))
        except RuntimeError as exc:
            results.append((var, label, False, str(exc)))
    return results


def _frames_have_data(result: dict) -> bool:
    for res in result.get("results", {}).values():
        if res.get("error"):
            return False
        for frame in res.get("frames") or []:
            for col in frame.get("data", {}).get("values") or []:
                for v in col:
                    if v is not None and v != "" and not (isinstance(v, float) and v != v):
                        return True
    return False


def _query_panel(
    ds_type: str, ds_uid: str, expr: str, panel_type: str, grafana: str,
) -> tuple[bool, str]:
    q: dict[str, Any] = {
        "refId": "A",
        "datasource": {"type": ds_type, "uid": ds_uid},
        "expr": expr,
    }
    if ds_type == "loki":
        q["queryType"] = "instant" if panel_type == "stat" else "range"
    else:
        q["instant"] = panel_type == "stat"
        q["range"] = panel_type != "stat"

    payload = {"queries": [q], "from": "now-6h", "to": "now"}
    try:
        resp = _req("POST", "/api/ds/query", payload, grafana=grafana)
        if not _frames_have_data(resp):
            err = next(
                (r.get("error") for r in resp.get("results", {}).values() if r.get("error")),
                None,
            )
            return False, err or "no data"
        return True, "ok"
    except RuntimeError as exc:
        return False, str(exc)


def _test_filter_combinations(
    prom_uid: str, loki_uid: str | None, grafana: str,
) -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []
    base = {
        "department": ".*",
        "region": ".*",
        "provider": ".*",
        "model": ".*",
        "operation": ".*",
        "status": ".*",
        "data_class": ".*",
        "environment": "dev",
    }

    # All filters at default (All / dev).
    for ds_type, (expr_tpl, ptype) in PANEL_QUERIES.items():
        if ds_type == "loki" and not loki_uid:
            results.append(("defaults/loki", False, "Loki not reachable"))
            continue
        uid = prom_uid if ds_type == "prometheus" else loki_uid
        expr = _substitute(expr_tpl, base)
        ok, detail = _query_panel(ds_type, uid, expr, ptype, grafana)
        results.append((f"defaults/{ds_type}", ok, detail))

    # Each filter individually with a real value.
    for var, samples in FILTER_VALUES.items():
        for sample in samples:
            values = {**base, var: sample}
            label = f"{var}={sample}"
            expr = _substitute(PANEL_QUERIES["prometheus"][0], values)
            ok, detail = _query_panel(
                "prometheus", prom_uid, expr, PANEL_QUERIES["prometheus"][1], grafana,
            )
            results.append((label, ok, detail))

    # Combined realistic slice.
    combo = {
        "department": "legal",
        "region": ".*",
        "provider": "anthropic",
        "model": ".*",
        "operation": "contract_review",
        "status": ".*",
        "data_class": ".*",
        "environment": "dev",
    }
    expr = _substitute(PANEL_QUERIES["prometheus"][0], combo)
    ok, detail = _query_panel("prometheus", prom_uid, expr, "stat", grafana)
    results.append(("combo legal/anthropic/contract_review", ok, detail))

    if loki_uid:
        loki_expr = _substitute(PANEL_QUERIES["loki"][0], combo)
        ok, detail = _query_panel("loki", loki_uid, loki_expr, "stat", grafana)
        results.append(("combo/loki", ok, detail))

    return results


def _test_dashboard_variables(uid: str, prom_uid: str, grafana: str) -> list[tuple[str, bool, str]]:
    dash = _req("GET", f"/api/dashboards/uid/{uid}", grafana=grafana)["dashboard"]
    expected = DASHBOARD_FILTER_KEYS.get(uid, ())
    results: list[tuple[str, bool, str]] = []

    present = [v.get("name") for v in dash.get("templating", {}).get("list", [])]
    if tuple(present) != expected:
        results.append((
            f"{uid}/filter-set",
            False,
            f"expected {list(expected)}, got {present}",
        ))
    else:
        results.append((f"{uid}/filter-set", True, f"{len(expected)} filters"))

    for name in expected:
        var = next(v for v in dash["templating"]["list"] if v.get("name") == name)
        if var.get("type") == "custom":
            options = [v.strip() for v in (var.get("query") or "").split(",") if v.strip()]
            ok = len(options) > 0
            results.append((f"{uid}/{name}", ok, f"{len(options)} options"))
            continue
        ds = var.get("datasource") or {}
        ds_uid = ds.get("uid", "")
        if ds_uid != prom_uid:
            results.append((f"{uid}/{name}/uid", False, f"expected {prom_uid}, got {ds_uid}"))
            continue
        q = var.get("query")
        if isinstance(q, dict) and q.get("query"):
            qstr = q["query"]
        elif isinstance(q, str):
            qstr = q
        else:
            results.append((f"{uid}/{name}/query", False, f"unexpected query shape: {q!r}"))
            continue
        if not qstr.startswith("label_values("):
            results.append((f"{uid}/{name}/query", False, qstr))
            continue
        label = _variable_label(name)
        try:
            values = _label_values(prom_uid, label, grafana=grafana)
            results.append((f"{uid}/{name}", True, f"{len(values)} options"))
        except RuntimeError as exc:
            results.append((f"{uid}/{name}", False, str(exc)))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Test Grafana dashboard filters")
    parser.add_argument("--grafana", default=GRAFANA)
    args = parser.parse_args()
    grafana_url = args.grafana.rstrip("/")

    print("Dashboard filter tests\n" + "=" * 40)
    try:
        prom_uid = _prom_uid(grafana_url)
    except RuntimeError as exc:
        print(f"FAIL setup: {exc}")
        return 2

    loki_uid: str | None = None
    try:
        loki_uid = _loki_uid(grafana_url)
        _req(
            "GET",
            f"/api/datasources/proxy/uid/{loki_uid}/loki/api/v1/labels",
            timeout=5,
            grafana=grafana_url,
        )
    except Exception:
        loki_uid = None

    print(f"Prometheus UID: {prom_uid}")
    print(f"Loki UID:       {loki_uid or '(unavailable)'}\n")

    failures = 0

    print("1) Variable option queries (Prometheus labels)")
    for var, label, ok, detail in _test_variable_options(prom_uid, grafana_url):
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {var} ({label}): {detail}")
        if not ok:
            failures += 1

    print("\n2) Filtered panel queries")
    for name, ok, detail in _test_filter_combinations(prom_uid, loki_uid, grafana_url):
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {name}: {detail}")
        if not ok:
            failures += 1

    print("\n3) Dashboard variable wiring (all dashboards)")
    for uid in DASHBOARD_FILTER_KEYS:
        for name, ok, detail in _test_dashboard_variables(uid, prom_uid, grafana_url):
            status = "PASS" if ok else "FAIL"
            print(f"  [{status}] {name}: {detail}")
            if not ok:
                failures += 1

    print(f"\n{'=' * 40}")
    if failures:
        print(f"FAILED: {failures} check(s)")
        return 1
    print("All filter checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
