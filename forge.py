"""Core Hermes Bot profile provisioning, updating, and rollback for DirtyForge."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from . import acks, compiler, journal, policy
from .sentinel.guard import scan_secrets

BASE_TOOLSETS = ["browser", "clarify", "file", "memory", "session_search", "skills", "todo", "web"]
ALL_TOOLSETS = set(BASE_TOOLSETS) | {
    "code_execution",
    "computer_use",
    "connections",
    "cronjob",
    "delegation",
    "image_gen",
    "terminal",
    "tts",
    "vision",
}
AVATAR_KINDS = ("sun", "cloud", "boxy", "droplet", "star", "leaf")
GENERIC_ROLE_WORDS = {
    "agent",
    "assistant",
    "bot",
    "coder",
    "helper",
    "manager",
    "researcher",
    "social",
    "writer",
}
PROFILE_DIRS = ("memories", "sessions", "skills", "skins", "logs", "plans", "workspace", "cron", "journal", "plugins")


def default_root() -> Path:
    env_home = os.environ.get("HERMES_HOME", "").strip()
    return Path(env_home).expanduser() if env_home else Path.home() / ".hermes"


def profile_dir(root: Path, profile_id: str) -> Path:
    return root if profile_id == "default" else root / "profiles" / profile_id


def slugify_profile(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return slug[:64]


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def save_yaml(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True, indent=2), encoding="utf-8")


def validate_display_name(display_name: str, root: Path) -> tuple[bool, str]:
    clean = (display_name or "").strip()
    if not clean:
        return False, "display_name is required"
    if clean.lower() in GENERIC_ROLE_WORDS:
        return False, f"'{clean}' is a generic role word; choose a character name like Quill, Kairo, or Nova."
    if not clean[0].isupper():
        return False, f"display_name '{clean}' must be Proper Case (e.g. '{clean.capitalize()}')."
    pid = slugify_profile(clean)
    if not pid or pid == "default":
        return False, f"invalid profile id derived from '{clean}'"
    if profile_dir(root, pid).exists():
        return False, f"Bot '{pid}' already exists."
    return True, pid


def _shallow_workspace_survey(roots: list[str] | None = None) -> list[str]:
    targets = [Path(r).expanduser() for r in (roots or []) if r] or [Path.cwd()]
    notes: list[str] = []
    for base in targets[:3]:
        if not base.is_dir():
            continue
        entries = sorted(p.name for p in base.iterdir() if not p.name.startswith("."))[:20]
        notes.append(f"Workspace `{base}` contains: {', '.join(entries) if entries else '(empty)'}.")
        for doc in ("AGENTS.md", "CLAUDE.md", "README.md"):
            doc_path = base / doc
            if doc_path.is_file():
                head = doc_path.read_text(encoding="utf-8", errors="ignore").splitlines()[:8]
                summary = " ".join(line.strip() for line in head if line.strip())[:240]
                if summary:
                    notes.append(f"{base.name}/{doc}: {summary}")
                break
    return notes


def _setup_omh_memory(pdir: Path, mode: str) -> None:
    omh_mode = mode if mode in ("auto-safe", "review-first", "off") else "auto-safe"
    omh_dir = pdir / ".omh"
    (omh_dir / "memory" / "candidates").mkdir(parents=True, exist_ok=True)
    (omh_dir / "memory" / "records").mkdir(parents=True, exist_ok=True)
    (omh_dir / "memory" / "reviews").mkdir(parents=True, exist_ok=True)
    setup_profile = {
        "schema": "project_memory_policy/v1",
        "mode": omh_mode,
        "managed_by": "dirty-forge",
    }
    (omh_dir / "setup-profile.json").write_text(
        json.dumps(setup_profile, indent=2) + "\n", encoding="utf-8"
    )


def _copy_inherited_plugins(root: Path, launch_profile: str, pdir: Path, names: list[str]) -> list[str]:
    copied: list[str] = []
    src_roots = [profile_dir(root, launch_profile) / "plugins", root / "plugins"]
    for name in names:
        if not name or name in ("dirty-forge", "bot-forge"):
            continue
        for src_base in src_roots:
            src = src_base / name
            if src.is_dir() and (src / "plugin.yaml").is_file():
                dst = pdir / "plugins" / name
                if not dst.exists():
                    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(".env*", "*.key", "__pycache__"))
                copied.append(name)
                break
    return copied


def _install_sentinel(pdir: Path) -> None:
    src = Path(__file__).parent / "sentinel"
    dst = pdir / "plugins" / "dirty-forge-sentinel"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))


def _configure_cron(pdir: Path, routines: list[dict[str, Any]]) -> list[dict[str, str]]:
    if not routines:
        return []
    valid: list[dict[str, str]] = []
    for idx, item in enumerate(routines):
        if not isinstance(item, dict):
            continue
        schedule = str(item.get("schedule") or "").strip()
        prompt = str(item.get("prompt") or "").strip()
        name = str(item.get("name") or f"routine-{idx + 1}").strip()
        if schedule and prompt:
            valid.append({"name": name, "schedule": schedule, "prompt": prompt})
    if valid:
        (pdir / "cron" / "jobs.json").write_text(json.dumps(valid, indent=2) + "\n", encoding="utf-8")
    return valid


def _gateway_check(install_gateway: bool) -> str:
    if not install_gateway:
        return "skipped (install_gateway=false)"
    hermes_bin = shutil.which("hermes")
    if not hermes_bin:
        return "pending (hermes CLI not on PATH)"
    try:
        proc = subprocess.run([hermes_bin, "gateway", "status"], capture_output=True, text=True, timeout=5)
        if proc.returncode == 0:
            return "active"
        return "pending (gateway not running)"
    except Exception:
        return "pending (gateway check unavailable)"


def forge_bot(spec: dict[str, Any], settings: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = settings or {}
    root = Path(spec.get("hermes_root") or default_root()).expanduser()
    launch_profile = str(spec.get("launch_profile") or "default").strip() or "default"
    display_name = str(spec.get("display_name") or "").strip()
    role = str(spec.get("role") or "").strip()
    if not role:
        return {"ok": False, "error": "role is required"}

    ok, pid_or_err = validate_display_name(display_name, root)
    if not ok:
        return {"ok": False, "error": pid_or_err}
    pid = pid_or_err
    pdir = profile_dir(root, pid)

    avatar = str(spec.get("avatar_kind") or "boxy").strip().lower()
    if avatar not in AVATAR_KINDS:
        avatar = "boxy"

    try:
        for d in PROFILE_DIRS:
            (pdir / d).mkdir(parents=True, exist_ok=True)

        launch_cfg = load_yaml(profile_dir(root, launch_profile) / "config.yaml")
        model_cfg = spec.get("model")
        if not isinstance(model_cfg, dict) or not model_cfg:
            if settings.get("inherit_model", True) and isinstance(launch_cfg.get("model"), dict):
                model_cfg = dict(launch_cfg["model"])
            elif isinstance(settings.get("fallback_model"), dict) and settings["fallback_model"]:
                model_cfg = dict(settings["fallback_model"])
            else:
                model_cfg = {}

        requested_toolsets = [str(t).strip() for t in (spec.get("toolsets") or []) if str(t).strip() in ALL_TOOLSETS]
        toolsets = sorted(set(BASE_TOOLSETS) | set(requested_toolsets))

        raw_soul, compile_mode = compiler.compile_soul_md(
            display_name=display_name,
            role=role,
            description=str(spec.get("description") or ""),
            one_job=str(spec.get("one_job") or ""),
            soul_md=str(spec.get("soul_md") or ""),
            blueprint_slug=str(spec.get("blueprint_slug") or ""),
            escalate_to=str(spec.get("escalate_to") or "the user"),
            model_cfg=model_cfg,
            allow_llm_fallback=bool(spec.get("allow_llm_fallback", True)),
        )

        canonical_policy_file = policy.ensure_starter_policy(root)
        soul_final = policy.inject_policy(raw_soul, canonical_policy_file.read_text(encoding="utf-8"))
        if settings.get("ack_reactions", True):
            soul_final = acks.inject_acks(soul_final)
        if settings.get("journal_enabled", True):
            soul_final = journal.inject_journal_policy(soul_final)
        (pdir / "SOUL.md").write_text(soul_final, encoding="utf-8")

        omh_mode = str(spec.get("omh_memory_mode") or settings.get("omh_memory_mode") or "auto-safe")
        _setup_omh_memory(pdir, omh_mode)

        inherit_list = spec.get("inherit_plugins")
        if inherit_list is None:
            inherit_list = settings.get("inherit_plugins", ["omh"])
        if not isinstance(inherit_list, list):
            inherit_list = ["omh"]
        enabled_plugins = _copy_inherited_plugins(root, launch_profile, pdir, [str(x) for x in inherit_list])

        if settings.get("enforce_approvals", True):
            _install_sentinel(pdir)
            enabled_plugins.append("dirty-forge-sentinel")

        cfg: dict[str, Any] = {
            "model": model_cfg,
            "toolsets": toolsets,
            "plugins": {"enabled": sorted(set(enabled_plugins))},
            "bots": {
                "title": display_name,
                "role": role,
                "avatar_kind": avatar,
                "hidden": False,
                "managed_by": "dirty-forge",
                "omh_memory_mode": omh_mode,
            },
        }
        if settings.get("enforce_approvals", True):
            cfg["dirty-forge-sentinel"] = {
                "approve_categories": spec.get("approve_categories") or ["send", "spend", "destroy"],
                "limits": spec.get("limits") or {},
            }
        save_yaml(pdir / "config.yaml", cfg)

        # Memory & USER.md
        mem_lines: list[str] = [f"# {display_name} Memory\n"]
        for fact in spec.get("memory") or []:
            fact_s = str(fact).strip()
            if fact_s and not scan_secrets(fact_s):
                mem_lines.append(f"- {fact_s}")
        if settings.get("workspace_survey", True):
            for note in _shallow_workspace_survey(settings.get("workspace_roots")):
                mem_lines.append(f"- {note}")
        mem_lines.append("- Metacognition: update existing memory facts rather than duplicating; record lessons in journal.")
        (pdir / "memories" / "MEMORY.md").write_text("\n".join(mem_lines) + "\n", encoding="utf-8")

        src_user = profile_dir(root, launch_profile) / "memories" / "USER.md"
        if src_user.is_file():
            shutil.copy2(src_user, pdir / "memories" / "USER.md")

        routines = _configure_cron(pdir, spec.get("routines") or [])
        gw_status = _gateway_check(bool(settings.get("install_gateway", True)))

        return {
            "ok": True,
            "name": pid,
            "display_name": display_name,
            "role": role,
            "avatar_kind": avatar,
            "profile_dir": str(pdir),
            "compile_mode": compile_mode,
            "omh_memory_mode": omh_mode,
            "plugins_enabled": cfg["plugins"]["enabled"],
            "toolsets": toolsets,
            "routines": routines,
            "gateway": gw_status,
        }
    except Exception as exc:
        if pdir.exists():
            shutil.rmtree(pdir, ignore_errors=True)
        return {"ok": False, "error": f"provisioning failed and rolled back: {exc}"}


def list_bots(root: Path | None = None, include_hidden: bool = False) -> list[dict[str, Any]]:
    base = (root or default_root()) / "profiles"
    if not base.is_dir():
        return []
    bots: list[dict[str, Any]] = []
    for pdir in sorted(base.iterdir()):
        if not pdir.is_dir():
            continue
        cfg = load_yaml(pdir / "config.yaml")
        meta = cfg.get("bots") if isinstance(cfg.get("bots"), dict) else {}
        hidden = bool(meta.get("hidden", False))
        if hidden and not include_hidden:
            continue
        bots.append(
            {
                "name": pdir.name,
                "display_name": meta.get("title") or pdir.name,
                "role": meta.get("role") or "",
                "avatar_kind": meta.get("avatar_kind") or "boxy",
                "hidden": hidden,
                "omh_memory_mode": meta.get("omh_memory_mode") or "unknown",
                "model": (cfg.get("model") or {}).get("default", ""),
            }
        )
    return bots


def update_bot(name: str, changes: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    r = root or default_root()
    pdir = profile_dir(r, slugify_profile(name))
    if not pdir.is_dir():
        return {"ok": False, "error": f"Bot '{name}' not found"}
    cfg = load_yaml(pdir / "config.yaml")
    bots_meta = cfg.setdefault("bots", {})
    if changes.get("display_name"):
        bots_meta["title"] = str(changes["display_name"]).strip()
    if changes.get("avatar_kind") in AVATAR_KINDS:
        bots_meta["avatar_kind"] = changes["avatar_kind"]
    if isinstance(changes.get("toolsets"), list):
        valid = {str(t).strip() for t in changes["toolsets"] if str(t).strip() in ALL_TOOLSETS}
        cfg["toolsets"] = sorted(set(BASE_TOOLSETS) | valid)
    save_yaml(pdir / "config.yaml", cfg)

    soul_path = pdir / "SOUL.md"
    if changes.get("soul_append") and soul_path.is_file():
        current = soul_path.read_text(encoding="utf-8")
        soul_path.write_text(current.rstrip() + "\n\n" + str(changes["soul_append"]).strip() + "\n", encoding="utf-8")
    return {"ok": True, "name": pdir.name}


def hide_bot(name: str, hidden: bool = True, root: Path | None = None) -> dict[str, Any]:
    r = root or default_root()
    pdir = profile_dir(r, slugify_profile(name))
    if not pdir.is_dir():
        return {"ok": False, "error": f"Bot '{name}' not found"}
    cfg = load_yaml(pdir / "config.yaml")
    cfg.setdefault("bots", {})["hidden"] = bool(hidden)
    save_yaml(pdir / "config.yaml", cfg)
    return {"ok": True, "name": pdir.name, "hidden": bool(hidden)}


def delete_bot(name: str, settings: dict[str, Any] | None = None, root: Path | None = None) -> dict[str, Any]:
    settings = settings or {}
    if not settings.get("allow_delete", False):
        return {"ok": False, "error": "delete_bot is disabled (set allow_delete: true in plugin config)"}
    r = root or default_root()
    pid = (name or "").strip()
    pdir = profile_dir(r, pid)
    if pid == "default" or not pdir.is_dir():
        return {"ok": False, "error": f"Bot '{pid}' not found"}

    backup_path = ""
    if settings.get("backup_before_delete", True):
        backups = r / "backups"
        backups.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        archive = backups / f"{pid}-{stamp}.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(pdir, arcname=pid)
        backup_path = str(archive)

    shutil.rmtree(pdir)
    return {"ok": True, "deleted": pid, "backup": backup_path}
