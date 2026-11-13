"""Portability & skill teaching for DirtyForge Bots: copy, teach, share, and import."""
from __future__ import annotations

import json
import re
import shutil
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import forge
from .sentinel.guard import scan_secrets

_SKILL_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


def teach_bot(name: str, skill_name: str, skill_md: str, root: Path | None = None) -> dict[str, Any]:
    r = root or forge.default_root()
    pid = forge.slugify_profile(name)
    pdir = forge.profile_dir(r, pid)
    if not pdir.is_dir():
        return {"ok": False, "error": f"Bot '{name}' not found"}
    slug = forge.slugify_profile(skill_name)
    if not _SKILL_SLUG_RE.match(slug):
        return {"ok": False, "error": f"invalid skill_name '{skill_name}'"}
    content = (skill_md or "").strip()
    if not content:
        return {"ok": False, "error": "skill_md is required"}
    secrets = scan_secrets(content)
    if secrets:
        return {"ok": False, "error": f"refused to teach skill: secret pattern detected ({', '.join(secrets)})"}

    skill_dir = pdir / "skills" / slug
    skill_dir.mkdir(parents=True, exist_ok=True)
    if not content.startswith("---\n"):
        content = f"---\nname: {slug}\ndescription: Taught skill for {pid}\n---\n\n{content}"
    target = skill_dir / "SKILL.md"
    target.write_text(content + "\n", encoding="utf-8")
    return {"ok": True, "bot": pid, "skill": slug, "path": str(target)}


def copy_bot(
    source_name: str,
    new_display_name: str,
    role: str = "",
    settings: dict[str, Any] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    r = root or forge.default_root()
    src_id = forge.slugify_profile(source_name)
    src_dir = forge.profile_dir(r, src_id)
    if not src_dir.is_dir():
        return {"ok": False, "error": f"source Bot '{source_name}' not found"}

    src_cfg = forge.load_yaml(src_dir / "config.yaml")
    bots_meta = src_cfg.get("bots") if isinstance(src_cfg.get("bots"), dict) else {}
    src_soul = (src_dir / "SOUL.md").read_text(encoding="utf-8", errors="ignore") if (src_dir / "SOUL.md").is_file() else ""
    src_title = str(bots_meta.get("title") or src_id)
    updated_soul = src_soul.replace(src_title, new_display_name.strip()) if src_soul else ""

    spec: dict[str, Any] = {
        "hermes_root": str(r),
        "launch_profile": src_id,
        "display_name": new_display_name,
        "role": role or str(bots_meta.get("role") or "Specialist"),
        "avatar_kind": bots_meta.get("avatar_kind") or "boxy",
        "soul_md": updated_soul,
        "toolsets": src_cfg.get("toolsets") or [],
        "model": src_cfg.get("model") or {},
        "omh_memory_mode": bots_meta.get("omh_memory_mode") or "auto-safe",
    }
    res = forge.forge_bot(spec, settings=settings)
    if not res.get("ok"):
        return res

    dst_dir = Path(res["profile_dir"])
    src_skills = src_dir / "skills"
    if src_skills.is_dir():
        for child in src_skills.iterdir():
            if child.is_dir() and (child / "SKILL.md").is_file():
                shutil.copytree(child, dst_dir / "skills" / child.name, dirs_exist_ok=True)
    return res


def share_bot(
    name: str,
    mode: str = "template",
    out_path: str = "",
    allow_secrets: bool = False,
    root: Path | None = None,
) -> dict[str, Any]:
    r = root or forge.default_root()
    pid = forge.slugify_profile(name)
    pdir = forge.profile_dir(r, pid)
    if not pdir.is_dir():
        return {"ok": False, "error": f"Bot '{name}' not found"}

    exports_dir = r / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)

    if mode == "backup":
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        archive = Path(out_path).expanduser() if out_path else (exports_dir / f"{pid}-backup-{stamp}.tar.gz")
        archive.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(pdir, arcname=pid)
        return {"ok": True, "mode": "backup", "path": str(archive), "contains_chat_history": True}

    cfg = forge.load_yaml(pdir / "config.yaml")
    bots_meta = cfg.get("bots") if isinstance(cfg.get("bots"), dict) else {}
    soul_md = (pdir / "SOUL.md").read_text(encoding="utf-8", errors="ignore") if (pdir / "SOUL.md").is_file() else ""
    taught: dict[str, str] = {}
    if (pdir / "skills").is_dir():
        for child in sorted((pdir / "skills").iterdir()):
            skill_file = child / "SKILL.md"
            if child.is_dir() and skill_file.is_file():
                taught[child.name] = skill_file.read_text(encoding="utf-8", errors="ignore")

    routines: list[dict[str, Any]] = []
    jobs_file = pdir / "cron" / "jobs.json"
    if jobs_file.is_file():
        try:
            routines = json.loads(jobs_file.read_text(encoding="utf-8"))
        except Exception:
            routines = []

    bundle = {
        "format": "dirty-forge/template",
        "version": 1,
        "display_name": bots_meta.get("title") or pid.capitalize(),
        "role": bots_meta.get("role") or "Assistant",
        "avatar_kind": bots_meta.get("avatar_kind") or "boxy",
        "toolsets": cfg.get("toolsets") or [],
        "omh_memory_mode": bots_meta.get("omh_memory_mode") or "auto-safe",
        "soul_md": soul_md,
        "taught_skills": taught,
        "routines": routines,
    }
    serialized = json.dumps(bundle, ensure_ascii=False, indent=2)
    secrets = scan_secrets(serialized)
    if secrets and not allow_secrets:
        return {"ok": False, "error": f"export blocked by secret scanner ({', '.join(secrets)})"}

    target = Path(out_path).expanduser() if out_path else (exports_dir / f"{pid}.dirtyforge.json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(serialized + "\n", encoding="utf-8")
    return {"ok": True, "mode": "template", "path": str(target)}


def import_bot(
    source_path: str,
    display_name: str = "",
    allow_secrets: bool = False,
    settings: dict[str, Any] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    r = root or forge.default_root()
    src = Path(source_path).expanduser()
    if not src.is_file():
        return {"ok": False, "error": f"template file not found: {source_path}"}
    raw = src.read_text(encoding="utf-8", errors="ignore")
    secrets = scan_secrets(raw)
    if secrets and not allow_secrets:
        return {"ok": False, "error": f"import blocked by secret scanner ({', '.join(secrets)})"}
    try:
        data = json.loads(raw)
    except Exception as exc:
        return {"ok": False, "error": f"invalid template JSON: {exc}"}

    if data.get("format") not in ("dirty-forge/template", "bot-forge/template"):
        return {"ok": False, "error": "unsupported template format"}

    spec: dict[str, Any] = {
        "hermes_root": str(r),
        "display_name": display_name.strip() or data.get("display_name") or "Imported",
        "role": data.get("role") or "Specialist",
        "avatar_kind": data.get("avatar_kind") or "boxy",
        "toolsets": data.get("toolsets") or [],
        "soul_md": data.get("soul_md") or "",
        "routines": data.get("routines") or [],
        "omh_memory_mode": data.get("omh_memory_mode") or "auto-safe",
    }
    res = forge.forge_bot(spec, settings=settings)
    if not res.get("ok"):
        return res

    for s_name, s_content in (data.get("taught_skills") or {}).items():
        teach_bot(res["name"], str(s_name), str(s_content), root=r)
    return res
