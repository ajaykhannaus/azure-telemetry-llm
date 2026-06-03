#!/usr/bin/env python3
"""Bake pinned datasource UIDs into dashboard JSON for Grafana file provisioning."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from setup_grafana_local import (  # noqa: E402
    _dashboard_files,
    _patch_legacy_dashboard,
    _patch_modern_dashboard,
    _strip_export_metadata,
)

PROM_UID = "prometheus-ds"
LOKI_UID = "loki-ds"
TEMPO_UID = "tempo-ds"


def bake_file(src: Path, dest: Path) -> None:
    dash = json.loads(src.read_text())
    _strip_export_metadata(dash)
    if src.name == "grafana_dashboard.json":
        _patch_legacy_dashboard(dash, PROM_UID, LOKI_UID, TEMPO_UID)
    else:
        _patch_modern_dashboard(dash, PROM_UID, LOKI_UID, TEMPO_UID)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(dash, indent=2) + "\n")
    print(f"  baked {src.name} → {dest}")


def main() -> None:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dashboards" / "baked"
    out_dir.mkdir(parents=True, exist_ok=True)
    for src in _dashboard_files():
        bake_file(src, out_dir / src.name)
    print(f"Done — {len(_dashboard_files())} dashboards in {out_dir}")


if __name__ == "__main__":
    main()
