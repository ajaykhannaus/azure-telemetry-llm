#!/usr/bin/env python3
import base64
import json
import pathlib
import urllib.request

AUTH = base64.b64encode(b"admin:admin").decode()


def fetch_deployed():
    req = urllib.request.Request(
        "http://localhost:3001/api/dashboards/uid/ai-telemetry-users",
        headers={"Authorization": f"Basic {AUTH}"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())["dashboard"]


def main():
    local = json.loads(
        pathlib.Path("dashboards/05-user-observability.json").read_text(encoding="utf-8")
    )
    deployed = fetch_deployed()
    for label, dash in [("LOCAL", local), ("DEPLOYED", deployed)]:
        print(f"=== {label} ===")
        in_adoption = False
        for p in dash["panels"]:
            if p.get("type") == "row":
                if in_adoption:
                    in_adoption = False
                if p.get("title") == "Adoption":
                    in_adoption = True
                kids = p.get("panels") or []
                print(
                    f"  {p.get('title')!r}: nested={len(kids)} "
                    f"collapsed={p.get('collapsed')}"
                )
            elif in_adoption:
                print(f"  + flat: {p.get('title')!r}")


if __name__ == "__main__":
    main()
