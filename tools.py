"""Tool handlers for DirtyForge."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any

from . import blueprints, compiler, evals, forge, handoff, intake, journal, omh_memory, policy, portable, takeover, team
from .sentinel import guard, telemetry


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


def rollback_bot(args: dict[str, Any], **kwargs: Any) -> str:
    name = str((args or {}).get("name") or "").strip()
    if not name:
        return _json({"ok": False, "error": "name is required"})
    return _json(forge.rollback_bot(name, stamp=str((args or {}).get("stamp") or "last")))


def check_bots(args: dict[str, Any], **kwargs: Any) -> str:
    root = forge.default_root()
    bots = forge.list_bots(root=root, include_hidden=True)
    report: list[dict[str, Any]] = []
    for bot in bots:
        pdir = forge.profile_dir(root, bot["name"])
        drift = policy.check_drift(root, pdir)
        omh_cfg = pdir / ".omh" / "setup-profile.json"
        sentinel_dir = pdir / "plugins" / "dirty-forge-sentinel"
        metrics = telemetry._load_state(pdir)
        report.append(
            {
                "name": bot["name"],
                "display_name": bot["display_name"],
                "role": "builder" if policy.is_builder(root, pdir) else "bot",
                "policy_in_sync": drift["in_sync"],
                "policy_reason": drift["reason"],
                "omh_configured": omh_cfg.is_file(),
                "omh_memory_mode": bot["omh_memory_mode"],
                "sentinel_installed": sentinel_dir.is_dir(),
                "telemetry": {
                    "total_calls": metrics.get("total_calls", 0),
                    "consecutive_errors": metrics.get("consecutive_errors", 0),
                    "breaker_tripped": metrics.get("breaker_tripped", False),
                },
            }
        )
    return _json({"ok": True, "count": len(report), "bots": report})


def agent_journal(args: dict[str, Any], **kwargs: Any) -> str:
    action = str((args or {}).get("action") or "").strip().lower()
    caller = os.environ.get("HERMES_PROFILE", "").strip().lower()
    target = str((args or {}).get("name") or caller or "default").strip()
    ok_id, pid_or_err = forge.validate_profile_id(target, allow_default=True)
    if not ok_id:
        return _json({"ok": False, "error": pid_or_err})
    target_pid = pid_or_err
    if action == "write" and caller and caller != "default" and target_pid != caller:
        return _json({"ok": False, "error": f"cross-bot journal writes are forbidden (caller '{caller}' cannot write to '{target_pid}')"})
    pdir = forge.profile_dir(forge.default_root(), target_pid)
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
    sec = guard.scan_secrets(question)
    if sec:
        return _json({"ok": False, "error": f"ask_bot blocked: secret pattern detected ({', '.join(sec)})"})
    inj = guard.scan_prompt_injection(question)
    if inj:
        return _json({"ok": False, "error": f"ask_bot blocked: prompt injection pattern detected ({', '.join(inj)})"})
    root = forge.default_root()
    pdir = forge.profile_dir(root, name)
    if not pdir.is_dir():
        return _json({"ok": False, "error": f"Bot '{name}' not found"})
    hermes_bin = shutil.which("hermes")
    if not hermes_bin:
        return _json({"ok": False, "error": "hermes CLI not found on PATH"})
    timeout_sec = max(30.0, forge.core_tool_deadline(root) - forge.DEADLINE_MARGIN)
    try:
        proc = subprocess.run(
            [hermes_bin, "-p", name, "chat", "-q", question],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
        reply = (proc.stdout or proc.stderr or "").strip()
        return _json({"ok": proc.returncode == 0, "name": name, "reply": reply[-6000:]})
    except subprocess.TimeoutExpired:
        return _json({"ok": False, "error": f"ask_bot timed out after {timeout_sec:.0f}s"})
    except Exception as exc:
        return _json({"ok": False, "error": f"failed asking '{name}': {exc}"})


def hide_bot(args: dict[str, Any], **kwargs: Any) -> str:
    name = str((args or {}).get("name") or "").strip()
    hidden = bool((args or {}).get("hidden", True))
    return _json(forge.hide_bot(name, hidden=hidden))


def delete_bot(args: dict[str, Any], settings: dict[str, Any] | None = None, **kwargs: Any) -> str:
    name = str((args or {}).get("name") or "").strip()
    return _json(forge.delete_bot(name, settings=settings))


def create_team(args: dict[str, Any], settings: dict[str, Any] | None = None, **kwargs: Any) -> str:
    spec = dict(args or {})
    if "launch_profile" not in spec:
        spec["launch_profile"] = os.environ.get("HERMES_PROFILE", "default")
    return _json(team.build_team(spec, settings=settings))


def handoff_bot(args: dict[str, Any], settings: dict[str, Any] | None = None, **kwargs: Any) -> str:
    spec = dict(args or {})
    if "from" not in spec:
        spec["from"] = os.environ.get("HERMES_PROFILE", "default")
    return _json(handoff.handoff_bot(spec, settings=settings))


def copy_bot(args: dict[str, Any], settings: dict[str, Any] | None = None, **kwargs: Any) -> str:
    return _json(
        portable.copy_bot(
            source_name=str((args or {}).get("source") or ""),
            new_display_name=str((args or {}).get("display_name") or ""),
            role=str((args or {}).get("role") or ""),
            settings=settings,
        )
    )


def teach_bot(args: dict[str, Any], **kwargs: Any) -> str:
    return _json(
        portable.teach_bot(
            name=str((args or {}).get("name") or ""),
            skill_name=str((args or {}).get("skill_name") or ""),
            skill_md=str((args or {}).get("skill_md") or ""),
        )
    )


def share_bot(args: dict[str, Any], settings: dict[str, Any] | None = None, **kwargs: Any) -> str:
    allow_secrets = bool((settings or {}).get("allow_secrets", False))
    return _json(
        portable.share_bot(
            name=str((args or {}).get("name") or ""),
            mode=str((args or {}).get("mode") or "template"),
            out_path=str((args or {}).get("out_path") or ""),
            allow_secrets=allow_secrets,
        )
    )


def import_bot(args: dict[str, Any], settings: dict[str, Any] | None = None, **kwargs: Any) -> str:
    allow_secrets = bool((settings or {}).get("allow_secrets", False))
    return _json(
        portable.import_bot(
            source_path=str((args or {}).get("source_path") or ""),
            display_name=str((args or {}).get("display_name") or ""),
            allow_secrets=allow_secrets,
            settings=settings,
        )
    )


def sync_policies(args: dict[str, Any], **kwargs: Any) -> str:
    root = forge.default_root()
    bots = forge.list_bots(root=root, include_hidden=True)
    dirs = [forge.profile_dir(root, b["name"]) for b in bots]
    return _json(policy.sync_policies(root, dirs))


def omh_review(args: dict[str, Any], **kwargs: Any) -> str:
    return _json(
        omh_memory.review_omh(
            name=str((args or {}).get("name") or ""),
            action=str((args or {}).get("action") or "list"),
            candidate_id=str((args or {}).get("candidate_id") or ""),
        )
    )


def fit_test(args: dict[str, Any], **kwargs: Any) -> str:
    return _json(
        evals.fit_test(
            goal=str((args or {}).get("goal") or ""),
            recurring=bool((args or {}).get("recurring", False)),
            needs_separate_state_or_config=bool((args or {}).get("needs_separate_state_or_config", False)),
            multiple_distinct_roles=bool((args or {}).get("multiple_distinct_roles", False)),
        )
    )


def eval_bot(args: dict[str, Any], **kwargs: Any) -> str:
    return _json(
        evals.eval_bot(
            name=str((args or {}).get("name") or ""),
            cases=list((args or {}).get("cases") or []),
        )
    )


def activate_bot(args: dict[str, Any], **kwargs: Any) -> str:
    return _json(
        forge.activate_bot(
            name=str((args or {}).get("name") or ""),
            force=bool((args or {}).get("force", False)),
        )
    )


def request_takeover(args: dict[str, Any], **kwargs: Any) -> str:
    return _json(
        takeover.request_takeover(
            name=str((args or {}).get("name") or ""),
            reason=str((args or {}).get("reason") or ""),
            context=str((args or {}).get("context") or ""),
        )
    )


def delegate_outside(args: dict[str, Any], settings: dict[str, Any] | None = None, **kwargs: Any) -> str:
    return _json(
        takeover.delegate_outside(
            cli=str((args or {}).get("cli") or ""),
            task=str((args or {}).get("task") or ""),
            cwd=str((args or {}).get("cwd") or ""),
            settings=settings,
        )
    )


def bot_metrics(args: dict[str, Any], **kwargs: Any) -> str:
    name = str((args or {}).get("name") or "").strip()
    ok_id, pid_or_err = forge.validate_profile_id(name, allow_default=False)
    if not ok_id:
        return _json({"ok": False, "error": pid_or_err})
    pdir = forge.profile_dir(forge.default_root(), pid_or_err)
    if not pdir.is_dir():
        return _json({"ok": False, "error": f"Bot '{name}' not found"})
    if bool((args or {}).get("reset_breaker", False)):
        state = telemetry.reset_breaker(pdir)
        return _json({"ok": True, "bot": pid_or_err, "reset": True, "metrics": state})
    return _json({"ok": True, "bot": pid_or_err, "metrics": telemetry.get_metrics(pdir)})


def interview(args: dict[str, Any], **kwargs: Any) -> str:
    return _json(
        intake.run_interview(
            intake_id=str((args or {}).get("intake_id") or ""),
            answers=(args or {}).get("answers") if isinstance((args or {}).get("answers"), dict) else {},
            include_optional=bool((args or {}).get("include_optional", True)),
        )
    )
