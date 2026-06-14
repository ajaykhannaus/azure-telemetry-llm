import urllib.parse, urllib.request, json
q='sum(count_over_time({service_name=~".+"} | json | event_type="telemetry_event" | eligible_user_count > 0 [24h]))'
body='query='+urllib.parse.quote(q,safe='')
r=urllib.request.urlopen(urllib.request.Request('http://localhost:3100/loki/api/v1/query',data=body.encode(),method='POST',headers={'Content-Type':'application/x-www-form-urlencoded'}),timeout=20)
print(json.loads(r.read()))
