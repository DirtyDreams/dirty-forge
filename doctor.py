"""Diagnostic CLI and health report for DirtyForge."""
from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path
from typing import Any

from . import forge, policy
from .sentinel import telemetry


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
    pkg_dir = Path(__file__).parent
    blueprints_file = pkg_dir / "data" / "blueprints.json"
    bp_count = len(json.loads(blueprints_file.read_text(encoding="utf-8"))) if blueprints_file.is_file() else 0
    drift_count = 0
    tripped_breakers = 0
    pending_takeovers = 0
    for b in bots:
        pdir = forge.profile_dir(root, b["name"])
        if not policy.check_drift(root, pdir)["in_sync"]:
            drift_count += 1
        if telemetry.get_metrics(pdir).get("breaker_tripped"):
            tripped_breakers += 1
        tdir = pdir / "takeovers"
        if tdir.is_dir():
            for tf in tdir.glob("*.json"):
                try:
                    if json.loads(tf.read_text(encoding="utf-8")).get("status") == "pending_human":
                        pending_takeovers += 1
                except Exception:
                    continue

    intake_dir = root / "intake"
    intake_sessions = len(list(intake_dir.glob("*.json"))) if intake_dir.is_dir() else 0
    omh_installed = (root / "plugins" / "omh" / "plugin.yaml").is_file()
    blocking_status, blocking_warning = _detect_pre_tool_call_blocking()
    warnings: list[str] = []
    if blocking_warning:
        warnings.append(blocking_warning)
    if tripped_breakers:
        warnings.append(f"{tripped_breakers} Bot(s) have a tripped circuit breaker.")
    if pending_takeovers:
        warnings.append(f"{pending_takeovers} Bot takeover request(s) awaiting human review.")
    return {
        "ok": True,
        "hermes_root": str(root),
        "hermes_cli": shutil.which("hermes") or "not found",
        "omh_plugin_installed": omh_installed,
        "pre_tool_call_blocking": blocking_status,
        "blueprints_indexed": bp_count,
        "bots_total": len(bots),
        "policy_drifted_bots": drift_count,
        "tripped_breakers": tripped_breakers,
        "pending_takeovers": pending_takeovers,
        "intake_sessions": intake_sessions,
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
        print(f"  bots provisioned:  {report['bots_total']} (policy drift: {report['policy_drifted_bots']}, tripped: {report['tripped_breakers']}, takeovers: {report['pending_takeovers']})")
        print(f"  intake sessions:   {report['intake_sessions']}")
        for w in report["warnings"]:
            print(f"  WARNING:           {w}")
    return 0
