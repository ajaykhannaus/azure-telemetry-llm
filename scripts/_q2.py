import json, base64, urllib.request

G = "http://localhost:3001"
A = base64.b64encode(b"admin:admin").decode()
q = 'count(count by (user_id) (count_over_time({service_name=~".+"} | json | event_type="login_event" | user_id != "" [24h])))'
body = {
    "queries": [{
        "refId": "A",
        "datasource": {"type": "loki", "uid": "loki-ds"},
        "expr": q,
        "queryType": "range",
    }],
    "from": "now-6h",
    "to": "now",
}
req = urllib.request.Request(
    G + "/api/ds/query", data=json.dumps(body).encode(), method="POST",
    headers={"Content-Type": "application/json", "Authorization": f"Basic {A}"},
)
try:
    urllib.request.urlopen(req, timeout=60)
    print("PASS")
except urllib.error.HTTPError as e:
    print(e.read().decode()[:500])
