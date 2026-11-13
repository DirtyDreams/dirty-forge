"""Core Hermes Bot profile provisioning, updating, and rollback for DirtyForge."""
from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None  # type: ignore[assignment]

import yaml

from . import acks, compiler, intake, journal, policy
from .sentinel.guard import scan_prompt_injection, scan_secrets

BASE_TOOLSETS = ["browser", "clarify", "file", "memory", "session_search", "skills", "todo", "web"]
ALL_TOOLSETS = set(BASE_TOOLSETS) | {
    "code_execution",
    "computer_use",
    "connections",
    "cronjob",
    "delegation",
    "image_gen",
    "messaging",
    "terminal",
    "tts",
    "vision",
}
RESTRICTED_CATEGORY_TOOLSETS: dict[str, set[str]] = {
    "send": {"messaging", "connections"},
    "destroy": {"terminal", "code_execution", "computer_use"},
}
VALID_PROFILE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
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
CORE_TOOL_DEADLINE = 420.0
DEADLINE_MARGIN = 20.0


def core_tool_deadline(root: Path | None = None) -> float:
    try:
        cfg = load_yaml((root or default_root()) / "config.yaml")
        node = (cfg.get("timeouts") or {}).get("tools") or {}
        raw = node.get("sequential_call", node.get("concurrent_call"))
        if raw is not None and not isinstance(raw, bool):
            val = float(raw)
            if val == val and val > 0:
                return val
    except Exception:
        pass
    return CORE_TOOL_DEADLINE


def default_root() -> Path:
    env_home = os.environ.get("HERMES_HOME", "").strip()
    return Path(env_home).expanduser() if env_home else Path.home() / ".hermes"


def validate_profile_id(name: str, allow_default: bool = False) -> tuple[bool, str]:
    clean = (name or "").strip().lower()
    if allow_default and clean == "default":
        return True, "default"
    if not clean or clean == "default" or not VALID_PROFILE_ID_RE.match(clean):
        return False, f"invalid profile id '{name}': must match ^[a-z0-9][a-z0-9_-]{{0,63}}$"
    return True, clean


def profile_dir(root: Path, profile_id: str) -> Path:
    ok, clean = validate_profile_id(profile_id, allow_default=True)
    if not ok:
        raise ValueError(clean)
    if clean == "default":
        return root
    base = (root / "profiles").resolve()
    target = (base / clean).resolve()
    if base not in target.parents:
        raise ValueError(f"path traversal rejected for profile '{profile_id}'")
    return root / "profiles" / clean


