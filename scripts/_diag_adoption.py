#!/usr/bin/env python3
import base64
import json
import urllib.parse
import urllib.request

LOKI = "http://localhost:3100"
GRAFANA = "http://localhost:3001"
AUTH = base64.b64encode(b"admin:admin").decode()


def loki(q: str) -> str:
    body = f"query={urllib.parse.quote(q, safe='')}"
    req = urllib.request.Request(
        f"{LOKI}/loki/api/v1/query", data=body.encode(), method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read())
    if data.get("status") != "success":
        return f"status={data.get('status')}"
    res = data.get("data", {}).get("result") or []
    if not res:
        return "EMPTY"
    return str(res[0].get("value", res[0]))[:120]


def grafana_panel(expr: str, ptype: str = "stat") -> str:
    instant = ptype in ("stat", "gauge", "barchart", "piechart", "treemap")
    body = {
        "queries": [{
            "refId": "A",
            "datasource": {"type": "loki", "uid": "loki-ds"},
            "expr": expr,
            "queryType": "instant" if instant else "range",
            **({"instant": True} if instant else {}),
        }],
        "from": "now-6h",
        "to": "now",
    }
    req = urllib.request.Request(
        f"{GRAFANA}/api/ds/query", data=json.dumps(body).encode(), method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Basic {AUTH}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            res = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()[:200]
        return f"HTTP {exc.code}: {body}"
    err = res.get("results", {}).get("A", {}).get("error")
    if err:
        return f"ERROR: {err[:160]}"
    for frame in res.get("results", {}).get("A", {}).get("frames") or []:
        for col in frame.get("data", {}).get("values") or []:
            if any(v is not None for v in col):
                return "PASS"
    return "NO_DATA"


def dash_adoption() -> None:
    req = urllib.request.Request(
        f"{GRAFANA}/api/dashboards/uid/ai-telemetry-users",
        headers={"Authorization": f"Basic {AUTH}"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        dash = json.loads(resp.read())["dashboard"]
    for p in dash.get("panels", []):
        if p.get("type") == "row" and p.get("title") == "Adoption":
            kids = p.get("panels") or []
            print(f"Adoption row: collapsed={p.get('collapsed')} child_panels={len(kids)}")
            for k in kids:
                t = k.get("targets", [{}])[0]
                print(f"  - {k.get('title')} ({k.get('type')}) queryType={t.get('queryType')} instant={t.get('instant')}")


if __name__ == "__main__":
    print("=== Loki direct ===")
    tests = [
        ("logins 5m", 'sum(count_over_time({service_name=~".+"} | json | event_type="login_event" [5m]))'),
        ("DAU", 'count(count by (user_id) (count_over_time({service_name=~".+"} | json | event_type="login_event" | user_id != "" [24h])))'),
        ("eligible 1h sum", 'sum(max by (department) (max_over_time({service_name=~".+"} | json | event_type="telemetry_event" | unwrap eligible_user_count [1h])))'),
    ]
    for name, q in tests:
        try:
            print(f"  {name}: {loki(q)}")
        except Exception as e:
            print(f"  {name}: FAIL {e}")

    print("\n=== Grafana datasource ===")
    req = urllib.request.Request(
        f"{GRAFANA}/api/datasources/name/Loki",
        headers={"Authorization": f"Basic {AUTH}"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        ds = json.loads(resp.read())
    print(f"  Loki URL: {ds.get('url')}")

    print("\n=== Grafana query (instant stat) ===")
    eligible = 'sum(max by (department) (max_over_time({service_name=~".+"} | json | event_type="telemetry_event" | unwrap eligible_user_count [1h])))'
    dau = 'count(count by (user_id) (count_over_time({service_name=~".+"} | json | event_type="login_event" | user_id != "" [24h])))'
    adoption = f'({dau} / ({eligible} or on() vector(1))) * 100'
    print(f"  Adoption Rate instant: {grafana_panel(adoption, 'stat')}")
    print(f"  Adoption Rate range:   {grafana_panel(adoption, 'timeseries')}")

    print("\n=== Live dashboard Adoption row ===")
    try:
        dash_adoption()
    except Exception as e:
        print(f"  FAIL {e}")
