#!/usr/bin/env python3
"""Verify Grafana AI Telemetry dashboards return data for each query panel."""
from __future__ import annotations

import argparse
import base64
import json
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Iterator

GRAFANA = "http://localhost:3000"
AUTH = base64.b64encode(b"admin:admin").decode()

DASHBOARD_UIDS = [
    ("1. Request & Traffic Metrics", "ai-telemetry-executive"),
    ("2. Traffic & Request Analytics", "ai-telemetry-traffic"),
    ("3. Latency & Performance Metrics", "ai-telemetry-latency"),
    ("4. Cost & Usage Metrics", "ai-telemetry-cost"),
    ("5. Model Quality Metrics", "ai-telemetry-quality"),
    ("6. Safety & Security Metrics", "ai-telemetry-safety"),
    ("7. Infrastructure Metrics", "ai-telemetry-infra"),
    ("8. Token & Context Metrics", "ai-telemetry-tokens"),
    ("9. User-Level Observability", "ai-telemetry-users"),
    ("Legacy POC", "ai-telemetry-001"),
]

SKIP_PANEL_TYPES = frozenset({"row", "text", "alertlist", "logs", "traces"})
# Panels that need real K8s/node exporters — warn instead of fail unless --strict
OPTIONAL_EMPTY_PATTERNS = [
    re.compile(r"\bnode_", re.I),
    re.compile(r"\bkube_node_", re.I),
    re.compile(r"\bkubelet_", re.I),
    re.compile(r"ContainerAppConsoleLogs_CL"),
    re.compile(r"grafana-azure-monitor"),
]

VAR_DEFAULTS = {
    "environment": "dev",
    "tenant": ".*",
    "model": ".*",
    "DS_PROMETHEUS": None,  # resolved from datasource list
    "DS_LOKI": None,
    "DS_TEMPO": None,
    "datasource": None,
}


@dataclass
class PanelResult:
    dashboard: str
    panel_title: str
    panel_type: str
    status: str  # PASS, NO_DATA, ERROR, SKIP, WARN
    detail: str = ""
    expr: str = ""


@dataclass
class RunSummary:
    results: list[PanelResult] = field(default_factory=list)

    @property
    def failures(self) -> list[PanelResult]:
        return [r for r in self.results if r.status in ("NO_DATA", "ERROR")]

    @property
    def warnings(self) -> list[PanelResult]:
        return [r for r in self.results if r.status == "WARN"]


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
        body_text = exc.read().decode() if exc.fp else ""
        raise RuntimeError(f"{method} {path} → HTTP {exc.code}: {body_text[:500]}") from exc