def slugify_profile(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return slug[:64]


@contextlib.contextmanager
def _profile_lock(root: Path, pid: str) -> Iterator[None]:
    locks_dir = root / ".locks"
    locks_dir.mkdir(parents=True, exist_ok=True)
    lock_path = locks_dir / f"{pid}.lock"
    with lock_path.open("w", encoding="utf-8") as fh:
        if fcntl is not None:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _filter_restricted_toolsets(
    requested: list[str],
    enforce_approvals: bool,
    approve_categories: list[str],
    allow_restricted: bool,
) -> tuple[list[str], list[str]]:
    if not enforce_approvals or allow_restricted:
        return requested, []
    blocked_pool: set[str] = set()
    for cat in approve_categories:
        cat_l = str(cat).strip().lower()
        for key, toolsets in RESTRICTED_CATEGORY_TOOLSETS.items():
            if key in cat_l:
                blocked_pool |= toolsets
    allowed = [t for t in requested if t not in blocked_pool]
    withheld = [t for t in requested if t in blocked_pool]
    return allowed, withheld


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


def _configure_cron(
    pdir: Path, pid: str, routines: list[dict[str, Any]], draft: bool = False
) -> list[dict[str, Any]]:
    if not routines:
        return []
    hermes_bin = shutil.which("hermes")
    valid: list[dict[str, Any]] = []
    now_iso = datetime.now(timezone.utc).isoformat()
    for idx, item in enumerate(routines):
        if not isinstance(item, dict):
            continue
        schedule = str(item.get("schedule") or "").strip()
        prompt = str(item.get("prompt") or "").strip()
        name = str(item.get("name") or f"routine-{idx + 1}").strip()
        if not (schedule and prompt):
            continue
        entry: dict[str, Any] = {
            "id": f"{pid}-{idx + 1}",
            "name": name,
            "schedule": schedule,
            "prompt": prompt,
            "enabled": not draft,
            "created_at": now_iso,
        }
        if hermes_bin and not draft:
            try:
                proc = subprocess.run(
                    [hermes_bin, "-p", pid, "cron", "add", schedule, prompt, "--name", name],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                m = re.search(r"Created job:\s*([A-Za-z0-9_.-]+)", proc.stdout or "")
                if m:
                    entry["hermes_job_id"] = m.group(1)
            except Exception:
                pass
        valid.append(entry)
    if valid and not (pdir / "cron" / "jobs.json").exists():
        (pdir / "cron" / "jobs.json").write_text(json.dumps(valid, indent=2) + "\n", encoding="utf-8")
    return valid


def _remove_cron_jobs(pid: str, routines: list[dict[str, Any]]) -> None:
    hermes_bin = shutil.which("hermes")
    if not hermes_bin or not routines:
        return
    for entry in routines:
        job_id = str(entry.get("hermes_job_id") or "").strip()
        if not job_id:
            continue
        try:
            subprocess.run(
                [hermes_bin, "-p", pid, "cron", "remove", job_id],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception:
            pass


def _gateway_check(install_gateway: bool) -> str:
    if not install_gateway:
        return "skipped (install_gateway=false)"
    hermes_bin = shutil.which("hermes")
    if not hermes_bin:
        return "pending (hermes CLI not on PATH)"
    try:
        proc = subprocess.run([hermes_bin, "gateway", "status"], capture_output=True, text=True, timeout=5)
        if proc.returncode == 0:
            restart_proc = subprocess.run([hermes_bin, "gateway", "restart"], capture_output=True, text=True, timeout=10)
            return "restarted" if restart_proc.returncode == 0 else "active"
        return "pending (gateway not running)"
    except Exception:
        return "pending (gateway check unavailable)"


def _render_task_card_section(card: dict[str, Any]) -> str:
    fields = (
        ("Inputs", "inputs"),
        ("Exact output format", "exact_output_format"),
        ("Sources of truth", "sources_of_truth"),
        ("Out of scope", "out_of_scope"),
        ("Forbidden tools", "forbidden_tools"),
        ("Good example", "good_example"),
        ("Bad example to avoid", "bad_example_to_avoid"),
    )
    lines: list[str] = []
    for label, key in fields:
        val = str(card.get(key) or "").strip()
        if val:
            lines.append(f"- **{label}:** {val}")
    if not lines:
        return ""
    return "## Task Card\n" + "\n".join(lines) + "\n"


def forge_bot(spec: dict[str, Any], settings: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = settings or {}
    root = Path(spec.get("hermes_root") or default_root()).expanduser()
    launch_profile = str(spec.get("launch_profile") or "default").strip() or "default"

    intake_id = str(spec.get("intake_id") or "").strip()
    task_card = spec.get("task_card") if isinstance(spec.get("task_card"), dict) else None
    if intake_id:
        loaded = intake.load_intake(root, intake_id)
        if not loaded:
            return {"ok": False, "error": f"intake session '{intake_id}' not found"}
        if task_card is None:
            task_card = loaded.get("answers") if isinstance(loaded.get("answers"), dict) else {}

    if settings.get("strict_intake", False):
        complete, missing = intake.is_task_card_complete(task_card)
        if not complete:
            return {
                "ok": False,
                "error": f"strict_intake is enabled: complete dirty_forge_interview first (missing: {', '.join(missing)})",
            }

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

    with _profile_lock(root, pid):
        if pdir.exists():
            return {"ok": False, "error": f"Bot '{pid}' already exists."}

        created_routines: list[dict[str, Any]] = []
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

            enforce = bool(settings.get("enforce_approvals", True))
            approve_cats = list(spec.get("approve_categories") or ["send", "spend", "destroy"])
            requested_toolsets = [str(t).strip() for t in (spec.get("toolsets") or []) if str(t).strip() in ALL_TOOLSETS]
            allowed_extra, withheld_toolsets = _filter_restricted_toolsets(
                requested_toolsets,
                enforce_approvals=enforce,
                approve_categories=approve_cats,
                allow_restricted=bool(spec.get("allow_restricted_toolsets", False)),
            )
            toolsets = sorted(set(BASE_TOOLSETS) | set(allowed_extra))

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

            if task_card:
                tc_block = _render_task_card_section(task_card)
                if tc_block and "## Task Card" not in raw_soul:
                    raw_soul = raw_soul.rstrip() + "\n\n" + tc_block
                (pdir / "intake.json").write_text(
                    json.dumps({"intake_id": intake_id, "task_card": task_card}, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )

            soul_secrets = scan_secrets(raw_soul)
            if soul_secrets and not settings.get("allow_secrets", False):
                raise ValueError(f"secret pattern detected in SOUL.md ({', '.join(soul_secrets)})")
            soul_inj = scan_prompt_injection(raw_soul)
            if soul_inj:
                raise ValueError(f"prompt injection pattern detected in SOUL.md ({', '.join(soul_inj)})")

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

            if enforce:
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
            if isinstance(spec.get("mcp_servers"), dict) and spec["mcp_servers"]:
                allow_trusted = bool(spec.get("allow_trusted_mcp", False))
                sanitized_mcp: dict[str, Any] = {}
                for srv_name, srv_cfg in spec["mcp_servers"].items():
                    if not isinstance(srv_cfg, dict):
                        continue
                    entry = dict(srv_cfg)
                    if not allow_trusted:
                        entry["trust"] = "untrusted"
                    sanitized_mcp[str(srv_name)] = entry
                if sanitized_mcp:
                    cfg["mcp_servers"] = sanitized_mcp
            if enforce:
                cfg["dirty-forge-sentinel"] = {
                    "approve_categories": approve_cats,
                    "limits": spec.get("limits") or {},
                    "circuit_breaker_max_calls": int(
                        spec.get("circuit_breaker_max_calls") or settings.get("circuit_breaker_max_calls") or 40
                    ),
                    "circuit_breaker_max_errors": int(
                        spec.get("circuit_breaker_max_errors") or settings.get("circuit_breaker_max_errors") or 5
                    ),
                }
            save_yaml(pdir / "config.yaml", cfg)

            section_name = str(spec.get("section_name") or "DirtyForge").strip() or "DirtyForge"
            section_id = slugify_profile(section_name) or "dirty-forge"
            save_yaml(
                pdir / "profile.yaml",
                {
                    "bot_title": display_name,
                    "ui_meta": {
                        "hermes-bots": {
                            "title": display_name,
                            "sectionId": section_id,
                            "sectionName": section_name,
                            "avatarKind": avatar,
                            "hidden": False,
                        }
                    },
                },
            )

            # Memory & USER.md
            mem_lines: list[str] = [f"# {display_name} Memory\n"]
            for fact in spec.get("memory") or []:
                fact_s = str(fact).strip()
                if fact_s and not scan_secrets(fact_s) and not scan_prompt_injection(fact_s):
                    mem_lines.append(f"- {fact_s}")
            if settings.get("workspace_survey", True):
                for note in _shallow_workspace_survey(settings.get("workspace_roots")):
                    mem_lines.append(f"- {note}")
            mem_lines.append("- Metacognition: update existing memory facts rather than duplicating; record lessons in journal.")
            (pdir / "memories" / "MEMORY.md").write_text("\n".join(mem_lines) + "\n", encoding="utf-8")

            src_user = profile_dir(root, launch_profile) / "memories" / "USER.md"
            if src_user.is_file():
                shutil.copy2(src_user, pdir / "memories" / "USER.md")

            created_routines = _configure_cron(pdir, pid, spec.get("routines") or [], draft=bool(spec.get("draft", False)))
            gw_status = _gateway_check(bool(settings.get("install_gateway", True)))

            out: dict[str, Any] = {
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
                "routines": created_routines,
                "gateway": gw_status,
            }
            if withheld_toolsets:
                out["withheld_toolsets"] = withheld_toolsets
            return out
        except Exception as exc:
            _remove_cron_jobs(pid, created_routines)
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
    ok, pid_or_err = validate_profile_id(name, allow_default=False)
    if not ok:
        return {"ok": False, "error": pid_or_err}
    pdir = profile_dir(r, pid_or_err)
    if not pdir.is_dir():
        return {"ok": False, "error": f"Bot '{name}' not found"}

    soul_append = str(changes.get("soul_append") or "").strip()
    if soul_append:
        secrets = scan_secrets(soul_append)
        if secrets:
            return {"ok": False, "error": f"secret pattern detected in soul_append ({', '.join(secrets)})"}
        inj = scan_prompt_injection(soul_append)
        if inj:
            return {"ok": False, "error": f"prompt injection pattern detected in soul_append ({', '.join(inj)})"}

    cfg = load_yaml(pdir / "config.yaml")
    bots_meta = cfg.setdefault("bots", {})
    if changes.get("display_name"):
        bots_meta["title"] = str(changes["display_name"]).strip()
    if changes.get("avatar_kind") in AVATAR_KINDS:
        bots_meta["avatar_kind"] = changes["avatar_kind"]
    withheld: list[str] = []
    if isinstance(changes.get("toolsets"), list):
        valid = [str(t).strip() for t in changes["toolsets"] if str(t).strip() in ALL_TOOLSETS]
        sentinel_cfg = cfg.get("dirty-forge-sentinel")
        enforce = isinstance(sentinel_cfg, dict)
        approve_cats = list(sentinel_cfg.get("approve_categories") or ["send", "spend", "destroy"]) if enforce else []
        allowed_extra, withheld = _filter_restricted_toolsets(
            valid,
            enforce_approvals=enforce,
            approve_categories=approve_cats,
            allow_restricted=bool(changes.get("allow_restricted_toolsets", False)),
        )
        cfg["toolsets"] = sorted(set(BASE_TOOLSETS) | set(allowed_extra))
    save_yaml(pdir / "config.yaml", cfg)

    prof_path = pdir / "profile.yaml"
    if prof_path.is_file():
        prof = load_yaml(prof_path)
        ui = prof.setdefault("ui_meta", {}).setdefault("hermes-bots", {})
        if changes.get("display_name"):
            prof["bot_title"] = bots_meta["title"]
            ui["title"] = bots_meta["title"]
        if changes.get("avatar_kind") in AVATAR_KINDS:
            ui["avatarKind"] = bots_meta["avatar_kind"]
        save_yaml(prof_path, prof)

    soul_path = pdir / "SOUL.md"
    if soul_append and soul_path.is_file():
        current = soul_path.read_text(encoding="utf-8")
        soul_path.write_text(current.rstrip() + "\n\n" + soul_append + "\n", encoding="utf-8")
    out: dict[str, Any] = {"ok": True, "name": pdir.name}
    if withheld:
        out["withheld_toolsets"] = withheld
    return out


def hide_bot(name: str, hidden: bool = True, root: Path | None = None) -> dict[str, Any]:
    r = root or default_root()
    ok, pid_or_err = validate_profile_id(name, allow_default=False)
    if not ok:
        return {"ok": False, "error": pid_or_err}
    pdir = profile_dir(r, pid_or_err)
    if not pdir.is_dir():
        return {"ok": False, "error": f"Bot '{name}' not found"}
    cfg = load_yaml(pdir / "config.yaml")
    cfg.setdefault("bots", {})["hidden"] = bool(hidden)
    save_yaml(pdir / "config.yaml", cfg)
    prof_path = pdir / "profile.yaml"
    if prof_path.is_file():
        prof = load_yaml(prof_path)
        prof.setdefault("ui_meta", {}).setdefault("hermes-bots", {})["hidden"] = bool(hidden)
        save_yaml(prof_path, prof)
    return {"ok": True, "name": pdir.name, "hidden": bool(hidden)}


def activate_bot(name: str, force: bool = False, root: Path | None = None) -> dict[str, Any]:
    """Enable draft cron routines after eval_bot passes (100% pass_rate), unless force=True."""
    r = root or default_root()
    ok, pid_or_err = validate_profile_id(name, allow_default=False)
    if not ok:
        return {"ok": False, "error": pid_or_err}
    pid = pid_or_err
    pdir = profile_dir(r, pid)
    if not pdir.is_dir():
        return {"ok": False, "error": f"Bot '{name}' not found"}

    if not force:
        evals_dir = pdir / "evals"
        reports = sorted(evals_dir.glob("eval-*.json"), reverse=True) if evals_dir.is_dir() else []
        if not reports:
            return {"ok": False, "error": "activation blocked: no eval_bot report found (run dirty_forge_eval_bot first or pass force=true)"}
        try:
            latest = json.loads(reports[0].read_text(encoding="utf-8"))
        except Exception as exc:
            return {"ok": False, "error": f"activation blocked: unreadable eval report ({exc})"}
        if float(latest.get("pass_rate", 0.0)) < 1.0:
            return {
                "ok": False,
                "error": f"activation blocked: latest eval_bot passed {latest.get('passed', 0)}/{latest.get('total', 0)} (requires 100% or force=true)",
            }

    jobs_file = pdir / "cron" / "jobs.json"
    activated = 0
    if jobs_file.is_file():
        try:
            jobs = json.loads(jobs_file.read_text(encoding="utf-8"))
        except Exception:
            jobs = []
        if isinstance(jobs, list):
            hermes_bin = shutil.which("hermes")
            for entry in jobs:
                if not isinstance(entry, dict):
                    continue
                was_enabled = bool(entry.get("enabled", False))
                entry["enabled"] = True
                if not was_enabled:
                    activated += 1
                if hermes_bin and not entry.get("hermes_job_id"):
                    schedule = str(entry.get("schedule") or "").strip()
                    prompt = str(entry.get("prompt") or "").strip()
                    rname = str(entry.get("name") or "routine").strip()
                    if schedule and prompt:
                        try:
                            proc = subprocess.run(
                                [hermes_bin, "-p", pid, "cron", "add", schedule, prompt, "--name", rname],
                                capture_output=True,
                                text=True,
                                timeout=10,
                            )
                            m = re.search(r"Created job:\s*([A-Za-z0-9_.-]+)", proc.stdout or "")
                            if m:
                                entry["hermes_job_id"] = m.group(1)
                        except Exception:
                            pass
            jobs_file.write_text(json.dumps(jobs, indent=2) + "\n", encoding="utf-8")

    journal.write_entry(
        pdir,
        status="completed",
        goal="Activate Bot routines",
        outcome=f"Activated {activated} draft routine(s) (force={force}).",
    )
    return {"ok": True, "name": pid, "activated_routines": activated, "forced": bool(force)}


def delete_bot(name: str, settings: dict[str, Any] | None = None, root: Path | None = None) -> dict[str, Any]:
    settings = settings or {}
    if not settings.get("allow_delete", False):
        return {"ok": False, "error": "delete_bot is disabled (set allow_delete: true in plugin config)"}
    r = root or default_root()
    ok, pid_or_err = validate_profile_id(name, allow_default=False)
    if not ok:
        return {"ok": False, "error": pid_or_err}
    pid = pid_or_err
    pdir = profile_dir(r, pid)
    if not pdir.is_dir():
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
