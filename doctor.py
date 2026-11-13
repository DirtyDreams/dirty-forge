"""Diagnostic CLI and health report for DirtyForge."""
from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path
from typing import Any

from . import forge, policy


def _detect_pre_tool_call_blocking() -> tuple[str, str | None]:
    """Check if the installed Hermes runtime honors pre_tool_call return directives."""
    try:
        spec = importlib.util.find_spec("model_tools")
        if spec and spec.origin:
            src = Path(spec.origin).read_text(encoding="utf-8", errors="ignore")
            if 'invoke_hook(\n                "pre_tool_call"' in src or 'invoke_hook("pre_tool_call"' in src:
                if "action" in src and "block" in src:
                    return "supported", None
                return (
                    "advisory_only",
                    "Hermes runtime ignores pre_tool_call return values; DirtyForge enforces hard restrictions via Bot toolset whitelists in config.yaml.",
                )
    except Exception:
        pass
    return (
        "unknown",
        "Could not inspect Hermes model_tools; verify whether pre_tool_call return values block execution or rely on toolset whitelists.",
    )


def run_doctor(settings: dict[str, Any] | None = None) -> dict[str, Any]:
    root = forge.default_root()
    bots = forge.list_bots(root=root, include_hidden=True)
    blueprints_file = Path(__file__).parent / "data" / "blueprints.json"
    bp_count = len(json.loads(blueprints_file.read_text(encoding="utf-8"))) if blueprints_file.is_file() else 0
    drift_count = sum(1 for b in bots if not policy.check_drift(root, forge.profile_dir(root, b["name"]))["in_sync"])
    omh_installed = (root / "plugins" / "omh" / "plugin.yaml").is_file()
    blocking_status, blocking_warning = _detect_pre_tool_call_blocking()
    warnings: list[str] = []
    if blocking_warning:
        warnings.append(blocking_warning)
    return {
        "ok": True,
        "hermes_root": str(root),
        "hermes_cli": shutil.which("hermes") or "not found",
        "omh_plugin_installed": omh_installed,
        "pre_tool_call_blocking": blocking_status,
        "blueprints_indexed": bp_count,
        "bots_total": len(bots),
        "policy_drifted_bots": drift_count,
        "warnings": warnings,
        "settings": settings or {},
    }


def cli(args: Any, settings: dict[str, Any] | None = None) -> int:
    report = run_doctor(settings=settings)
    if getattr(args, "json", False):
        print(json.dumps(report, indent=2))
    else:
        print(f"DirtyForge Doctor — root: {report['hermes_root']}")
        print(f"  hermes CLI:        {report['hermes_cli']}")
        print(f"  omh plugin:        {'installed' if report['omh_plugin_installed'] else 'not found in root plugins'}")
        print(f"  sentinel blocking: {report['pre_tool_call_blocking']}")
        print(f"  blueprints:        {report['blueprints_indexed']}")
        print(f"  bots provisioned:  {report['bots_total']} (policy drift: {report['policy_drifted_bots']})")
        for w in report["warnings"]:
            print(f"  WARNING:           {w}")
    return 0
