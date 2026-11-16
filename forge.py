"""Core Hermes Bot profile provisioning, updating, and rollback for DirtyForge."""
from __future__ import annotations

import contextlib
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
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
# The silhouettes Desktop can actually draw (`BLOB_KINDS` in avatar.tsx). A kind outside this
# list is accepted by the schema, written into ui_meta, and then silently dropped by the renderer —
# the Bot keeps a shape string that draws nothing. `leaf` and `star` used to sit here and did exactly
# that; `round`/`capsule`/`nub`/`organic`/`hexagon`/`triangle` were unreachable.
AVATAR_KINDS = ("sun", "cloud", "boxy", "droplet", "capsule", "round", "nub", "organic", "hexagon", "triangle")
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
    """The Hermes root that holds ``profiles/``, not the profile we happen to run in.

    This plugin now runs inside the `forge` profile, whose HERMES_HOME is
    ``<root>/profiles/forge``: trusting it blindly put the Bots it creates inside its own profile
    directory. A ``profiles`` parent means we were handed a profile home; the root is one level up.
    """
    env_home = os.environ.get("HERMES_HOME", "").strip()
    path = Path(env_home).expanduser() if env_home else Path.home() / ".hermes"
    return path.parent.parent if path.parent.name == "profiles" else path


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


_ASSISTANT_NAMING = re.compile(
    r"\b(call|calls|called|name|names|named)\b.{0,40}\bassistant\b|\bassistant\b.{0,40}\b(name|named|called)\b",
    re.I,
)


def _filter_user_memory(text: str, other_names: set[str]) -> str:
    """Keep the facts about the user, drop entries naming an assistant (they make a bot adopt its name)."""
    keep: list[str] = []
    for entry in (e.strip() for e in text.split("§")):
        if not entry or _ASSISTANT_NAMING.search(entry):
            continue
        if any(
            re.search(rf"\b{re.escape(n)}\b", entry, re.I) and re.search(r"\bname", entry, re.I)
            for n in other_names
            if n
        ):
            continue
        keep.append(entry)
    return "\n§\n".join(keep) + ("\n" if keep else "")


def _hermes_root_resolves_to(root: Path) -> bool:
    """Does Hermes' own root resolution land on *root*? Only then may we let it create the profile.

    Hermes resolves its home through ``hermes_constants``, never straight from ``HERMES_HOME``: a
    temp root handed to it silently falls back to the real ``~/.hermes``, which is how a test run
    once filed sixteen Bots into the operator's own profiles directory.
    """
    try:
        import hermes_constants

        return hermes_constants.get_default_hermes_root().resolve() == root.resolve()
    except Exception:
        return False


def _delete_profile_through_hermes(root: Path, pid: str) -> str:
    """Delete the profile through Hermes' own teardown. ``""`` means gone; a reason otherwise.

    A bare ``shutil.rmtree`` leaves the multiplexer serving a profile whose directory is gone: the
    gateway keeps its handles, recreates the scaffolding on the next reconcile, and the Bot comes
    back as an empty shell. Hermes' teardown tombstones the name, unserve the profile, settles its
    identity and releases the open handles first — the same order ``hermes profile delete`` uses.
    """
    if not _hermes_root_resolves_to(root):
        return "skip"
    try:
        from hermes_cli.profiles import delete_profile
    except ImportError:
        return "skip"
    try:
        delete_profile(pid, yes=True)
    except Exception as exc:  # a live runtime that still owns it, a partial identity settlement
        return f"profile delete failed: {exc}"
    return ""


