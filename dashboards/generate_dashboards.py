"""Grafana dashboard generator — produces 9 dashboard JSON files.

Run:
    python3 dashboards/generate_dashboards.py

Outputs:
    dashboards/01-executive-overview.json
    dashboards/02-traffic-analytics.json
    dashboards/03-latency-performance.json
    dashboards/04-token-cost.json
    dashboards/05-model-quality.json
    dashboards/06-safety-pii.json
    dashboards/07-infra-runner.json
    dashboards/08-token-context.json
    dashboards/09-user-observability.json
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
if OUT_DIR not in sys.path:
    sys.path.insert(0, OUT_DIR)

from metric_definitions import METRIC_DEFINITIONS  # noqa: E402

# ---------------------------------------------------------------------------
# Datasource references (match dashboards/provisioning/datasources.yaml UIDs)
# ---------------------------------------------------------------------------
PROM_UID = "prometheus-ds"
LOKI_UID = "loki-ds"
TEMPO_UID = "tempo-ds"

DS_PROMETHEUS = {"type": "prometheus", "uid": PROM_UID}
DS_LOKI       = {"type": "loki",       "uid": LOKI_UID}
DS_TEMPO      = {"type": "tempo",      "uid": TEMPO_UID}

# OTel Collector stores OTLP log records with JSON payload in a `body` field.
_LOKI_STREAM = '{service_name=~".+"} | json | line_format "{{.body}}" | json |'


def _loki_ratio(numerator: str, denominator: str, scale: float = 100) -> str:
    """LogQL-safe ratio — clamp_min is Prometheus-only and breaks Loki panels."""
    return f"({numerator} / ({denominator} or on() vector(1))) * {scale}"

# ---------------------------------------------------------------------------
# Common template variables (shared by every dashboard)
# ---------------------------------------------------------------------------

def _ds_var(name: str, ds_type: str, label: str, uid: str) -> dict:
    return {
        "type": "datasource", "name": name, "label": label,
        "pluginId": ds_type, "multi": False, "includeAll": False,
        "hide": 2, "refresh": 1,
        "current": {"selected": True, "text": label, "value": uid},
    }

def _query_var(name: str, label: str, datasource: dict, query: str,
               multi: bool = True, include_all: bool = True,
               current: dict | None = None) -> dict:
    return {
        "type": "query", "name": name, "label": label,
        "datasource": datasource,
        "query": query,
        "multi": multi, "includeAll": include_all,
        "allValue": ".*", "hide": 0, "refresh": 2,
        "current": current or {},
        "sort": 1,
    }

COMMON_VARS: list[dict] = [
    _query_var(
        "tenant", "Tenant",
        DS_PROMETHEUS,
        'label_values(ai_gateway_request_count_total, tenant_id)',
        multi=True, include_all=True,
        current={"selected": True, "text": "All", "value": ".*"},
    ),
    _query_var(
        "model", "Model",
        DS_PROMETHEUS,
        'label_values(ai_gateway_request_count_total, model_name)',
        multi=True, include_all=True,
        current={"selected": True, "text": "All", "value": ".*"},
    ),
    _query_var(
        "environment", "Environment",
        DS_PROMETHEUS,
        'label_values(ai_gateway_request_count_total, environment)',
        multi=False, include_all=False,
        current={"selected": True, "text": "dev", "value": "dev"},
    ),
]

# ---------------------------------------------------------------------------
# Panel builders
# ---------------------------------------------------------------------------

_id_counter = 0

def _next_id() -> int:
    global _id_counter
    _id_counter += 1
    return _id_counter


def _grid(x: int, y: int, w: int, h: int) -> dict:
    return {"x": x, "y": y, "w": w, "h": h}


def _panel_description(title: str, description: str | None = None) -> str | None:
    """Resolve panel description for Grafana ⓘ tooltip (metric_definitions or override)."""
    if description is not None:
        return description
    return METRIC_DEFINITIONS.get(title)


def _with_description(panel: dict, title: str, description: str | None = None) -> dict:
    desc = _panel_description(title, description)
    if desc:
        panel["description"] = desc
    return panel


def stat_panel(
    title: str,
    expr: str,
    unit: str = "short",
    color_mode: str = "background",
    thresholds: list[dict] | None = None,
    grid: dict | None = None,
    datasource: dict | None = None,
    mappings: list | None = None,
    decimals: int = 2,
    description: str | None = None,
) -> dict:
    ds = datasource or DS_PROMETHEUS
    th = thresholds or [
        {"color": "green",  "value": None},
        {"color": "yellow", "value": 80},
        {"color": "red",    "value": 95},
    ]
    return _with_description({
        "id": _next_id(), "type": "stat", "title": title,
        "datasource": ds,
        "fieldConfig": {
            "defaults": {
                "unit": unit, "decimals": decimals,
                # Grafana 11: field color mode must be thresholds/shades/etc — not "background".
                "color": {"mode": "thresholds"},
                "thresholds": {"mode": "absolute", "steps": th},
                "mappings": mappings or [],
            },
            "overrides": [],
        },
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"]},
            "colorMode": color_mode, "graphMode": "area",
            "justifyMode": "center", "textMode": "auto",
        },
        "gridPos": grid or _grid(0, 0, 4, 3),
        "targets": [_loki_stat_target(expr, ref="A") if ds == DS_LOKI
                    else _prom_stat_target(expr)],
    }, title, description)


def timeseries_panel(
    title: str,
    targets: list[dict],
    unit: str = "short",
    grid: dict | None = None,
    datasource: dict | None = None,
    stacking: str = "none",
    fill_opacity: int = 5,
    legend_placement: str = "bottom",
    axis_soft_max: float | None = None,
    decimals: int | None = None,
    description: str | None = None,
) -> dict:
    ds = datasource or DS_PROMETHEUS
    custom: dict[str, Any] = {
        "lineWidth": 1, "fillOpacity": fill_opacity,
        "gradientMode": "none",
        "stacking": {"mode": stacking},
        "showPoints": "never",
    }
    if axis_soft_max is not None:
        custom["axisSoftMax"] = axis_soft_max
    defaults: dict[str, Any] = {"unit": unit, "custom": custom}
    if decimals is not None:
        defaults["decimals"] = decimals
    return _with_description({
        "id": _next_id(), "type": "timeseries", "title": title,
        "datasource": ds,
        "fieldConfig": {
            "defaults": defaults,
            "overrides": [],
        },
        "options": {
            "legend": {"displayMode": "list", "placement": legend_placement, "showLegend": True},
            "tooltip": {"mode": "multi", "sort": "desc"},
        },
        "gridPos": grid or _grid(0, 0, 12, 8),
        "targets": targets,
    }, title, description)


def _prom_targets(*specs: tuple[str, str]) -> list[dict]:
    """Build Prometheus targets with unique refIds (A, B, C, …)."""
    refs = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return [_prom_target(expr, legend, refs[i]) for i, (expr, legend) in enumerate(specs)]


def _prom_stat_target(expr: str, ref: str = "A") -> dict:
    """Prometheus stat/gauge targets — range queries; instant rate/recording rules often return empty."""
    return {
        "datasource": DS_PROMETHEUS, "expr": expr,
        "refId": ref, "range": True, "instant": False,
    }


def _prom_target(expr: str, legend: str, ref: str = "A") -> dict:
    return {
        "datasource": DS_PROMETHEUS, "expr": expr,
        "legendFormat": legend, "refId": ref,
        "format": "time_series", "range": True,
    }


def _loki_targets(*specs: tuple[str, str]) -> list[dict]:
    """Build Loki range targets with unique refIds (A, B, C, …)."""
    refs = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return [_loki_target(expr, legend, refs[i]) for i, (expr, legend) in enumerate(specs)]


def _loki_target(expr: str, legend: str = "", ref: str = "A") -> dict:
    return {
        "datasource": DS_LOKI, "expr": expr,
        "legendFormat": legend, "refId": ref,
        "queryType": "range",
    }


def _loki_instant_target(expr: str, legend: str = "", ref: str = "A") -> dict:
    """Loki metric queries used by bar/pie panels need explicit instant queryType."""
    return {
        "datasource": DS_LOKI, "expr": expr,
        "legendFormat": legend, "refId": ref,
        "instant": True, "queryType": "instant",
    }


def _loki_stat_target(expr: str, ref: str = "A") -> dict:
    """Loki stat panels — range metric queries; instant often returns empty."""
    return {
        "datasource": DS_LOKI, "expr": expr,
        "refId": ref, "queryType": "range",
        "instant": False, "range": True,
    }


def gauge_panel(
    title: str, expr: str, unit: str = "percent",
    min_val: float = 0, max_val: float = 100,
    thresholds: list[dict] | None = None,
    grid: dict | None = None,
    description: str | None = None,
) -> dict:
    th = thresholds or [
        {"color": "red",    "value": None},
        {"color": "yellow", "value": 25},
        {"color": "green",  "value": 50},
    ]
    return _with_description({
        "id": _next_id(), "type": "gauge", "title": title,
        "datasource": DS_PROMETHEUS,
        "fieldConfig": {
            "defaults": {
                "unit": unit, "min": min_val, "max": max_val,
                "color": {"mode": "thresholds"},
                "thresholds": {"mode": "absolute", "steps": th},
            },
            "overrides": [],
        },
        "options": {"reduceOptions": {"calcs": ["lastNotNull"]}, "showThresholdLabels": True},
        "gridPos": grid or _grid(0, 0, 6, 6),
        "targets": [_prom_stat_target(expr)],
    }, title, description)


def barchart_panel(
    title: str, targets: list[dict], unit: str = "short",
    grid: dict | None = None, datasource: dict | None = None,
    orientation: str = "auto",
    description: str | None = None,
) -> dict:
    ds = datasource or DS_PROMETHEUS
    return _with_description({
        "id": _next_id(), "type": "barchart", "title": title,
        "datasource": ds,
        "fieldConfig": {"defaults": {"unit": unit}, "overrides": []},
        "options": {
            "orientation": orientation,
            "xTickLabelRotation": -45,
            "barRadius": 0.03,
            "groupWidth": 0.7,
            "barWidth": 0.97,
            "stacking": "none",
            "legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
        },
        "gridPos": grid or _grid(0, 0, 12, 8),
        "targets": targets,
    }, title, description)


def piechart_panel(
    title: str, targets: list[dict],
    grid: dict | None = None, datasource: dict | None = None,
    description: str | None = None,
) -> dict:
    ds = datasource or DS_PROMETHEUS
    return _with_description({
        "id": _next_id(), "type": "piechart", "title": title,
        "datasource": ds,
        "fieldConfig": {"defaults": {"unit": "short"}, "overrides": []},
        "options": {
            "pieType": "pie",
            "legend": {"displayMode": "table", "placement": "right", "showLegend": True,
                       "values": ["value", "percent"]},
            "tooltip": {"mode": "single"},
        },
        "gridPos": grid or _grid(0, 0, 8, 8),
        "targets": targets,
    }, title, description)


def bargauge_panel(
    title: str, expr: str, unit: str = "percent",
    grid: dict | None = None,
    thresholds: list[dict] | None = None,
    datasource: dict | None = None,
    description: str | None = None,
) -> dict:
    ds = datasource or DS_PROMETHEUS
    th = thresholds or [
        {"color": "green",  "value": None},
        {"color": "yellow", "value": 75},
        {"color": "red",    "value": 90},
    ]
    return _with_description({
        "id": _next_id(), "type": "bargauge", "title": title,
        "datasource": ds,
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "color": {"mode": "thresholds"},
                "thresholds": {"mode": "absolute", "steps": th},
            },
            "overrides": [],
        },
        "options": {
            "orientation": "horizontal",
            "reduceOptions": {"calcs": ["lastNotNull"]},
            "displayMode": "lcd",
            "showUnfilled": True,
        },
        "gridPos": grid or _grid(0, 0, 12, 6),
        "targets": [{"datasource": ds, "expr": expr, "instant": True,
                     "legendFormat": "{{tenant_id}}", "refId": "A"}],
    }, title, description)


def heatmap_panel(
    title: str, expr: str, unit: str = "ms",
    grid: dict | None = None,
    description: str | None = None,
) -> dict:
    return _with_description({
        "id": _next_id(), "type": "heatmap", "title": title,
        "datasource": DS_PROMETHEUS,
        "fieldConfig": {"defaults": {"unit": unit}, "overrides": []},
        "options": {
            "calculate": False,
            "yAxis": {"unit": unit},
            "color": {"scheme": "Oranges", "mode": "scheme"},
            "tooltip": {"mode": "single"},
        },
        "gridPos": grid or _grid(0, 0, 12, 8),
        "targets": [{"datasource": DS_PROMETHEUS, "expr": expr,
                     "format": "heatmap", "legendFormat": "{{le}}", "refId": "A"}],
    }, title, description)


def table_panel(
    title: str, targets: list[dict],
    grid: dict | None = None,
    datasource: dict | None = None,
    description: str | None = None,
) -> dict:
    ds = datasource or DS_LOKI
    return _with_description({
        "id": _next_id(), "type": "table", "title": title,
        "datasource": ds,
        "fieldConfig": {"defaults": {"unit": "short"}, "overrides": []},
        "options": {
            "sortBy": [{"displayName": "Time", "desc": True}],
            "footer": {"show": False},
        },
        "gridPos": grid or _grid(0, 0, 24, 8),
        "targets": targets,
        "transformations": [
            {"id": "merge", "options": {}},
            {"id": "organize", "options": {"excludeByName": {"__name__": True}}},
        ],
    }, title, description)


def logs_panel(
    title: str, expr: str,
    grid: dict | None = None,
    datasource: dict | None = None,
    description: str | None = None,
) -> dict:
    ds = datasource or DS_LOKI
    return _with_description({
        "id": _next_id(), "type": "logs", "title": title,
        "datasource": ds,
        "options": {
            "dedupStrategy": "none",
            "enableLogDetails": True,
            "prettifyLogMessage": True,
            "showTime": True,
            "sortOrder": "Descending",
            "wrapLogMessage": False,
        },
        "gridPos": grid or _grid(0, 0, 24, 10),
        "targets": [{
            "datasource": ds,
            "expr": expr,
            "refId": "A",
            "queryType": "range",
            "maxLines": 500,
            "legendFormat": "",
        }],
    }, title, description)


def alertlist_panel(
    title: str, grid: dict | None = None, description: str | None = None,
) -> dict:
    return _with_description({
        "id": _next_id(), "type": "alertlist", "title": title,
        "options": {
            "alertInstanceLabelFilter": "",
            "alertName": "",
            "dashboardAlerts": False,
            "groupMode": "default",
            "maxItems": 20,
            "sortOrder": 1,
            "stateFilter": {
                "error": True, "firing": True, "noData": False,
                "normal": False, "pending": True,
            },
        },
        "gridPos": grid or _grid(0, 0, 12, 8),
        "targets": [],
    }, title, description)


def row_panel(title: str, y: int, collapsed: bool = False) -> dict:
    return {
        "id": _next_id(), "type": "row", "title": title,
        "collapsed": collapsed, "gridPos": {"x": 0, "y": y, "w": 24, "h": 1},
        "panels": [],
    }


def text_panel(
    title: str,
    content: str,
    grid: dict | None = None,
    mode: str = "markdown",
    transparent: bool = False,
    description: str | None = None,
) -> dict:
    panel: dict[str, Any] = {
        "id": _next_id(), "type": "text", "title": title,
        "options": {"content": content, "mode": mode},
        "gridPos": grid or _grid(0, 0, 24, 2),
        "targets": [],
    }
    if transparent:
        panel["transparent"] = True
    return _with_description(panel, title, description)


# ---------------------------------------------------------------------------
# Cross-dashboard navigation (visible button bar + compact header dropdown)
# ---------------------------------------------------------------------------

NAV_BAR_HEIGHT = 3

DASHBOARDS_NAV: list[tuple[str, str, str]] = [
    ("1", "Request & Traffic", "ai-telemetry-executive"),
    ("2", "Traffic Analytics", "ai-telemetry-traffic"),
    ("3", "Latency", "ai-telemetry-latency"),
    ("4", "Cost & Usage", "ai-telemetry-cost"),
    ("5", "Model Quality", "ai-telemetry-quality"),
    ("6", "Safety & Security", "ai-telemetry-safety"),
    ("7", "Infrastructure", "ai-telemetry-infra"),
    ("8", "Token & Context", "ai-telemetry-tokens"),
    ("9", "User Observability", "ai-telemetry-users"),
]


def _shift_panels_y(panels: list[dict], delta: int) -> list[dict]:
    shifted: list[dict] = []
    for panel in panels:
        p = dict(panel)
        gp = dict(panel["gridPos"])
        gp["y"] = gp["y"] + delta
        p["gridPos"] = gp
        shifted.append(p)
    return shifted


def nav_bar_panel(current_uid: str) -> dict:
    """HTML button row — primary navigation; current dashboard highlighted."""
    buttons: list[str] = []
    for num, label, uid in DASHBOARDS_NAV:
        active = uid == current_uid
        if active:
            style = (
                "background:#1d4ed8;color:#fff;border:2px solid #1e40af;"
                "box-shadow:0 1px 3px rgba(30,64,175,.35);"
            )
        else:
            style = (
                "background:#eff6ff;color:#1e3a8a;border:1px solid #93c5fd;"
            )
        buttons.append(
            f'<a href="/d/{uid}" style="display:inline-flex;align-items:center;'
            f"padding:9px 14px;margin:0;border-radius:8px;font-size:13px;"
            f"font-weight:600;text-decoration:none;white-space:nowrap;"
            f'letter-spacing:.01em;{style}">{num}. {label}</a>'
        )
    content = (
        '<div style="display:flex;flex-wrap:wrap;gap:8px;align-items:center;'
        'justify-content:flex-start;width:100%;padding:6px 2px 2px;">'
        + "".join(buttons)
        + "</div>"
    )
    return text_panel(
        "",
        content,
        grid=_grid(0, 0, 24, NAV_BAR_HEIGHT),
        mode="html",
        transparent=True,
    )


def _prepend_nav(uid: str, panels: list[dict]) -> list[dict]:
    return [nav_bar_panel(uid)] + _shift_panels_y(panels, NAV_BAR_HEIGHT)


def _dashboard_nav_links() -> list[dict]:
    """Single header dropdown — avoids one link per dashboard wrapping in the toolbar."""
    return [
        {
            "asDropdown": True,
            "icon": "apps",
            "includeVars": True,
            "keepTime": True,
            "tags": ["ai-telemetry"],
            "title": "All dashboards",
            "tooltip": "Jump to any AI Telemetry dashboard",
            "type": "dashboards",
            "targetBlank": False,
        },
    ]


# ---------------------------------------------------------------------------
# Dashboard skeleton
# ---------------------------------------------------------------------------

def dashboard(
    uid: str, title: str, description: str, tags: list[str],
    panels: list[dict],
    refresh: str = "30s",
) -> dict:
    global _id_counter
    _id_counter = 0   # reset per dashboard so IDs start at 1
    panels = _prepend_nav(uid, panels)
    for i, p in enumerate(panels, 1):
        p["id"] = i
    return {
        "uid": uid,
        "title": title,
        "description": description,
        "tags": tags,
        "schemaVersion": 39,
        "version": 1,
        "style": "light",
        "refresh": refresh,
        "time": {"from": "now-6h", "to": "now"},
        "timepicker": {},
        "timezone": "browser",
        "editable": True,
        "graphTooltip": 1,
        "templating": {"list": COMMON_VARS},
        "annotations": {"list": []},
        "panels": panels,
        "links": _dashboard_nav_links(),
    }


def _save(name: str, d: dict) -> None:
    path = os.path.join(OUT_DIR, name)
    with open(path, "w") as f:
        json.dump(d, f, indent=2)
    print(f"  wrote {name}  ({len(d['panels'])} panels)")


# ===========================================================================
# D A S H B O A R D   1 — Request & Traffic Metrics
# ===========================================================================

def build_d1() -> dict:
    global _id_counter; _id_counter = 0

    _f = '{environment=~"$environment",tenant_id=~"$tenant",model_name=~"$model"}'
    _tele = (
        f'{_LOKI_STREAM} event_type="telemetry_event" '
        '| tenant_id=~"$tenant" | model_name=~"$model"'
    )

    panels = [
        stat_panel(
            "Total requests",
            f'sum(increase(ai_gateway_request_count_total{_f}[6h]))',
            unit="short", decimals=0,
            thresholds=[{"color": "blue", "value": None}],
            grid=_grid(0, 0, 8, 4),
        ),
        stat_panel(
            "RPM",
            f'sum(rate(ai_gateway_request_count_total{_f}[1m])) * 60',
            unit="r/min", decimals=1,
            thresholds=[{"color": "blue", "value": None}],
            grid=_grid(8, 0, 16, 4),
        ),

        timeseries_panel(
            "RPM By Model",
            [_prom_target(
                f'sum by (model_name) (rate(ai_gateway_request_count_total{_f}[2m])) * 60',
                "{{model_name}}", "A",
            )],
            unit="r/min", grid=_grid(0, 4, 24, 8),
        ),

        timeseries_panel(
            "Active users/sessions",
            [
                _loki_target(
                    f'count(sum by (user_id) (count_over_time({_tele} [5m])))',
                    "Active users", "A",
                ),
                _loki_target(
                    f'count(sum by (session_id) (count_over_time({_tele} [5m])))',
                    "Active sessions", "B",
                ),
            ],
            unit="short", grid=_grid(0, 12, 12, 8),
            datasource=DS_LOKI,
        ),
        timeseries_panel(
            "Error Rate By Model",
            [_prom_target(
                f'sum by (model_name) (rate(ai_gateway_exception_count_total{_f}[5m])) '
                f'/ clamp_min(sum by (model_name) (rate(ai_gateway_request_count_total{_f}[5m])), 1e-9) * 100',
                "{{model_name}}", "A",
            )],
            unit="percent", grid=_grid(12, 12, 12, 8),
        ),

        piechart_panel(
            "Model Provider Distribution",
            [{"datasource": DS_PROMETHEUS,
              "expr": f'sort_desc(sum by (model_provider) (increase(ai_gateway_request_count_total{_f}[1h])))',
              "legendFormat": "{{model_provider}}", "refId": "A", "instant": True}],
            grid=_grid(0, 20, 12, 8),
        ),
        piechart_panel(
            "Model Distribution (last 1h)",
            [{"datasource": DS_PROMETHEUS,
              "expr": f'sort_desc(sum by (model_name) (increase(ai_gateway_request_count_total{_f}[1h])))',
              "legendFormat": "{{model_name}}", "refId": "A", "instant": True}],
            grid=_grid(12, 20, 12, 8),
        ),
    ]

    return dashboard(
        uid="ai-telemetry-executive",
        title="1. Request & Traffic Metrics",
        description="Request volume, RPM, active users/sessions, model mix, and error rates.",
        tags=["ai-telemetry", "traffic", "requests"],
        panels=panels,
    )


# ===========================================================================
# D A S H B O A R D   2 — Traffic & Request Analytics
# ===========================================================================

def build_d2() -> dict:
    global _id_counter; _id_counter = 0

    panels = [
        row_panel("Traffic Volume", y=0),
        timeseries_panel(
            "Requests / min by Model",
            [_prom_target('sum by (model_name) (rate(ai_gateway_request_count_total{tenant_id=~"$tenant"}[2m])) * 60', "{{model_name}}")],
            unit="r/min", grid=_grid(0, 1, 12, 8),
        ),
        timeseries_panel(
            "Requests / min by Tenant",
            [_prom_target('sum by (tenant_id) (rate(ai_gateway_request_count_total[2m])) * 60', "{{tenant_id}}")],
            unit="r/min", grid=_grid(12, 1, 12, 8),
        ),
        timeseries_panel(
            "Requests / min by Operation",
            [_prom_target('sum by (operation_name) (rate(ai_gateway_request_count_total{tenant_id=~"$tenant"}[2m])) * 60', "{{operation_name}}")],
            unit="r/min", grid=_grid(0, 9, 12, 8),
        ),
        piechart_panel(
            "Model Distribution (last 1h)",
            [{"datasource": DS_PROMETHEUS, "expr": 'sort_desc(sum by (model_name) (increase(ai_gateway_request_count_total[1h])))', "legendFormat": "{{model_name}}", "refId": "A", "instant": True}],
            grid=_grid(12, 9, 6, 8),
        ),
        piechart_panel(
            "Model Provider Distribution",
            [{"datasource": DS_PROMETHEUS, "expr": 'sort_desc(sum by (model_provider) (increase(ai_gateway_request_count_total[1h])))', "legendFormat": "{{model_provider}}", "refId": "A", "instant": True}],
            grid=_grid(18, 9, 6, 8),
        ),

        row_panel("Errors & Retries", y=17),
        timeseries_panel(
            "Error Rate by Type",
            [_prom_target('sum by (error_type) (rate(ai_gateway_exception_count_total{tenant_id=~"$tenant"}[5m]))', "{{error_type}}")],
            unit="reqps", grid=_grid(0, 18, 12, 8),
        ),
        barchart_panel(
            "Errors by HTTP Status Code (last 1h)",
            [{"datasource": DS_PROMETHEUS, "expr": 'sort_desc(sum by (http_status) (increase(ai_gateway_exception_count_total{tenant_id=~"$tenant"}[1h])))', "legendFormat": "{{http_status}}", "refId": "A", "instant": True}],
            unit="short", grid=_grid(12, 18, 8, 8),
        ),
        piechart_panel(
            "Error Category Mix",
            [{"datasource": DS_PROMETHEUS, "expr": 'sort_desc(sum by (error_category) (increase(ai_gateway_exception_count_total{tenant_id=~"$tenant"}[1h])))', "legendFormat": "{{error_category}}", "refId": "A", "instant": True}],
            grid=_grid(20, 18, 4, 8),
        ),

        row_panel("SLA Compliance", y=26),
        timeseries_panel(
            "SLA Breach Rate by Tenant",
            [_prom_target('sum by (tenant_id) (rate(ai_gateway_request_count_total{status="error",tenant_id=~"$tenant"}[5m])) / clamp_min(sum by (tenant_id) (rate(ai_gateway_request_count_total{tenant_id=~"$tenant"}[5m])),1e-9) * 100', "{{tenant_id}}")],
            unit="percent", grid=_grid(0, 27, 12, 8),
        ),
        barchart_panel(
            "Total Requests by Routing Reason (last 1h)",
            [_loki_instant_target(f'sum by (routing_reason) (count_over_time({_LOKI_STREAM} event_type = "telemetry_event" [1h]))', "{{routing_reason}}")],
            unit="short", grid=_grid(12, 27, 12, 8),
            datasource=DS_LOKI,
        ),

        row_panel("Live Request Log", y=35),
        logs_panel(
            "Live Telemetry Events",
            f'{_LOKI_STREAM} event_type = "telemetry_event" '
            '| line_format "{{.timestamp}} [{{.model_name}}] {{.operation_name}} '
            'status={{.status}} lat={{.latency_ms}}ms tenant={{.tenant_id}} '
            'routing={{.routing_reason}}"',
            grid=_grid(0, 36, 24, 10),
        ),
    ]

    return dashboard(
        uid="ai-telemetry-traffic",
        title="2. Traffic & Request Analytics",
        description="Request volumes, model usage, error taxonomy, SLA compliance.",
        tags=["ai-telemetry", "traffic", "errors"],
        panels=panels,
    )


# ===========================================================================
# D A S H B O A R D   3 — Latency & Performance Metrics
# ===========================================================================

def build_d3() -> dict:
    global _id_counter; _id_counter = 0

    _f = '{environment=~"$environment",tenant_id=~"$tenant",model_name=~"$model"}'
    _tele = (
        f'{_LOKI_STREAM} event_type="telemetry_event" '
        '| tenant_id=~"$tenant" | model_name=~"$model"'
    )

    panels = [
        timeseries_panel(
            "End-to-end response latency",
            [_prom_target(
                f'sum(rate(ai_gateway_request_duration_milliseconds_sum{_f}[5m])) '
                f'/ clamp_min(sum(rate(ai_gateway_request_duration_milliseconds_count{_f}[5m])), 1e-9)',
                "Avg latency", "A",
            )],
            unit="ms", grid=_grid(0, 0, 24, 8),
        ),

        timeseries_panel(
            "Request Latency — p50 / p95 / p99",
            [
                _prom_target(
                    f'histogram_quantile(0.50, sum by (le) (rate(ai_gateway_request_duration_milliseconds_bucket{_f}[5m])))',
                    "p50", "A",
                ),
                _prom_target(
                    f'histogram_quantile(0.95, sum by (le) (rate(ai_gateway_request_duration_milliseconds_bucket{_f}[5m])))',
                    "p95", "B",
                ),
                _prom_target(
                    f'histogram_quantile(0.99, sum by (le) (rate(ai_gateway_request_duration_milliseconds_bucket{_f}[5m])))',
                    "p99", "C",
                ),
            ],
            unit="ms", grid=_grid(0, 8, 24, 8),
        ),

        timeseries_panel(
            "Model Specific Latency",
            [_prom_target(
                f'histogram_quantile(0.95, sum by (le, model_name) '
                f'(rate(ai_gateway_request_duration_milliseconds_bucket{_f}[5m])))',
                "{{model_name}}", "A",
            )],
            unit="ms", grid=_grid(0, 16, 12, 8),
        ),
        timeseries_panel(
            "First token latency (Model Based)",
            [_loki_target(
                f'avg by (model_name) (avg_over_time({_tele} '
                f'| streaming="true" | unwrap first_token_ms [5m]))',
                "{{model_name}}", "A",
            )],
            unit="ms", grid=_grid(12, 16, 12, 8),
            datasource=DS_LOKI,
        ),

        timeseries_panel(
            "Queue delays",
            [
                _loki_target(
                    f'avg(avg_over_time({_tele} | unwrap queue_wait_ms [5m]))',
                    "Avg queue delay", "A",
                ),
                _loki_target(
                    f'avg by (model_name) (avg_over_time({_tele} | unwrap queue_wait_ms [5m]))',
                    "{{model_name}}", "B",
                ),
            ],
            unit="ms", grid=_grid(0, 24, 24, 8),
            datasource=DS_LOKI,
        ),
    ]

    return dashboard(
        uid="ai-telemetry-latency",
        title="3. Latency & Performance Metrics",
        description="End-to-end latency, percentiles, model-specific latency, first-token latency, and queue delays.",
        tags=["ai-telemetry", "latency", "performance"],
        panels=panels,
    )


# ===========================================================================
# D A S H B O A R D   4 — Cost & Usage Metrics
# ===========================================================================

def build_d4() -> dict:
    global _id_counter; _id_counter = 0

    _f = '{environment=~"$environment",tenant_id=~"$tenant",model_name=~"$model"}'
    _tele = (
        f'{_LOKI_STREAM} event_type="telemetry_event" '
        '| tenant_id=~"$tenant" | model_name=~"$model"'
    )

    panels = [
        timeseries_panel(
            "Cost per request",
            [
                _loki_target(
                    f'avg(avg_over_time({_tele} | unwrap cost_usd [5m]))',
                    "Avg cost / request", "A",
                ),
                _loki_target(
                    f'avg by (model_name) (avg_over_time({_tele} | unwrap cost_usd [5m]))',
                    "{{model_name}}", "B",
                ),
            ],
            unit="currencyUSD", grid=_grid(0, 0, 12, 8),
            datasource=DS_LOKI,
        ),
        timeseries_panel(
            "Cost per user/session",
            [
                _loki_target(
                    f'sum(sum by (user_id) (sum_over_time({_tele} | unwrap cost_usd [5m]))) '
                    f'/ count(sum by (user_id) (count_over_time({_tele} [5m])))',
                    "Avg spend / active user", "A",
                ),
                _loki_target(
                    f'sum(sum by (session_id) (sum_over_time({_tele} | unwrap cost_usd [5m]))) '
                    f'/ count(sum by (session_id) (count_over_time({_tele} [5m])))',
                    "Avg spend / active session", "B",
                ),
            ],
            unit="currencyUSD", grid=_grid(12, 0, 12, 8),
            datasource=DS_LOKI,
        ),

        timeseries_panel(
            "Daily/monthly spend",
            [
                _prom_target(
                    f'sum(increase(ai_gateway_request_cost_USD_total{_f}[24h]))',
                    "Daily spend (24h)", "A",
                ),
                _prom_target(
                    f'sum(increase(ai_gateway_request_cost_USD_total{_f}[30d]))',
                    "Monthly spend (30d)", "B",
                ),
            ],
            unit="currencyUSD", grid=_grid(0, 8, 24, 8),
        ),

        piechart_panel(
            "Total cost breakdown",
            [{"datasource": DS_PROMETHEUS,
              "expr": f'sort_desc(sum by (tenant_id) (increase(ai_gateway_request_cost_USD_total{_f}[24h])))',
              "legendFormat": "{{tenant_id}}", "refId": "A", "instant": True}],
            grid=_grid(0, 16, 12, 8),
        ),
        barchart_panel(
            "Model-wise cost breakdown",
            [{"datasource": DS_PROMETHEUS,
              "expr": f'sort_desc(sum by (model_name) (increase(ai_gateway_request_cost_USD_total{_f}[24h])))',
              "legendFormat": "{{model_name}}", "refId": "A", "instant": True}],
            unit="currencyUSD", grid=_grid(12, 16, 12, 8),
        ),

        timeseries_panel(
            "Cache hit savings",
            [
                _loki_target(
                    f'sum(sum_over_time({_tele} | unwrap cache_savings_usd [5m]))',
                    "Cache savings USD", "A",
                ),
                _loki_target(
                    f'sum by (model_name) (sum_over_time({_tele} | unwrap cache_savings_usd [5m]))',
                    "{{model_name}}", "B",
                ),
            ],
            unit="currencyUSD", grid=_grid(0, 24, 24, 8),
            datasource=DS_LOKI,
        ),
    ]

    return dashboard(
        uid="ai-telemetry-cost",
        title="4. Cost & Usage Metrics",
        description="Cost per request, user/session spend, daily and monthly totals, breakdowns, and cache savings.",
        tags=["ai-telemetry", "cost", "usage"],
        panels=panels,
    )


# ===========================================================================
# D A S H B O A R D   5 — Model Quality Metrics
# ===========================================================================

def build_d5() -> dict:
    global _id_counter; _id_counter = 0

    _eval = f'{_LOKI_STREAM} event_type="eval_result"'
    _tele = f'{_LOKI_STREAM} event_type="telemetry_event"'
    # % of judged responses flagged as hallucinating (faithfulness < 5 on 0–10 scale).
    _hallucination_rate = _loki_ratio(
        f'sum(count_over_time({_eval} | faithfulness < 5 [1h]))',
        f'sum(count_over_time({_eval} [1h]))',
    )
    # Judge scores are 0–10; factual accuracy is shown as 0–100 %.
    _factual_accuracy = f'avg(avg_over_time({_eval} | unwrap faithfulness [1h])) * 10'
    _relevance_score = f'avg(avg_over_time({_eval} | unwrap relevance [1h]))'
    _groundedness_score = f'avg(avg_over_time({_eval} | unwrap groundedness [1h]))'

    _score_th = [
        {"color": "red", "value": None},
        {"color": "yellow", "value": 60},
        {"color": "green", "value": 80},
    ]
    _halluc_th = [
        {"color": "green", "value": None},
        {"color": "yellow", "value": 10},
        {"color": "red", "value": 20},
    ]

    panels = [
        stat_panel(
            "Hallucination rate",
            _hallucination_rate,
            unit="percent", decimals=1,
            thresholds=_halluc_th,
            grid=_grid(0, 0, 6, 4), datasource=DS_LOKI,
        ),
        stat_panel(
            "Factual accuracy",
            _factual_accuracy,
            unit="percent", decimals=1,
            thresholds=_score_th,
            grid=_grid(6, 0, 6, 4), datasource=DS_LOKI,
        ),
        stat_panel(
            "Relevance score",
            _relevance_score,
            unit="short", decimals=1,
            thresholds=[{"color":"red","value":None},{"color":"yellow","value":6},{"color":"green","value":8}],
            grid=_grid(12, 0, 6, 4), datasource=DS_LOKI,
        ),
        stat_panel(
            "Groundedness score",
            _groundedness_score,
            unit="short", decimals=1,
            thresholds=[{"color":"red","value":None},{"color":"yellow","value":6},{"color":"green","value":8}],
            grid=_grid(18, 0, 6, 4), datasource=DS_LOKI,
        ),

        timeseries_panel(
            "Hallucination rate over time",
            [_loki_target(
                _loki_ratio(
                    f'sum(count_over_time({_eval} | faithfulness < 5 [5m]))',
                    f'sum(count_over_time({_eval} [5m]))',
                ),
                "Hallucination %", "A",
            )],
            unit="percent", decimals=1, axis_soft_max=30,
            grid=_grid(0, 4, 12, 8), datasource=DS_LOKI,
        ),
        timeseries_panel(
            "Factual accuracy",
            [_loki_target(f'{_factual_accuracy}', "Factual accuracy %", "A")],
            unit="percent", decimals=1,
            grid=_grid(12, 4, 12, 8), datasource=DS_LOKI,
        ),
        timeseries_panel(
            "Relevance score",
            [
                _loki_target(f'{_relevance_score}', "Relevance (0–10)", "A"),
                _loki_target(
                    f'avg by (model_name) (avg_over_time({_eval} | unwrap relevance [1h]))',
                    "{{model_name}}", "B",
                ),
            ],
            unit="short", decimals=1,
            grid=_grid(0, 12, 12, 8), datasource=DS_LOKI,
        ),
        timeseries_panel(
            "Groundedness score",
            [
                _loki_target(f'{_groundedness_score}', "Groundedness (0–10)", "A"),
                _loki_target(
                    f'avg by (model_name) (avg_over_time({_eval} | unwrap groundedness [1h]))',
                    "{{model_name}}", "B",
                ),
            ],
            unit="short", decimals=1,
            grid=_grid(12, 12, 12, 8), datasource=DS_LOKI,
        ),

        row_panel("Evaluation Ops", y=20),
        stat_panel(
            "Evaluation Coverage",
            _loki_ratio(
                f'sum(count_over_time({_eval} [1h]))',
                f'sum(count_over_time({_tele} [1h]))',
            ),
            unit="percent", decimals=2,
            thresholds=[{"color": "blue", "value": None}],
            grid=_grid(0, 21, 6, 4), datasource=DS_LOKI,
        ),
        stat_panel(
            "Evaluator Errors (24h)",
            f'sum(count_over_time({_eval} |~ "mock_judge_timeout" [24h])) or on() vector(0)',
            unit="short", decimals=0,
            thresholds=[{"color":"green","value":None},{"color":"yellow","value":1},{"color":"red","value":10}],
            grid=_grid(6, 21, 6, 4), datasource=DS_LOKI,
        ),
        logs_panel(
            "Low-Quality Responses (hallucination flagged)",
            f'{_eval} | faithfulness < 5',
            grid=_grid(12, 21, 12, 8), datasource=DS_LOKI,
        ),
    ]

    return dashboard(
        uid="ai-telemetry-quality",
        title="5. Model Quality Metrics",
        description="Hallucination rate, factual accuracy, relevance, and groundedness from eval_result judge scores.",
        tags=["ai-telemetry", "quality", "evaluation"],
        panels=panels,
    )


# ===========================================================================
# D A S H B O A R D   6 — Safety & Security Metrics
# ===========================================================================

def build_d6() -> dict:
    global _id_counter; _id_counter = 0

    _plog = f'{_LOKI_STREAM} event_type = "prompt_log_event"'
    _tele = f'{_LOKI_STREAM} event_type = "telemetry_event"'

    _pii_rate = _loki_ratio(
        f'sum(count_over_time({_plog} | pii_detected="true" [24h]))',
        f'sum(count_over_time({_plog} [24h]))',
    )
    _toxicity_score = f'avg(avg_over_time({_plog} | unwrap toxicity_score [24h])) * 100'

    _safety_th = [
        {"color": "green", "value": None},
        {"color": "yellow", "value": 30},
        {"color": "red", "value": 60},
    ]

    panels = [
        stat_panel(
            "Toxicity score",
            _toxicity_score,
            unit="percent", decimals=1,
            thresholds=_safety_th,
            grid=_grid(0, 0, 5, 4), datasource=DS_LOKI,
        ),
        stat_panel(
            "PII detection rate",
            _pii_rate,
            unit="percent", decimals=1,
            thresholds=[{"color": "green", "value": None}, {"color": "yellow", "value": 5}, {"color": "red", "value": 15}],
            grid=_grid(5, 0, 5, 4), datasource=DS_LOKI,
        ),
        stat_panel(
            "Prompt injection attempts",
            f'sum(count_over_time({_plog} | prompt_injection_detected="true" [24h])) or vector(0)',
            unit="short", decimals=0,
            thresholds=[{"color": "green", "value": None}, {"color": "yellow", "value": 5}, {"color": "red", "value": 25}],
            grid=_grid(10, 0, 5, 4), datasource=DS_LOKI,
        ),
        stat_panel(
            "Jailbreak attempts",
            f'sum(count_over_time({_plog} | jailbreak_attempt="true" [24h])) or vector(0)',
            unit="short", decimals=0,
            thresholds=[{"color": "green", "value": None}, {"color": "yellow", "value": 3}, {"color": "red", "value": 15}],
            grid=_grid(15, 0, 5, 4), datasource=DS_LOKI,
        ),
        stat_panel(
            "Compliance violations",
            f'sum(count_over_time({_plog} | compliance_violation="true" [24h])) or vector(0)',
            unit="short", decimals=0,
            thresholds=[{"color": "green", "value": None}, {"color": "yellow", "value": 5}, {"color": "red", "value": 20}],
            grid=_grid(20, 0, 4, 4), datasource=DS_LOKI,
        ),

        row_panel("Safety Trends", y=4),
        timeseries_panel(
            "Toxicity score",
            [_loki_target(f'avg(avg_over_time({_plog} | unwrap toxicity_score [5m])) * 100', "Toxicity %")],
            unit="percent", decimals=1, axis_soft_max=100,
            grid=_grid(0, 5, 12, 8), datasource=DS_LOKI,
        ),
        timeseries_panel(
            "PII detection rate",
            [
                _loki_target(_loki_ratio(
                    f'sum(count_over_time({_plog} | pii_detected="true" [5m]))',
                    f'sum(count_over_time({_plog} [5m]))',
                ), "PII %"),
            ],
            unit="percent", grid=_grid(12, 5, 12, 8), datasource=DS_LOKI,
        ),
        timeseries_panel(
            "Prompt injection attempts / min",
            [_loki_target(
                f'sum(count_over_time({_plog} | prompt_injection_detected="true" [1m])) or vector(0)',
                "Injections/min",
            )],
            unit="short", grid=_grid(0, 13, 8, 8), datasource=DS_LOKI,
        ),
        timeseries_panel(
            "Jailbreak attempts / min",
            [_loki_target(
                f'sum(count_over_time({_plog} | jailbreak_attempt="true" [1m])) or vector(0)',
                "Jailbreaks/min",
            )],
            unit="short", grid=_grid(8, 13, 8, 8), datasource=DS_LOKI,
        ),
        timeseries_panel(
            "Compliance violations / min",
            [_loki_target(
                f'sum(count_over_time({_plog} | compliance_violation="true" [1m])) or vector(0)',
                "Violations/min",
            )],
            unit="short", grid=_grid(16, 13, 8, 8), datasource=DS_LOKI,
        ),

        row_panel("PII & Data Classification", y=21),
        stat_panel("PII Events Today",
                   f'sum(count_over_time({_plog} | pii_detected="true" [24h])) or vector(0)',
                   unit="short", decimals=0,
                   thresholds=[{"color":"green","value":None},{"color":"yellow","value":10},{"color":"red","value":50}],
                   grid=_grid(0, 22, 4, 4), datasource=DS_LOKI),
        stat_panel("PHI Requests Today",
                   f'sum(count_over_time({_tele} | data_classification="phi" [24h])) or vector(0)',
                   unit="short", decimals=0,
                   thresholds=[{"color":"blue","value":None}],
                   grid=_grid(4, 22, 4, 4), datasource=DS_LOKI),
        stat_panel("PII Requests Today",
                   f'sum(count_over_time({_tele} | data_classification="pii" [24h])) or vector(0)',
                   unit="short", decimals=0,
                   thresholds=[{"color":"blue","value":None}],
                   grid=_grid(8, 22, 4, 4), datasource=DS_LOKI),
        stat_panel("Unique Prompt Hashes (24h)",
                   f'count(sum by (prompt_hash) (count_over_time({_plog} [24h])))',
                   unit="short", decimals=0,
                   thresholds=[{"color":"blue","value":None}],
                   grid=_grid(12, 22, 4, 4), datasource=DS_LOKI),
        piechart_panel(
            "Data Classification Distribution",
            [_loki_instant_target(f'sum by (data_classification) (count_over_time({_tele} [1h]))', "{{data_classification}}")],
            grid=_grid(16, 22, 8, 4), datasource=DS_LOKI,
        ),
        timeseries_panel(
            "PII Events by Tenant",
            [_loki_target(f'sum by (tenant_id) (count_over_time({_plog} | pii_detected="true" [5m])) or vector(0)', "{{tenant_id}}")],
            unit="short", grid=_grid(0, 26, 12, 8), datasource=DS_LOKI,
        ),
        barchart_panel(
            "PHI + PII Volume by Tenant (last 1h)",
            [_loki_instant_target(f'sum by (tenant_id) (count_over_time({_tele} | data_classification=~"phi|pii" [1h]))', "{{tenant_id}}")],
            unit="short", grid=_grid(12, 26, 12, 8), datasource=DS_LOKI,
        ),

        row_panel("Prompt Audit Log", y=34),
        logs_panel(
            "Prompt Log Events (PII-scrubbed)",
            f'{_plog}',
            grid=_grid(0, 35, 24, 10), datasource=DS_LOKI,
        ),

        row_panel("High-Risk Request Table", y=45),
        table_panel(
            "PHI / PII Requests with Trace Links",
            [{"datasource": DS_LOKI,
              "expr": f'{_tele} | data_classification=~"phi|pii" | line_format "{{.request_id}} {{.tenant_id}} {{.model_name}} {{.trace_id}}"',
              "refId": "A"}],
            grid=_grid(0, 46, 24, 8), datasource=DS_LOKI,
        ),
        logs_panel(
            "Safety incidents (injection, jailbreak, compliance)",
            f'{_plog} | prompt_injection_detected="true" or jailbreak_attempt="true" or compliance_violation="true"',
            grid=_grid(0, 54, 24, 8), datasource=DS_LOKI,
        ),
    ]

    return dashboard(
        uid="ai-telemetry-safety",
        title="6. Safety & Security Metrics",
        description="Toxicity score, PII detection rate, prompt injection, jailbreak, and compliance violations.",
        tags=["ai-telemetry", "safety", "security", "pii", "compliance"],
        panels=panels,
    )


# ===========================================================================
# D A S H B O A R D   7 — Infrastructure Metrics
# ===========================================================================

def build_d7() -> dict:
    global _id_counter; _id_counter = 0

    _ns = 'namespace="ai-gateway-ns"'
    _gw = 'namespace="ai-gateway-ns", container="ai-gateway"'
    _f = '{environment=~"$environment",tenant_id=~"$tenant",model_name=~"$model"}'
    _f_completion = (
        '{token_type="completion",environment=~"$environment",'
        'tenant_id=~"$tenant",model_name=~"$model"}'
    )
    _cpu_util = (
        f'sum(rate(container_cpu_usage_seconds_total{{{_gw}}}[5m])) '
        f'/ clamp_min(sum(kube_pod_status_phase{{{_ns}, phase="Running"}}), 1) * 100'
    )
    _model_throughput = f'sum(rate(ai_gateway_request_token_total{_f_completion}[5m]))'
    _oom_failures = (
        f'sum(increase(kube_pod_container_oom_killed_total{{{_ns}}}[24h])) or vector(0)'
    )
    _pod_health = (
        f'kube_deployment_status_replicas_available{{{_ns}}} '
        f'/ clamp_min(kube_deployment_spec_replicas{{{_ns}}}, 1) * 100'
    )
    _scaling_events = (
        f'sum(increase(kube_horizontalpodautoscaler_scaling_events_total{{{_ns}}}[24h])) '
        f'or vector(0)'
    )
    _api_error_rate = (
        f'sum(rate(ai_gateway_request_count_total{{status="error",environment=~"$environment",'
        f'tenant_id=~"$tenant",model_name=~"$model"}}[5m])) '
        f'/ clamp_min(sum(rate(ai_gateway_request_count_total{_f}[5m])), 1e-9) * 100'
    )

    panels = [
        stat_panel(
            "CPU utilization",
            _cpu_util,
            unit="percent", decimals=1,
            thresholds=[{"color": "green", "value": None}, {"color": "yellow", "value": 70}, {"color": "red", "value": 90}],
            grid=_grid(0, 0, 4, 4),
        ),
        stat_panel(
            "Model throughput",
            _model_throughput,
            unit="tps", decimals=1,
            thresholds=[{"color": "blue", "value": None}],
            grid=_grid(4, 0, 4, 4),
        ),
        stat_panel(
            "OOM failures",
            _oom_failures,
            unit="short", decimals=0,
            thresholds=[{"color": "green", "value": None}, {"color": "yellow", "value": 1}, {"color": "red", "value": 3}],
            grid=_grid(8, 0, 4, 4),
        ),
        stat_panel(
            "Pod/container health",
            _pod_health,
            unit="percent", decimals=1,
            thresholds=[{"color": "red", "value": None}, {"color": "yellow", "value": 80}, {"color": "green", "value": 95}],
            grid=_grid(12, 0, 4, 4),
        ),
        stat_panel(
            "Auto-scaling events",
            _scaling_events,
            unit="short", decimals=0,
            thresholds=[{"color": "blue", "value": None}],
            grid=_grid(16, 0, 4, 4),
        ),
        stat_panel(
            "API error rate",
            _api_error_rate,
            unit="percent", decimals=2,
            thresholds=[{"color": "green", "value": None}, {"color": "yellow", "value": 2}, {"color": "red", "value": 5}],
            grid=_grid(20, 0, 4, 4),
        ),

        row_panel("Infrastructure Trends", y=4),
        timeseries_panel(
            "CPU utilization",
            [_prom_target(_cpu_util, "CPU % per pod (avg cores)", "A")],
            unit="percent", decimals=1, grid=_grid(0, 5, 12, 8),
        ),
        timeseries_panel(
            "Model throughput",
            [
                _prom_target(_model_throughput, "Completion tokens/s", "A"),
                _prom_target(
                    f'sum by (model_name) (rate(ai_gateway_request_token_total{_f_completion}[5m]))',
                    "{{model_name}}", "B",
                ),
            ],
            unit="tps", grid=_grid(12, 5, 12, 8),
        ),
        timeseries_panel(
            "OOM failures",
            [_prom_target(
                f'sum(increase(kube_pod_container_oom_killed_total{{{_ns}}}[1h])) or vector(0)',
                "OOM events / h", "A",
            )],
            unit="short", grid=_grid(0, 13, 8, 8),
        ),
        timeseries_panel(
            "Pod/container health",
            [
                _prom_target(_pod_health, "Available %", "A"),
                _prom_target(
                    f'sum(kube_pod_status_phase{{{_ns}, phase="Running"}})',
                    "Running pods", "B",
                ),
            ],
            unit="percent", decimals=1, grid=_grid(8, 13, 8, 8),
        ),
        timeseries_panel(
            "Auto-scaling events",
            _prom_targets(
                (f'sum(increase(kube_horizontalpodautoscaler_scaling_events_total{{{_ns}, direction="up"}}[1h])) or vector(0)', "scale up"),
                (f'sum(increase(kube_horizontalpodautoscaler_scaling_events_total{{{_ns}, direction="down"}}[1h])) or vector(0)', "scale down"),
            ),
            unit="short", grid=_grid(16, 13, 8, 8),
        ),
        timeseries_panel(
            "API error rate",
            [
                _prom_target(_api_error_rate, "Error %", "A"),
                _prom_target(
                    f'sum by (error_type) (rate(ai_gateway_exception_count_total{_f}[5m]))',
                    "{{error_type}}", "B",
                ),
            ],
            unit="percent", decimals=2, grid=_grid(0, 21, 24, 8),
        ),

        row_panel("HPA Scaling", y=29),
        timeseries_panel(
            "HPA Current vs Desired Replicas",
            _prom_targets(
                ('kube_horizontalpodautoscaler_status_current_replicas{namespace="ai-gateway-ns"}', "current"),
                ('kube_horizontalpodautoscaler_status_desired_replicas{namespace="ai-gateway-ns"}', "desired"),
                ('kube_horizontalpodautoscaler_spec_min_replicas{namespace="ai-gateway-ns"}', "min"),
                ('kube_horizontalpodautoscaler_spec_max_replicas{namespace="ai-gateway-ns"}', "max"),
            ),
            unit="short", grid=_grid(0, 30, 12, 8),
        ),
        timeseries_panel(
            "Pod Restart Rate",
            [_prom_target('sum by (pod) (rate(kube_pod_container_status_restarts_total{namespace="ai-gateway-ns"}[15m]))', "{{pod}}")],
            unit="ops", grid=_grid(12, 30, 12, 8),
        ),

        row_panel("Container Resources", y=38),
        timeseries_panel(
            "Container Memory RSS by Pod",
            [_prom_target('container_memory_rss{namespace="ai-gateway-ns", container="ai-gateway"}', "{{pod}}")],
            unit="bytes", grid=_grid(0, 39, 12, 8),
        ),
        timeseries_panel(
            "Container CPU Usage by Pod",
            [_prom_target('sum by (pod) (rate(container_cpu_usage_seconds_total{namespace="ai-gateway-ns", container="ai-gateway"}[2m]))', "{{pod}}")],
            unit="percentunit", grid=_grid(12, 39, 12, 8),
        ),
        timeseries_panel(
            "Node Memory Available Over Time",
            _prom_targets(
                ('node_memory_MemAvailable_bytes', "available"),
                ('node_memory_MemTotal_bytes', "total"),
            ),
            unit="bytes", grid=_grid(0, 47, 12, 8),
        ),
        timeseries_panel(
            "Node CPU Usage (user mode)",
            [_prom_target('rate(node_cpu_seconds_total{mode="user"}[2m]) * 100', "cpu user %")],
            unit="percent", grid=_grid(12, 47, 12, 8),
        ),

        row_panel("Runner Self-Observability (NFR-014)", y=55),
        heatmap_panel(
            "Batch Duration Heatmap",
            'sum by (le) (rate(ai_telemetry_runner_batch_duration_seconds_bucket[2m]))',
            unit="s", grid=_grid(0, 56, 12, 8),
        ),
        timeseries_panel(
            "Kafka Queue Depth",
            [_prom_target('ai_telemetry_runner_kafka_queue_depth', "queue depth")],
            unit="short", grid=_grid(12, 56, 12, 8),
        ),
        timeseries_panel(
            "Publish Error Rate by Reason",
            [_prom_target('sum by (reason) (rate(ai_telemetry_runner_publish_errors_total[5m])) or label_replace(vector(0), "reason", "none", "", "")', "{{reason}}")],
            unit="ops", grid=_grid(0, 64, 12, 8),
        ),
        timeseries_panel(
            "Batch Duration p99",
            [_prom_target('histogram_quantile(0.99, sum by (le) (rate(ai_telemetry_runner_batch_duration_seconds_bucket[5m])))', "p99 batch duration")],
            unit="s", grid=_grid(12, 64, 12, 8),
        ),

        row_panel("OTel Collector Pipeline Health", y=72),
        timeseries_panel(
            "Collector Exporter Queue Size",
            _prom_targets(
                ('otelcol_exporter_queue_size{exporter="otlp/tempo"}',       "tempo queue"),
                ('otelcol_exporter_queue_size{exporter="prometheusremotewrite"}', "prom queue"),
                ('otelcol_exporter_queue_size{exporter="loki"}',             "loki queue"),
            ),
            unit="short", grid=_grid(0, 73, 12, 8),
        ),
        timeseries_panel(
            "Collector Export Failures",
            _prom_targets(
                ('rate(otelcol_exporter_send_failed_spans[5m])', "failed spans/s"),
                ('rate(otelcol_exporter_send_failed_log_records[5m])', "failed logs/s"),
            ),
            unit="ops", grid=_grid(12, 73, 12, 8),
        ),
    ]

    return dashboard(
        uid="ai-telemetry-infra",
        title="7. Infrastructure Metrics",
        description="CPU utilization, model throughput, OOM failures, pod health, auto-scaling, and API error rates.",
        tags=["ai-telemetry", "infrastructure", "kubernetes", "sre"],
        panels=panels,
    )


# ===========================================================================
# D A S H B O A R D   8 — Token & Context Metrics
# ===========================================================================

def build_d8() -> dict:
    global _id_counter; _id_counter = 0

    _f = '{environment=~"$environment",tenant_id=~"$tenant",model_name=~"$model"}'
    # Single label set — PromQL rejects metric{a}{b} (two brace blocks).
    _f_completion = (
        '{token_type="completion",environment=~"$environment",'
        'tenant_id=~"$tenant",model_name=~"$model"}'
    )
    _f_prompt = (
        '{token_type="prompt",environment=~"$environment",'
        'tenant_id=~"$tenant",model_name=~"$model"}'
    )
    _req_rate = f'clamp_min(sum(rate(ai_gateway_request_count_total{_f}[5m])), 1e-9)'
    _tok_per_req = (
        f'sum(rate(ai_gateway_request_token_total{_f}[5m])) / {_req_rate}'
    )
    _prompt_per_req = (
        f'sum(rate(ai_gateway_request_token_total{_f_prompt}[5m])) / {_req_rate}'
    )
    # Loki: keep filters on parsed JSON only; stream label is service_name.
    _tele = f'{_LOKI_STREAM} event_type="telemetry_event"'
    _stream = f'{_tele} | stream_response_ms > 0'
    _stream_tps = f'{_tele} | tokens_per_second > 0'

    panels = [
        timeseries_panel(
            "Output Token Count",
            [
                _prom_target(
                    f'sum(rate(ai_gateway_request_token_total{_f_completion}[5m]))',
                    "Completion tokens/s", "A",
                ),
                _prom_target(
                    f'sum by (model_name) (rate(ai_gateway_request_token_total{_f_completion}[5m]))',
                    "{{model_name}}", "B",
                ),
            ],
            unit="tps", grid=_grid(0, 0, 12, 8),
        ),
        timeseries_panel(
            "Total tokens per request",
            [
                _prom_target(_tok_per_req, "Avg tokens / request", "A"),
                _prom_target(
                    f'sum by (model_name) (rate(ai_gateway_request_token_total{_f}[5m])) '
                    f'/ clamp_min(sum by (model_name) (rate(ai_gateway_request_count_total{_f}[5m])), 1e-9)',
                    "{{model_name}}", "B",
                ),
            ],
            unit="short", decimals=0, grid=_grid(12, 0, 12, 8),
        ),

        timeseries_panel(
            "Context Window Utilization (%)",
            [
                _loki_target(
                    f'avg(avg_over_time({_tele} | unwrap context_window_utilization_pct [5m]))',
                    "Avg utilization %", "A",
                ),
                _loki_target(
                    f'avg by (model_name) (avg_over_time({_tele} | unwrap context_window_utilization_pct [5m]))',
                    "{{model_name}}", "B",
                ),
            ],
            unit="percent", decimals=1, axis_soft_max=100,
            grid=_grid(0, 8, 12, 8), datasource=DS_LOKI,
        ),
        timeseries_panel(
            "Prompt size",
            [
                _prom_target(_prompt_per_req, "Avg prompt tokens / request", "A"),
                _prom_target(
                    f'sum by (model_name) (rate(ai_gateway_request_token_total{_f_prompt}[5m])) '
                    f'/ clamp_min(sum by (model_name) (rate(ai_gateway_request_count_total{_f}[5m])), 1e-9)',
                    "{{model_name}}", "B",
                ),
            ],
            unit="short", decimals=0, grid=_grid(12, 8, 12, 8),
        ),

        timeseries_panel(
            "Live token generation rate",
            [
                _prom_target(
                    f'sum(rate(ai_gateway_request_token_total{_f_completion}[1m]))',
                    "Live completion tokens/s", "A",
                ),
                _prom_target(
                    f'sum by (model_name) (rate(ai_gateway_request_token_total{_f_completion}[1m]))',
                    "{{model_name}}", "B",
                ),
            ],
            unit="tps", grid=_grid(0, 16, 12, 8),
        ),
        timeseries_panel(
            "Streaming response latency",
            [
                _loki_target(
                    f'avg(avg_over_time({_stream} | unwrap stream_response_ms [5m]))',
                    "Avg stream response ms", "A",
                ),
                _loki_target(
                    f'avg by (model_name) (avg_over_time({_stream} | unwrap stream_response_ms [5m]))',
                    "{{model_name}}", "B",
                ),
            ],
            unit="ms", grid=_grid(12, 16, 12, 8),
            datasource=DS_LOKI,
        ),

        timeseries_panel(
            "Tokens/sec",
            [
                _loki_target(
                    f'avg(avg_over_time({_stream_tps} | unwrap tokens_per_second [5m]))',
                    "Avg tokens/s", "A",
                ),
                _loki_target(
                    f'avg by (model_name) (avg_over_time({_stream_tps} | unwrap tokens_per_second [5m]))',
                    "{{model_name}}", "B",
                ),
            ],
            unit="tps", grid=_grid(0, 24, 12, 8),
            datasource=DS_LOKI,
        ),
        timeseries_panel(
            "Real-time error spikes",
            [
                _prom_target(
                    f'sum(increase(ai_gateway_exception_count_total{_f}[5m])) or on() vector(0)',
                    "Errors (5m increase)", "A",
                ),
                _prom_target(
                    f'sum(rate(ai_gateway_exception_count_total{_f}[1m])) * 60',
                    "Errors / min", "B",
                ),
                _prom_target(
                    f'sum by (error_type) (increase(ai_gateway_exception_count_total{_f}[5m]))',
                    "{{error_type}}", "C",
                ),
            ],
            unit="short", grid=_grid(12, 24, 12, 8),
        ),
    ]

    return dashboard(
        uid="ai-telemetry-tokens",
        title="8. Token & Context Metrics",
        description="Output tokens, per-request totals, context window fill, prompt size, streaming throughput, and error spikes.",
        tags=["ai-telemetry", "tokens", "context", "streaming"],
        panels=panels,
        refresh="15s",
    )


# ===========================================================================
# D A S H B O A R D   9 — User-Level Observability
# ===========================================================================

def build_d9() -> dict:
    global _id_counter; _id_counter = 0

    _tele = (
        f'{_LOKI_STREAM} event_type="telemetry_event" '
        '| tenant_id=~"$tenant" | model_name=~"$model"'
    )
    _login = f'{_LOKI_STREAM} event_type="login_event" | tenant_id=~"$tenant"'

    # LogQL does not support Prometheus clamp_min — use `or on(...) vector(...)` instead.
    _prev_15m_tokens = (
        f"sum(sum_over_time({_tele} | unwrap total_tokens [30m])) "
        f"- sum(sum_over_time({_tele} | unwrap total_tokens [15m]))"
    )
    _spike_pct = (
        f"("
        f"sum(sum_over_time({_tele} | unwrap total_tokens [15m]) "
        f"/ ({_prev_15m_tokens} or vector(1)) - 1) * 100"
    )
    _user_spike_ratio = (
        f"topk(10, "
        f"sum by (user_id) (sum_over_time({_tele} | unwrap total_tokens [15m])) "
        f"/ (sum by (user_id) (sum_over_time({_tele} | unwrap total_tokens [1h])) * 0.25 "
        f"or on(user_id) vector(1e-6)))"
    )

    panels = [
        row_panel("Login & user growth", y=0),
        stat_panel(
            "Logins (24h)",
            f'sum(count_over_time({_login} [24h])) or vector(0)',
            unit="short", decimals=0,
            thresholds=[{"color": "blue", "value": None}],
            grid=_grid(0, 1, 6, 4), datasource=DS_LOKI,
        ),
        stat_panel(
            "Active users (24h)",
            f'count(sum by (user_id) (count_over_time({_tele} [24h])))',
            unit="short", decimals=0,
            thresholds=[{"color": "blue", "value": None}],
            grid=_grid(6, 1, 6, 4), datasource=DS_LOKI,
        ),
        stat_panel(
            "Monthly active users (30d)",
            f'count(sum by (user_id) (count_over_time({_login} [30d])))',
            unit="short", decimals=0,
            thresholds=[{"color": "blue", "value": None}],
            grid=_grid(12, 1, 6, 4), datasource=DS_LOKI,
        ),
        stat_panel(
            "LLM usage spike (15m vs prev 15m)",
            _spike_pct,
            unit="percent", decimals=1,
            thresholds=[
                {"color": "green", "value": None},
                {"color": "yellow", "value": 50},
                {"color": "red", "value": 150},
            ],
            grid=_grid(18, 1, 6, 4), datasource=DS_LOKI,
        ),

        timeseries_panel(
            "Login track",
            [_loki_target(
                f'sum(count_over_time({_login} [5m])) or vector(0)',
                "Logins / 5m", "A",
            )],
            unit="short", grid=_grid(0, 5, 12, 8), datasource=DS_LOKI,
        ),
        timeseries_panel(
            "Users added (daily active logins)",
            [_loki_target(
                f'count(sum by (user_id) (count_over_time({_login} [1d])))',
                "Distinct users / day", "A",
            )],
            unit="short", decimals=0, grid=_grid(12, 5, 12, 8), datasource=DS_LOKI,
        ),

        row_panel("Token consumption by user", y=13),
        barchart_panel(
            "Top 10 users — tokens (24h)",
            [_loki_instant_target(
                f'topk(10, sum by (user_id) (sum_over_time({_tele} | unwrap total_tokens [24h])))',
                "{{user_id}}",
            )],
            unit="short", grid=_grid(0, 14, 12, 8), datasource=DS_LOKI,
        ),
        timeseries_panel(
            "Top 10 users — token rate (5m)",
            [_loki_target(
                f'topk(10, sum by (user_id) (sum_over_time({_tele} | unwrap total_tokens [5m])))',
                "{{user_id}}", "A",
            )],
            unit="short", grid=_grid(12, 14, 12, 8), datasource=DS_LOKI,
        ),

        row_panel("Session-level usage", y=22),
        barchart_panel(
            "Top 10 users — session time (latency sum, 6h)",
            [_loki_instant_target(
                f'topk(10, sum by (user_id) (sum_over_time({_tele} | unwrap latency_ms [6h])))',
                "{{user_id}}",
            )],
            unit="ms", grid=_grid(0, 23, 12, 8), datasource=DS_LOKI,
        ),
        table_panel(
            "Session usage by user",
            [{"datasource": DS_LOKI,
              "expr": (
                  f"topk(50, sum by (user_id, session_id) "
                  f"(sum_over_time({_tele} | unwrap total_tokens [6h])))"
              ),
              "refId": "A"}],
            grid=_grid(12, 23, 12, 8), datasource=DS_LOKI,
        ),
        timeseries_panel(
            "Session time by user (top 10, 5m)",
            [_loki_target(
                f'topk(10, sum by (user_id) (sum_over_time({_tele} | unwrap latency_ms [5m])))',
                "{{user_id}}", "A",
            )],
            unit="ms", grid=_grid(0, 31, 24, 8), datasource=DS_LOKI,
        ),

        row_panel("Usage spikes", y=39),
        timeseries_panel(
            "Token volume — spike detector (5m buckets)",
            [
                _loki_target(
                    f'sum(sum_over_time({_tele} | unwrap total_tokens [5m]))',
                    "Tokens / 5m", "A",
                ),
                _loki_target(
                    f'avg_over_time(sum(sum_over_time({_tele} | unwrap total_tokens [5m]))[1h:5m])',
                    "1h rolling avg", "B",
                ),
            ],
            unit="short", grid=_grid(0, 40, 14, 8), datasource=DS_LOKI,
        ),
        barchart_panel(
            "Top 10 users — spike ratio (15m vs 1h baseline)",
            [_loki_instant_target(_user_spike_ratio, "{{user_id}}")],
            unit="short", grid=_grid(14, 40, 10, 8), datasource=DS_LOKI,
        ),
        logs_panel(
            "Recent login events",
            f'{_login}',
            grid=_grid(0, 48, 24, 8), datasource=DS_LOKI,
        ),
    ]

    return dashboard(
        uid="ai-telemetry-users",
        title="9. User-Level Observability",
        description=(
            "Login tracking, monthly user growth, top token consumers, "
            "session time, and sudden LLM usage spikes."
        ),
        tags=["ai-telemetry", "users", "sessions", "login"],
        panels=panels,
    )


# ===========================================================================
# Generate
# ===========================================================================

if __name__ == "__main__":
    builders = [
        ("01-executive-overview.json",   build_d1),
        ("02-traffic-analytics.json",    build_d2),
        ("03-latency-performance.json",  build_d3),
        ("04-token-cost.json",           build_d4),
        ("05-model-quality.json",        build_d5),
        ("06-safety-pii.json",           build_d6),
        ("07-infra-runner.json",         build_d7),
        ("08-token-context.json",        build_d8),
        ("09-user-observability.json",   build_d9),
    ]
    print("Generating Grafana dashboards…")
    for fname, builder in builders:
        d = builder()
        _save(fname, d)
    print(f"\nDone — {len(builders)} dashboards written to {OUT_DIR}/")
