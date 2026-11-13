"""Diagnostic CLI and health report for DirtyForge."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from . import forge, policy


def run_doctor(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    root = forge.default_root()
    bots = forge.list_bots(root=root, include_hidden=True)
    blueprints_file = Path(__file__).parent / "data" / "blueprints.json"
    bp_count = len(json.loads(blueprints_file.read_text(encoding="utf-8"))) if blueprints_file.is_file() else 0
    drift_count = sum(1 for b in bots if not policy.check_drift(root, forge.profile_dir(root, b["name"]))["in_sync"])
    return {
        "ok": True,
        "hermes_root": str(root),
        "hermes_cli": shutil.which("hermes") or "not found",
        "blueprints_indexed": bp_count,
        "bots_total": len(bots),
        "policy_drifted_bots": drift_count,
        "settings": settings or {},
    }


def cli(args: Any, settings: dict[str, Any] | None = None) -> int:
    report = run_doctor(settings=settings)
    if getattr(args, "json", False):
        print(json.dumps(report, indent=2))
    else:
        print(f"DirtyForge Doctor — root: {report['hermes_root']}")
        print(f"  hermes CLI:        {report['hermes_cli']}")
        print(f"  blueprints:        {report['blueprints_indexed']}")
        print(f"  bots provisioned:  {report['bots_total']} (policy drift: {report['policy_drifted_bots']})")
    return 0