def _provision_profile(root: Path, pid: str, description: str) -> str:
    """Create the profile through Hermes' provisioning. ``""`` means made; ``"skip"`` means "lay it out here".

    Returns ``"skip"`` when Hermes would not resolve this root (tests, scratch homes) — the caller
    then writes the layout itself, and that is the only case where it still does.
    """
    if not _hermes_root_resolves_to(root):
        return "skip"
    plugin_dir = Path(__file__).parent.resolve()
    parked = [p for p in sys.path if Path(p or ".").resolve() == plugin_dir]  # our tools.py shadows core
    for p in parked:
        sys.path.remove(p)
    try:
        from hermes_cli.profile_provision import ProfileCreateRequest, provision_profile

        result = provision_profile(
            ProfileCreateRequest(
                name=pid,
                description=description or None,
                alias=False,  # a wrapper belongs to the operator's PATH; forge names profiles, not commands
                mirror_credentials=True,
                share_auth=True,
                quiet=True,
            )
        )
    except ImportError:
        return "skip"
    except Exception as exc:  # a refusal (name taken, bad model): report it, never retry blindly
        return f"profile create failed: {exc}"
    finally:
        sys.path[:0] = parked
    if result.path.resolve() != profile_dir(root, pid).resolve():
        # Hermes made it somewhere else (a root it resolved differently). Leaving it there would be
        # an orphan profile the caller never reports and cannot find; this call created it, so this
        # call removes it.
        shutil.rmtree(result.path, ignore_errors=True)
        return f"profile landed outside the requested root ({result.path}) and was removed"
    return ""


KICKOFF = "Hey, tell me about yourself!"


