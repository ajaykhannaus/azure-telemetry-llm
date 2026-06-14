#!/usr/bin/env python3
"""Test Adoption section Loki queries."""
import base64
import json
import urllib.request

LOKI = "http://localhost:3100"
GRAFANA = "http://localhost:3001"
AUTH = base64.b64encode(b"admin:admin").decode()

QUERIES = [
    ("login_event count 5m", 'sum(count_over_time({service_name=~".+"} | json | event_type="login_event" [5m]))'),
    ("DAU 24h", 'count(count by (user_id) (count_over_time({service_name=~".+"} | json | event_type="login_event" | user_id != "" [24h])))'),
    ("eligible_user_count", 'max(max_over_time({service_name=~".+"} | json | event_type="telemetry_event" | unwrap eligible_user_count [24h]))'),
    ("Adoption rate", '(count(count by (user_id) (count_over_time({service_name=~".+"} | json | event_type="login_event" | user_id != "" [24h]))) / (max(max_over_time({service_name=~".+"} | json | event_type="telemetry_event" | unwrap eligible_user_count [24h])) or on() vector(1))) * 100'),
    ("is_new_user logins", 'sum(count_over_time({service_name=~".+"} | json | event_type="login_event" | is_new_user="true" [24h]))'),
    ("feature_id users", 'sort_desc(count by (feature_id) (count by (user_id, feature_id) (count_over_time({service_name=~".+"} | json | event_type="telemetry_event" | user_id != "" | feature_id != "" [24h]))))'),
    ("dept penetration", '(count by (department) (count by (user_id, department) (count_over_time({service_name=~".+"} | json | event_type="telemetry_event" | user_id != "" | department != "" [1h]))) / (max by (department) (max_over_time({service_name=~".+"} | json | event_type="telemetry_event" | unwrap eligible_user_count [1h])) or on(department) vector(1)) * 100)'),
]


def loki_instant(expr: str) -> tuple[str, bool]:
    body = f"query={urllib.parse.quote(expr, safe='')}"
    req = urllib.request.Request(
        f"{LOKI}/loki/api/v1/query", data=body.encode(), method="POST",
    )
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    result = data.get("data", {}).get("result") or []
    return str(result)[:200], bool(result)


def grafana_query(expr: str, instant: bool = True) -> tuple[str, bool]:
    body = {
        "queries": [{
            "refId": "A",
            "datasource": {"type": "loki", "uid": "loki-ds"},
            "expr": expr,
            "queryType": "instant" if instant else "range",
        }],
        "from": "now-6h",
        "to": "now",
    }
    req = urllib.request.Request(
        f"{GRAFANA}/api/ds/query", data=json.dumps(body).encode(), method="POST",
    )
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Basic {AUTH}")
    with urllib.request.urlopen(req, timeout=45) as resp:
        res = json.loads(resp.read())
    err = res.get("results", {}).get("A", {}).get("error")
    if err:
        return f"ERROR: {err[:180]}", False
    frames = res["results"]["A"].get("frames") or []
    for frame in frames:
        vals = frame.get("data", {}).get("values") or []
        if any(v is not None for col in vals for v in col):
            return "PASS", True
    return "NO_DATA", False


if __name__ == "__main__":
    import urllib.parse

    print("=== Direct Loki ===")
    for name, expr in QUERIES:
        try:
            out, ok = loki_instant(expr)
            print(f"{'PASS' if ok else 'EMPTY':5} {name}: {out}")
        except Exception as exc:
            print(f"FAIL  {name}: {exc}")

    print("\n=== Via Grafana ===")
    for name, expr in QUERIES:
        try:
            out, ok = grafana_query(expr, instant=(name != "dept penetration"))
            print(f"{'PASS' if ok else out:5} {name}")
        except Exception as exc:
            print(f"FAIL  {name}: {exc}")
