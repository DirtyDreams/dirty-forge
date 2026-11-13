"""Tool handlers for DirtyForge."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from . import blueprints, compiler, forge, journal, policy


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def search_blueprints(args: dict[str, Any], **kwargs: Any) -> str:
    query = str(args.get("query") or "").strip()
    if not query:
        return _json({"ok": False, "error": "query is required"})
    division = str(args.get("division") or "").strip()
    limit = int(args.get("limit") or 5)
    hits = blueprints.search(query, division=division, limit=limit)
    pack = compiler.build_metaprompt_pack(query, blueprint_slug=hits[0]["slug"] if hits else "")
    return _json({"ok": True, "matches": hits, "metaprompt_pack": pack})


def create_bot(args: dict[str, Any], settings: dict[str, Any] | None = None, **kwargs: Any) -> str:
    spec = dict(args or {})
    if "launch_profile" not in spec:
        spec["launch_profile"] = os.environ.get("HERMES_PROFILE", "default")
    return _json(forge.forge_bot(spec, settings=settings))


def list_bots(args: dict[str, Any], **kwargs: Any) -> str:
    include_hidden = bool((args or {}).get("include_hidden", False))
    bots = forge.list_bots(include_hidden=include_hidden)
    return _json({"ok": True, "count": len(bots), "bots": bots})


def update_bot(args: dict[str, Any], **kwargs: Any) -> str:
    name = str((args or {}).get("name") or "").strip()
    if not name:
        return _json({"ok": False, "error": "name is required"})
    return _json(forge.update_bot(name, args or {}))


def check_bots(args: dict[str, Any], **kwargs: Any) -> str:
    root = forge.default_root()
    bots = forge.list_bots(root=root, include_hidden=True)
    report: list[dict[str, Any]] = []
    for bot in bots:
        pdir = forge.profile_dir(root, bot["name"])
        drift = policy.check_drift(root, pdir)
        omh_cfg = pdir / ".omh" / "setup-profile.json"
        sentinel_dir = pdir / "plugins" / "dirty-forge-sentinel"
        report.append(
            {
                "name": bot["name"],
                "display_name": bot["display_name"],
                "policy_in_sync": drift["in_sync"],
                "policy_reason": drift["reason"],
                "omh_configured": omh_cfg.is_file(),
                "omh_memory_mode": bot["omh_memory_mode"],
                "sentinel_installed": sentinel_dir.is_dir(),
            }
        )
    return _json({"ok": True, "count": len(report), "bots": report})


def agent_journal(args: dict[str, Any], **kwargs: Any) -> str:
    action = str((args or {}).get("action") or "").strip().lower()
    target = str((args or {}).get("name") or os.environ.get("HERMES_PROFILE") or "default").strip()
    pdir = forge.profile_dir(forge.default_root(), forge.slugify_profile(target) if target != "default" else "default")
    if not pdir.is_dir():
        return _json({"ok": False, "error": f"profile '{target}' not found"})
    if action == "write":
        return _json(
            journal.write_entry(
                pdir,
                status=str(args.get("status") or ""),
                goal=str(args.get("goal") or ""),
                outcome=str(args.get("outcome") or ""),
                evidence=str(args.get("evidence") or ""),
                next_step=str(args.get("next_step") or ""),
            )
        )
    if action == "read":
        return _json(journal.read_entries(pdir, date=str(args.get("date") or ""), limit=int(args.get("limit") or 20)))
    return _json({"ok": False, "error": "action must be 'write' or 'read'"})


def ask_bot(args: dict[str, Any], **kwargs: Any) -> str:
    name = forge.slugify_profile(str((args or {}).get("name") or ""))
    question = str((args or {}).get("question") or "").strip()
    if not name or not question:
        return _json({"ok": False, "error": "name and question are required"})
    pdir = forge.profile_dir(forge.default_root(), name)
    if not pdir.is_dir():
        return _json({"ok": False, "error": f"Bot '{name}' not found"})
    hermes_bin = shutil.which("hermes")
    if not hermes_bin:
        return _json({"ok": False, "error": "hermes CLI not found on PATH"})
    try:
        proc = subprocess.run(
            [hermes_bin, "-p", name, "chat", "-q", question],
            capture_output=True,
            text=True,
            timeout=120,
        )
        reply = (proc.stdout or proc.stderr or "").strip()
        return _json({"ok": proc.returncode == 0, "name": name, "reply": reply[-6000:]})
    except Exception as exc:
        return _json({"ok": False, "error": f"failed asking '{name}': {exc}"})


def hide_bot(args: dict[str, Any], **kwargs: Any) -> str:
    name = str((args or {}).get("name") or "").strip()
    hidden = bool((args or {}).get("hidden", True))
    return _json(forge.hide_bot(name, hidden=hidden))


def delete_bot(args: dict[str, Any], settings: dict[str, Any] | None = None, **kwargs: Any) -> str:
    name = str((args or {}).get("name") or "").strip()
    return _json(forge.delete_bot(name, settings=settings))