def _kickoff_check(root: Path, pid: str, settings: dict[str, Any]) -> str:
    """Send the Bot its first message and return "" (it answered) or the reason it did not.

    Same first message Desktop's New Agent sends. Cheap because a Bot whose model cannot sign in
    is otherwise reported as a success and discovered broken by the operator.
    """
    hermes_bin = shutil.which("hermes")
    if not hermes_bin:
        return "kickoff skipped: hermes CLI not on PATH"
    if not _hermes_root_resolves_to(root):
        return "kickoff skipped: this root is not one Hermes resolves"
    env = {k: v for k, v in os.environ.items() if not k.startswith("HERMES_")}
    env["HERMES_HOME"] = str(root)
    timeout = max(30.0, core_tool_deadline(root) - DEADLINE_MARGIN)
    try:
        proc = subprocess.run(
            [hermes_bin, "-p", pid, "chat", "-q", KICKOFF],
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return f"kickoff did not finish in {timeout:.0f}s"
    except Exception as exc:
        return f"kickoff failed: {exc}"
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()
        return f"kickoff failed ({tail[-1] if tail else 'no output'})"
    return ""


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
                    [hermes_bin, "-p", pid, "cron", "add", schedule, prompt, "--name", name,
                     "--deliver", f"bot-chat:{pid}"],
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
            provisioned = _provision_profile(
                root, pid, description=f"{role}: {str(spec.get('description') or '').strip()}".strip(": ")
            )
            if provisioned.startswith("profile "):
                raise RuntimeError(provisioned)
            if provisioned == "skip":
                # A root Hermes itself will not resolve (a scratch or test home): lay the layout out
                # here, since nothing else can. The real root always goes through provisioning.
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

            cfg: dict[str, Any] = load_yaml(pdir / "config.yaml")
            cfg["model"] = model_cfg
            # Hermes reads `platform_toolsets.<platform>`, never a top-level `toolsets`: a bot given
            # only `toolsets` came out with every tool enabled, so this whitelist is what actually
            # holds the restriction.
            cfg.setdefault("platform_toolsets", {})["cli"] = toolsets
            cfg["plugins"] = {"enabled": sorted(set(enabled_plugins))}
            if isinstance(spec.get("mcp_servers"), dict) and spec["mcp_servers"]:
                allow_trusted = bool(spec.get("allow_trusted_mcp", settings.get("allow_trusted_mcp", False)))
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
            bot_meta = load_yaml(pdir / "profile.yaml")
            ui = bot_meta.setdefault("ui_meta", {}).setdefault("hermes-bots", {})
            ui.update(
                {
                    "title": display_name,
                    "description": str(spec.get("description") or "").strip(),
                    "sectionId": section_id,
                    "sectionName": section_name,
                    # Desktop draws a face from `imageKind` + `shape`; the old `avatarKind` key is not
                    # read by any client, so every Bot from this plugin rendered without one.
                    "imageKind": "shape",
                    "shape": f"blobatar::{avatar}",
                    "hidden": False,
                }
            )
            ui.setdefault("created", int(time.time() * 1000))
            revisions = bot_meta.get("_ui_meta_revisions")
            revisions = revisions if isinstance(revisions, dict) else {}
            revisions["hermes-bots"] = int(revisions.get("hermes-bots", 0)) + 1
            bot_meta["_ui_meta_revisions"] = revisions
            bot_meta["display_name"] = display_name
            # Kept for the plugin's own older readers and tests; Desktop reads ui_meta only.
            bot_meta["bot_title"] = display_name
            bot_meta["bot_title_role"] = role
            bot_meta["bot"] = {"managed_by": "dirty-forge", "omh_memory_mode": omh_mode}
            save_yaml(pdir / "profile.yaml", bot_meta)

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
                # A verbatim copy carried the launching profile's own name into a bot with a different
                # one, so it introduced itself as somebody else; `_filter_user_memory` keeps the facts
                # about the user and drops the entries that name an assistant.
                others = {b["name"] for b in list_bots(root, include_hidden=True)} | {launch_profile}
                (pdir / "memories" / "USER.md").write_text(
                    _filter_user_memory(src_user.read_text(encoding="utf-8"), others), encoding="utf-8"
                )

            created_routines = _configure_cron(pdir, pid, spec.get("routines") or [], draft=bool(spec.get("draft", False)))
            gw_status = _gateway_check(bool(settings.get("install_gateway", True)))
            # A Bot that never answers is not a Bot: the kickoff turn is the only check that the
            # model, the credentials and the SOUL all work together. It is not a rollback condition.
            chat_warning = _kickoff_check(root, pid, settings)

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
            if chat_warning:
                out["warning"] = chat_warning
            return out
        except Exception as exc:
            _remove_cron_jobs(pid, created_routines)
            if pdir.exists():
                shutil.rmtree(pdir, ignore_errors=True)
            return {"ok": False, "error": f"provisioning failed and rolled back: {exc}"}


def _is_tombstoned(root: Path, pdir: Path) -> bool:
    """True when this directory is a deleted profile Hermes recreated as an empty shell.

    A deleted profile leaves a marker under ``profiles/.deleted/<name>``; a live gateway that still
    held the old handles then recreates the directory with nothing in it. Hermes skips those in its
    own roster (``named_profile_is_deleted``), so a roster that lists them reports Bots that have no
    config, no SOUL and no model — the operator sees ghosts.
    """
    return (root / "profiles" / ".deleted" / pdir.name).exists()


def list_bots(root: Path | None = None, include_hidden: bool = False) -> list[dict[str, Any]]:
    base = (root or default_root()) / "profiles"
    if not base.is_dir():
        return []
    bots: list[dict[str, Any]] = []
    for pdir in sorted(base.iterdir()):
        if not pdir.is_dir() or pdir.name.startswith("."):
            continue
        if _is_tombstoned(root or default_root(), pdir):
            continue
        cfg = load_yaml(pdir / "config.yaml")
        # profile.yaml is the roster truth: it is what Hermes' own roster and Desktop read, so a
        # second copy under config.yaml:bots could only ever disagree with it.
        meta = load_yaml(pdir / "profile.yaml")
        ui = (meta.get("ui_meta") or {}).get("hermes-bots")
        ui = ui if isinstance(ui, dict) else {}
        hidden = bool(ui.get("hidden", False))
        if hidden and not include_hidden:
            continue
        shape = str(ui.get("shape") or "")
        bots.append(
            {
                "name": pdir.name,
                "display_name": ui.get("title") or meta.get("display_name") or pdir.name,
                "role": meta.get("bot_title_role") or "",
                "avatar_kind": shape.rsplit(":", 1)[-1] if shape else "boxy",
                "hidden": hidden,
                "omh_memory_mode": ((pdir / ".omh" / "setup-profile.json").is_file() and "auto-safe") or "unknown",
                "model": (cfg.get("model") or {}).get("default", ""),
            }
        )
    return bots


HISTORY_KEEP = 20
SNAPSHOT_FILES = ("SOUL.md", "config.yaml", "profile.yaml")


def _snapshot_dir(pdir: Path) -> Path:
    """A fresh ``history/<UTC stamp>/`` directory; a second edit in the same second gets a suffix."""
    base = pdir / "history"
    base.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = base / stamp
    suffix = 1
    while target.exists():
        target = base / f"{stamp}-{suffix}"
        suffix += 1
    target.mkdir()
    return target


def snapshot_bot(pdir: Path, reason: str = "") -> dict[str, Any]:
    """Copy the files an edit may touch into ``history/``; the manifest is written last, on purpose.

    A snapshot without ``manifest.json`` is a run that died mid-copy, and ``rollback_bot`` refuses
    it rather than restoring half a Bot. Retention keeps the newest ``HISTORY_KEEP`` snapshots.
    """
    target = _snapshot_dir(pdir)
    copied: list[str] = []
    for name in SNAPSHOT_FILES:
        src = pdir / name
        if src.is_file():
            shutil.copy2(src, target / name)
            copied.append(name)
    (target / "manifest.json").write_text(
        json.dumps({"files": copied, "reason": reason, "at": datetime.now(timezone.utc).isoformat()}, indent=2) + "\n",
        encoding="utf-8",
    )
    history = pdir / "history"
    # Only our own snapshots are candidates: a directory in here without a manifest was put there by
    # someone else, and retention must never destroy what it did not create.
    snaps = sorted(
        (d for d in history.iterdir() if d.is_dir() and (d / "manifest.json").is_file()), reverse=True
    )
    for stale in snaps[HISTORY_KEEP:]:
        shutil.rmtree(stale, ignore_errors=True)
    return {"stamp": target.name, "files": copied}


def _snapshot_text(target: Path, name: str) -> str:
    path = target / name
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def _snapshot_diff(before: Path, pdir: Path, files: list[str]) -> str:
    """Unified diff of the snapshot against the Bot as it is now, capped for a chat reply."""
    chunks: list[str] = []
    for name in files:
        old = _snapshot_text(before, name).splitlines(keepends=True)
        new = (pdir / name).read_text(encoding="utf-8").splitlines(keepends=True) if (pdir / name).is_file() else []
        if old == new:
            continue
        chunks.extend(difflib.unified_diff(old, new, fromfile=f"a/{name}", tofile=f"b/{name}", n=2))
    text = "".join(chunks)
    return text if len(text) <= 6000 else text[:6000] + "\n… (diff truncated)\n"


def rollback_bot(name: str, stamp: str = "last", root: Path | None = None) -> dict[str, Any]:
    """Restore a Bot's files from ``history/<stamp>`` (default: the newest) and snapshot that first."""
    r = root or default_root()
    ok, pid_or_err = validate_profile_id(name, allow_default=False)
    if not ok:
        return {"ok": False, "error": pid_or_err}
    pdir = profile_dir(r, pid_or_err)
    if not pdir.is_dir():
        return {"ok": False, "error": f"Bot '{name}' not found"}
    history = pdir / "history"
    if not history.is_dir():
        return {"ok": False, "error": f"no snapshots for '{pid_or_err}' — nothing to roll back"}
    snaps = sorted(
        (d for d in history.iterdir() if d.is_dir() and (d / "manifest.json").is_file()), reverse=True
    )
    if not snaps:
        return {"ok": False, "error": f"no snapshots for '{pid_or_err}' — nothing to roll back"}
    if stamp and stamp != "last":
        match = next((d for d in snaps if d.name == stamp), None)
        if match is None:
            return {"ok": False, "error": f"snapshot '{stamp}' not found"}
        target = match
    else:
        target = snaps[0]
    manifest_path = target / "manifest.json"
    if not manifest_path.is_file():
        return {
            "ok": False,
            "error": f"snapshot '{target.name}' is incomplete (no manifest.json) — refusing to restore half a Bot",
        }
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"ok": False, "error": f"snapshot '{target.name}' has an unreadable manifest ({exc})"}
    files = [f for f in manifest.get("files") or [] if f in SNAPSHOT_FILES]
    if not files:
        return {"ok": False, "error": f"snapshot '{target.name}' holds no files"}
    # Read the payload BEFORE the undo snapshot: that snapshot applies retention, and when history
    # is at the cap the oldest one — this very target — is what retention deletes.
    payload = {f: (target / f).read_bytes() for f in files if (target / f).is_file()}
    missing = [f for f in files if f not in payload]
    if missing:
        # A manifest naming a file that is gone means the snapshot is damaged; restoring the rest
        # would leave the Bot in a state neither the operator nor Hermes ever chose.
        return {
            "ok": False,
            "error": f"snapshot '{target.name}' is damaged (missing: {', '.join(missing)}) — refusing a partial restore",
        }
    undo = snapshot_bot(pdir, reason=f"before rollback to {target.name}")
    restored: list[str] = []
    for filename, blob in payload.items():
        (pdir / filename).write_bytes(blob)
        restored.append(filename)
    if not restored:  # never report a rollback that restored nothing
        return {"ok": False, "error": f"rollback to '{target.name}' restored nothing"}
    return {
        "ok": True,
        "name": pid_or_err,
        "restored": restored,
        "from": target.name,
        "undo_snapshot": undo["stamp"],
    }