def _resolve_datasource_uids_for(grafana: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for ds in _req("GET", "/api/datasources", grafana=grafana):
        name = ds["name"].lower()
        if name == "prometheus":
            mapping["DS_PROMETHEUS"] = ds["uid"]
            mapping["datasource"] = ds["uid"]
        elif name == "loki":
            mapping["DS_LOKI"] = ds["uid"]
        elif name == "tempo":
            mapping["DS_TEMPO"] = ds["uid"]
    return mapping


def _substitute_vars(text: str, ds_uids: dict[str, str]) -> str:
    defaults = {**VAR_DEFAULTS, **ds_uids}

    def repl(match: re.Match[str]) -> str:
        key = match.group(1) or match.group(2)
        val = defaults.get(key)
        if val is None and key in defaults:
            return match.group(0)
        return str(val) if val is not None else match.group(0)

    text = re.sub(r"\$\{([^}:]+)(?::[^}]*)?\}|\$([a-zA-Z_][a-zA-Z0-9_]*)", repl, text)
    return text


def _iter_panels(panels: list[dict], path: str = "") -> Iterator[tuple[str, dict]]:
    for panel in panels:
        if not isinstance(panel, dict):
            continue
        title = panel.get("title") or panel.get("type", "untitled")
        loc = f"{path}/{title}" if path else title
        ptype = panel.get("type", "")
        if ptype == "row":
            yield from _iter_panels(panel.get("panels", []), loc)
        else:
            yield loc, panel


def _resolve_panel_datasource(panel: dict, target: dict, ds_uids: dict[str, str]) -> dict | None:
    ds = target.get("datasource") or panel.get("datasource")
    if isinstance(ds, str):
        uid = _substitute_vars(ds, ds_uids)
        return {"type": "prometheus", "uid": uid}
    if isinstance(ds, dict):
        ds_type = ds.get("type", "prometheus")
        uid = _substitute_vars(str(ds.get("uid", "")), ds_uids)
        if not uid or uid.startswith("$"):
            # fall back by type
            if ds_type == "loki":
                uid = ds_uids.get("DS_LOKI", uid)
            elif ds_type == "tempo":
                uid = ds_uids.get("DS_TEMPO", uid)
            else:
                uid = ds_uids.get("DS_PROMETHEUS", uid)
        return {"type": ds_type, "uid": uid}
    return None


def _build_query(target: dict, panel: dict, ds_uids: dict[str, str]) -> dict | None:
    ds_ref = _resolve_panel_datasource(panel, target, ds_uids)
    if not ds_ref or not ds_ref.get("uid"):
        return None

    ds_type = ds_ref["type"]
    ref_id = target.get("refId", "A")

    if ds_type == "prometheus":
        expr = target.get("expr") or target.get("query")
        if not expr:
            return None
        expr = _substitute_vars(expr, ds_uids)
        q: dict[str, Any] = {
            "refId": ref_id,
            "datasource": ds_ref,
            "expr": expr,
        }
        if target.get("instant") or panel.get("type") in ("stat", "gauge", "barchart", "piechart", "bargauge") and not target.get("range"):
            q["instant"] = True
            q["range"] = False
        else:
            q["range"] = True
            q["instant"] = False
        if target.get("legendFormat"):
            q["legendFormat"] = target["legendFormat"]
        return q

    if ds_type == "loki":
        expr = target.get("expr") or target.get("query")
        if not expr:
            return None
        expr = _substitute_vars(expr, ds_uids)
        q = {
            "refId": ref_id,
            "datasource": ds_ref,
            "expr": expr,
        }
        ptype = panel.get("type", "")
        if target.get("queryType") == "instant" or ptype in ("stat", "gauge", "bargauge", "piechart"):
            q["queryType"] = "instant"
        else:
            q["queryType"] = "range"
        return q

    if ds_type == "tempo":
        query = target.get("query") or target.get("expr")
        if not query:
            return None
        return {
            "refId": ref_id,
            "datasource": ds_ref,
            "query": _substitute_vars(str(query), ds_uids),
            "queryType": target.get("queryType", "traceql"),
        }

    return None


def _frames_have_data(result: dict) -> bool:
    for res in result.get("results", {}).values():
        for frame in res.get("frames") or []:
            data = frame.get("data", {})
            values = data.get("values") or []
            for col in values:
                if not col:
                    continue
                for v in col:
                    if v is not None and v != "" and v != "NaN":
                        if isinstance(v, float) and v != v:  # NaN
                            continue
                        return True
            # logs-style frames
            fields = data.get("fields") or frame.get("fields") or []
            for fld in fields:
                for v in fld.get("values") or []:
                    if v is not None and v != "":
                        return True
    return False


def _is_optional_panel(expr: str) -> bool:
    return any(p.search(expr) for p in OPTIONAL_EMPTY_PATTERNS)


def _check_panel(
    dashboard: str,
    panel: dict,
    panel_path: str,
    ds_uids: dict[str, str],
    strict: bool,
    lookback: str,
    grafana: str,
) -> list[PanelResult]:
    ptype = panel.get("type", "")
    title = panel.get("title") or panel_path

    if ptype in SKIP_PANEL_TYPES:
        return [PanelResult(dashboard, title, ptype, "SKIP", "panel type not query-tested")]

    targets = panel.get("targets") or []
    if not targets:
        return [PanelResult(dashboard, title, ptype, "SKIP", "no targets")]

    out: list[PanelResult] = []
    for target in targets:
        if not isinstance(target, dict):
            continue
        if target.get("hide"):
            continue
        q = _build_query(target, panel, ds_uids)
        if not q:
            continue
        expr = q.get("expr") or q.get("query") or ""
        payload = {
            "queries": [q],
            "from": lookback,
            "to": "now",
        }
        try:
            resp = _req("POST", "/api/ds/query", payload, grafana=grafana)
            if _frames_have_data(resp):
                out.append(PanelResult(dashboard, title, ptype, "PASS", expr=expr[:120]))
            elif _is_optional_panel(expr) and not strict:
                out.append(PanelResult(dashboard, title, ptype, "WARN", "optional / no local data", expr[:120]))
            else:
                out.append(PanelResult(dashboard, title, ptype, "NO_DATA", expr=expr[:120]))
        except RuntimeError as exc:
            if _is_optional_panel(expr) and not strict:
                out.append(PanelResult(dashboard, title, ptype, "WARN", str(exc)[:200], expr[:120]))
            else:
                out.append(PanelResult(dashboard, title, ptype, "ERROR", str(exc)[:200], expr[:120]))

    if not out:
        out.append(PanelResult(dashboard, title, ptype, "SKIP", "no runnable targets"))
    return out


def verify_dashboard(
    name: str,
    uid: str,
    ds_uids: dict[str, str],
    strict: bool,
    lookback: str,
    grafana: str,
) -> list[PanelResult]:
    dash = _req("GET", f"/api/dashboards/uid/{uid}", grafana=grafana)
    panels = dash.get("dashboard", {}).get("panels", [])
    results: list[PanelResult] = []
    for path, panel in _iter_panels(panels):
        results.extend(_check_panel(name, panel, path, ds_uids, strict, lookback, grafana))
    return results


def _print_report(summary: RunSummary) -> None:
    by_dash: dict[str, list[PanelResult]] = {}
    for r in summary.results:
        by_dash.setdefault(r.dashboard, []).append(r)

    for dash, items in by_dash.items():
        print(f"\n=== {dash} ===")
        for r in items:
            if r.status == "PASS":
                continue
            line = f"  [{r.status:7}] {r.panel_title} ({r.panel_type})"
            if r.detail:
                line += f" — {r.detail}"
            if r.expr:
                line += f"\n           expr: {r.expr}"
            print(line)

    passed = sum(1 for r in summary.results if r.status == "PASS")
    skipped = sum(1 for r in summary.results if r.status == "SKIP")
    warned = len(summary.warnings)
    failed = len(summary.failures)
    total = len(summary.results)
    print(f"\n--- Summary: {passed} pass, {failed} fail, {warned} warn, {skipped} skip / {total} panels ---")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Grafana dashboard panels return data.")
    parser.add_argument("--grafana", default=GRAFANA, help="Grafana base URL")
    parser.add_argument("--strict", action="store_true", help="Treat optional/infra empty panels as failures")
    parser.add_argument("--lookback", default="now-6h", help="Query time range start (default: now-6h)")
    parser.add_argument("--uid", action="append", help="Limit to dashboard UID (repeatable)")
    args = parser.parse_args()

    grafana_url = args.grafana.rstrip("/")

    try:
        ds_uids = _resolve_datasource_uids_for(grafana_url)
    except RuntimeError as exc:
        print(f"ERROR: cannot reach Grafana or list datasources: {exc}", file=sys.stderr)
        return 2

    if "DS_PROMETHEUS" not in ds_uids:
        print("ERROR: Prometheus datasource not found in Grafana", file=sys.stderr)
        return 2

    dashboards = DASHBOARD_UIDS
    if args.uid:
        wanted = set(args.uid)
        dashboards = [(n, u) for n, u in DASHBOARD_UIDS if u in wanted]

    summary = RunSummary()
    for name, uid in dashboards:
        try:
            summary.results.extend(
                verify_dashboard(name, uid, ds_uids, args.strict, args.lookback, grafana_url)
            )
        except RuntimeError as exc:
            print(f"ERROR loading dashboard {name} ({uid}): {exc}", file=sys.stderr)
            summary.results.append(PanelResult(name, "(dashboard)", "", "ERROR", str(exc)))

    _print_report(summary)

    if summary.failures:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
