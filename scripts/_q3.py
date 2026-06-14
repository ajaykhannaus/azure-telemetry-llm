import json, base64, urllib.request

G = "http://localhost:3001"
A = base64.b64encode(b"admin:admin").decode()

for label, q in [
    ("DAU 1h", 'count(count by (user_id) (count_over_time({service_name=~".+"} | json | event_type="login_event" | user_id != "" [1h])))'),
    ("logins 5m rate", 'sum(count_over_time({service_name=~".+"} | json | event_type="login_event" [5m]))'),
]:
    body = {"queries": [{"refId": "A", "datasource": {"type": "loki", "uid": "loki-ds"}, "expr": q, "queryType": "range"}], "from": "now-6h", "to": "now"}
    req = urllib.request.Request(G + "/api/ds/query", data=json.dumps(body).encode(), method="POST", headers={"Content-Type": "application/json", "Authorization": f"Basic {A}"})
    try:
        r = urllib.request.urlopen(req, timeout=45)
        frames = json.loads(r.read())["results"]["A"].get("frames") or []
        print(label, "PASS" if frames else "NO_DATA")
    except Exception as e:
        print(label, str(e)[:120])