def update_bot(name: str, changes: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    r = root or default_root()
    ok, pid_or_err = validate_profile_id(name, allow_default=False)
    if not ok:
        return {"ok": False, "error": pid_or_err}
    pdir = profile_dir(r, pid_or_err)
    if not pdir.is_dir():
        return {"ok": False, "error": f"Bot '{name}' not found"}

    soul_append = str(changes.get("soul_append") or "").strip()
    soul_replace = str(changes.get("soul_replace") or "").strip()
    for label, body in (("soul_append", soul_append), ("soul_replace", soul_replace)):
        if not body:
            continue
        secrets = scan_secrets(body)
        if secrets:
            return {"ok": False, "error": f"secret pattern detected in {label} ({', '.join(secrets)})"}
        inj = scan_prompt_injection(body)
        if inj:
            return {"ok": False, "error": f"prompt injection pattern detected in {label} ({', '.join(inj)})"}

    cfg = load_yaml(pdir / "config.yaml")
    cfg.setdefault("platform_toolsets", {})
    prof_path = pdir / "profile.yaml"
    prof = load_yaml(prof_path)
    ui = prof.setdefault("ui_meta", {}).setdefault("hermes-bots", {})
    # Nothing is written before this: an edit with no snapshot is an edit nobody can undo.
    snap = snapshot_bot(pdir, reason=name)
    if changes.get("display_name"):
        title = str(changes["display_name"]).strip()
        ui["title"] = title
        prof["display_name"] = title
    if changes.get("avatar_kind") in AVATAR_KINDS:
        ui["imageKind"] = "shape"
        ui["shape"] = f"blobatar::{changes['avatar_kind']}"
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
        cfg["platform_toolsets"]["cli"] = sorted(set(BASE_TOOLSETS) | set(allowed_extra))
    save_yaml(pdir / "config.yaml", cfg)

    if prof.get("ui_meta"):
        save_yaml(prof_path, prof)

    soul_path = pdir / "SOUL.md"
    if (soul_append or soul_replace) and soul_path.is_file():
        current = soul_path.read_text(encoding="utf-8")
        if soul_replace:
            # Replace, not append: after three "also add that…" appends nobody can tell which
            # version is live, and there is no way back to a clean one.
            soul_path.write_text(soul_replace.rstrip() + "\n", encoding="utf-8")
        else:
            soul_path.write_text(current.rstrip() + "\n\n" + soul_append + "\n", encoding="utf-8")
    out: dict[str, Any] = {"ok": True, "name": pdir.name, "snapshot": snap["stamp"]}
    diff = _snapshot_diff(pdir / "history" / snap["stamp"], pdir, snap["files"])
    if diff:
        out["diff"] = diff
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

    # Hermes' own teardown first: it tombstones the name, unserve the profile and releases the
    # handles that keep recreating this directory. Falling back to rmtree only when Hermes cannot
    # resolve this root (tests, scratch homes), which is also the only case provisioning falls back.
    teardown = _delete_profile_through_hermes(r, pid)
    if teardown == "skip":
        shutil.rmtree(pdir)
    elif teardown:
        return {"ok": False, "error": teardown, "backup": backup_path}
    if pdir.exists():
        return {"ok": False, "error": f"Bot '{pid}' is still on disk after delete", "backup": backup_path}
    return {"ok": True, "deleted": pid, "backup": backup_path}
