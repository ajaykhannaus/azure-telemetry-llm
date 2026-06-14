#!/usr/bin/env python3
import base64, json, urllib.parse, urllib.request

LOKI = "http://localhost:3100"
GRAFANA = "http://localhost:3001"
AUTH = base64.b64encode(b"admin:admin").decode()


def loki(expr: str, timeout: int = 45):
    body = "query=" + urllib.parse.quote(expr, safe="")
    req = urllib.request.Request(
        f"{LOKI}/loki/api/v1/query", data=body.encode(), method="POST"
    )
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    return data.get("data", {}).get("result") or []


def grafana_ds():
    req = urllib.request.Request(
        f"{GRAFANA}/api/datasources",
        headers={"Authorization": f"Basic {AUTH}"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def grafana_dash():
    req = urllib.request.Request(
        f"{GRAFANA}/api/dashboards/uid/ai-telemetry-users",
        headers={"Authorization": f"Basic {AUTH}"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())["dashboard"]


STREAM = '{service_name=~".+"} | json'
queries = [
    ("login 5m", f'sum(count_over_time({STREAM} | event_type="login_event" [5m]))'),
    ("telemetry 5m", f'sum(count_over_time({STREAM} | event_type="telemetry_event" [5m]))'),
    ("DAU login 24h", f'count(count by (user_id) (count_over_time({STREAM} | event_type="login_event" | user_id != "" [24h])))'),
    ("DAU tele 24h", f'count(count by (user_id) (count_over_time({STREAM} | event_type="telemetry_event" | user_id != "" [24h])))'),
]

print("=== GRAFANA DATASOURCES ===")
for ds in grafana_ds():
    print(f"  {ds['name']}: {ds['url']}")

print("\n=== LOKI QUERIES ===")
for name, expr in queries:
    try:
        res = loki(expr)
        print(f"  {'OK' if res else 'EMPTY':5} {name}: {str(res)[:120]}")
    except Exception as exc:
        print(f"  FAIL  {name}: {exc}")

print("\n=== DEPLOYED DASHBOARD SECTIONS ===")
dash = grafana_dash()
rows = [p.get("title") for p in dash.get("panels", []) if p.get("type") == "row"]
print(f"  title: {dash.get('title')}")
print(f"  panels: {len(dash.get('panels', []))}")
print(f"  rows: {rows}")

print("\n=== LOKI LABELS / HISTORY ===")
with urllib.request.urlopen(f"{LOKI}/loki/api/v1/labels", timeout=15) as resp:
    labels = json.loads(resp.read()).get("data", [])
print(f"  label count: {len(labels)}")
print(f"  sample: {labels[:12]}")

hist_q = f'sum by (event_type) (count_over_time({STREAM} [7d]))'
try:
    res = loki(hist_q, timeout=90)
    print(f"  events by type (7d): {res}")
except Exception as exc:
    print(f"  history query failed: {exc}")

# Adoption-specific fields (Excel dashboard)
adoption_queries = [
    ("eligible_user_count", f'sum(max by (department) (max_over_time({STREAM} | event_type="telemetry_event" | unwrap eligible_user_count [1h])))'),
    ("is_new_user logins", f'sum(count_over_time({STREAM} | event_type="login_event" | is_new_user="true" [24h]))'),
    ("feature_id adoption", f'count by (feature_id) (count by (user_id, feature_id) (count_over_time({STREAM} | event_type="telemetry_event" | user_id != "" | feature_id != "" [24h])))'),
]
print("\n=== ADOPTION FIELD QUERIES ===")
for name, expr in adoption_queries:
    try:
        res = loki(expr)
        print(f"  {'OK' if res else 'EMPTY':5} {name}: {str(res)[:100]}")
    except Exception as exc:
        print(f"  FAIL  {name}: {exc}")
