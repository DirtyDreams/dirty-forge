"""Build a team of DirtyForge Bots: a lead plus specialists that report to it."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import forge

MAX_MEMBERS = 6


def _tell_lead(root: Path, lead_id: str, team_name: str, roster: list[dict[str, Any]]) -> None:
    mem = forge.profile_dir(root, lead_id) / "memories" / "MEMORY.md"
    if not mem.parent.is_dir():
        return
    lines = [f"- @{m['name']} ({m['display_name']}): {m.get('role', '')}" for m in roster]
    entry = (
        f"\n## Team: {team_name}\n"
        + "\n".join(lines)
        + "\nDelegate specialist work to these teammates via `dirty_forge_handoff_bot` or `dirty_forge_ask_bot`.\n"
    )
    existing = mem.read_text(encoding="utf-8", errors="ignore").rstrip() if mem.exists() else ""
    mem.write_text((existing + "\n" if existing else "") + entry, encoding="utf-8")


def build_team(spec: dict[str, Any], settings: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = settings or {}
    root = Path(spec.get("hermes_root") or forge.default_root()).expanduser()
    launch_profile = str(spec.get("launch_profile") or "default").strip() or "default"
    raw_members = [m for m in (spec.get("members") or []) if isinstance(m, dict)][:MAX_MEMBERS]
    if not raw_members:
        return {"ok": False, "error": "a team needs at least one member in `members`"}

    team_name = str(spec.get("team") or "Core").strip() or "Core"
    lead_id = ""
    lead_result: dict[str, Any] | None = None

    if spec.get("lead_name"):
        candidate = forge.slugify_profile(str(spec["lead_name"]))
        if not forge.profile_dir(root, candidate).is_dir():
            return {"ok": False, "error": f"lead_name '{candidate}' not found"}
        lead_id = candidate
    elif isinstance(spec.get("lead"), dict):
        lead_spec = {
            **spec["lead"],
            "hermes_root": str(root),
            "launch_profile": launch_profile,
        }
        lead_res = forge.forge_bot(lead_spec, settings=settings)
        if not lead_res.get("ok"):
            return {"ok": False, "error": f"lead provisioning failed: {lead_res.get('error')}"}
        lead_id = lead_res["name"]
        lead_result = lead_res

    built: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    for member in raw_members:
        m_spec = {
            **member,
            "hermes_root": str(root),
            "launch_profile": launch_profile,
        }
        if lead_id and not m_spec.get("escalate_to"):
            m_spec["escalate_to"] = f"@{lead_id}"
        res = forge.forge_bot(m_spec, settings=settings)
        if res.get("ok"):
            built.append(res)
        else:
            failed.append({"display_name": member.get("display_name", ""), "error": res.get("error", "failed")})

    if lead_id and built:
        _tell_lead(root, lead_id, team_name, built)

    return {
        "ok": len(built) > 0,
        "team": team_name,
        "lead": lead_result or ({"name": lead_id} if lead_id else None),
        "built": built,
        "failed": failed,
    }
