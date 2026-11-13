"""FastAPI backend bridge for DirtyForge Hermes Desktop UI (/api/plugins/dirty-forge/*)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Query

_PLUGIN_ROOT = Path(__file__).resolve().parent.parent
if str(_PLUGIN_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT.parent))

if __package__ and "." in __package__:
    from .. import blueprints, evals, forge, intake, journal, omh_memory, policy, portable, takeover, team
    from ..sentinel import telemetry
else:  # pragma: no cover - fallback when loaded directly by file path or `dashboard.plugin_api`
    import importlib
    import importlib.util

    _PKG = "dirty_forge"
    if _PKG not in sys.modules:
        _spec = importlib.util.spec_from_file_location(
            _PKG,
            str(_PLUGIN_ROOT / "__init__.py"),
            submodule_search_locations=[str(_PLUGIN_ROOT)],
        )
        if _spec and _spec.loader:
            _mod = importlib.util.module_from_spec(_spec)
            sys.modules[_PKG] = _mod
            _spec.loader.exec_module(_mod)
    blueprints = importlib.import_module(f"{_PKG}.blueprints")
    evals = importlib.import_module(f"{_PKG}.evals")
    forge = importlib.import_module(f"{_PKG}.forge")
    intake = importlib.import_module(f"{_PKG}.intake")
    journal = importlib.import_module(f"{_PKG}.journal")
    omh_memory = importlib.import_module(f"{_PKG}.omh_memory")
    policy = importlib.import_module(f"{_PKG}.policy")
    portable = importlib.import_module(f"{_PKG}.portable")
    takeover = importlib.import_module(f"{_PKG}.takeover")
    team = importlib.import_module(f"{_PKG}.team")
    telemetry = importlib.import_module(f"{_PKG}.sentinel.telemetry")

router = APIRouter()

_SETTINGS_DEFAULTS: dict[str, Any] = {
    "inherit_model": True,
    "fallback_model": {},
    "probe_local_models": False,
    "omh_memory_mode": "auto-safe",
    "inherit_plugins": ["omh"],
    "enforce_approvals": True,
    "journal_enabled": True,
    "ack_reactions": True,
    "ack_tapback": True,
    "workspace_survey": True,
    "workspace_roots": [],
    "install_gateway": True,
    "allow_secrets": False,
    "allow_delete": False,
    "backup_before_delete": True,
    "allow_external_delegation": False,
    "allowed_external_clis": ["codex", "claude", "aider"],
    "circuit_breaker_max_calls": 40,
    "circuit_breaker_max_errors": 5,
    "strict_intake": False,
    "allow_trusted_mcp": False,
}

_VALID_OMH_MODES = ("auto-safe", "review-first", "off")
_BOOL_SETTINGS = {
    "inherit_model",
    "probe_local_models",
    "enforce_approvals",
    "journal_enabled",
    "ack_reactions",
    "ack_tapback",
    "workspace_survey",
    "install_gateway",
    "allow_secrets",
    "allow_delete",
    "backup_before_delete",
    "allow_external_delegation",
    "strict_intake",
    "allow_trusted_mcp",
}
_INT_SETTINGS = {"circuit_breaker_max_calls", "circuit_breaker_max_errors"}
_LIST_SETTINGS = {"inherit_plugins", "workspace_roots", "allowed_external_clis"}


def _validate_settings_updates(updates: dict[str, Any]) -> tuple[dict[str, Any], str | None]:
    clean: dict[str, Any] = {}
    for k, v in updates.items():
        if k not in _SETTINGS_DEFAULTS:
            continue
        if k in _BOOL_SETTINGS:
            if not isinstance(v, bool):
                return {}, f"setting '{k}' must be a boolean"
            clean[k] = v
        elif k in _INT_SETTINGS:
            if isinstance(v, bool) or not isinstance(v, int) or v < 1 or v > 10000:
                return {}, f"setting '{k}' must be an integer between 1 and 10000"
            clean[k] = v
        elif k == "omh_memory_mode":
            if v not in _VALID_OMH_MODES:
                return {}, f"setting 'omh_memory_mode' must be one of {_VALID_OMH_MODES}"
            clean[k] = v
        elif k in _LIST_SETTINGS:
            if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
                return {}, f"setting '{k}' must be a list of strings"
            clean[k] = v
        elif k == "fallback_model":
            if not isinstance(v, dict):
                return {}, "setting 'fallback_model' must be a dict"
            clean[k] = v
    return clean, None


def _load_settings(root: Path | None = None) -> dict[str, Any]:
    r = root or forge.default_root()
    cfg = forge.load_yaml(r / "config.yaml")
    out = dict(_SETTINGS_DEFAULTS)
    plugins_entries = ((cfg.get("plugins") or {}).get("entries") or {}).get("dirty-forge") or {}
    if isinstance(plugins_entries, dict) and isinstance(plugins_entries.get("settings"), dict):
        for k, v in plugins_entries["settings"].items():
            if k in out:
                out[k] = v
    direct = cfg.get("dirty-forge") or cfg.get("dirty_forge") or {}
    if isinstance(direct, dict):
        for k, v in direct.items():
            if k in out:
                out[k] = v
    return out


def _save_settings(updates: dict[str, Any], root: Path | None = None) -> dict[str, Any]:
    r = root or forge.default_root()
    cfg_path = r / "config.yaml"
    cfg = forge.load_yaml(cfg_path)
    section = cfg.get("dirty-forge")
    if not isinstance(section, dict):
        section = {}
    for k, v in updates.items():
        if k in _SETTINGS_DEFAULTS:
            section[k] = v
    cfg["dirty-forge"] = section
    forge.save_yaml(cfg_path, cfg)
    return _load_settings(r)


def _list_takeovers(pdir: Path) -> list[dict[str, Any]]:
    tdir = pdir / "takeovers"
    if not tdir.is_dir():
        return []
    items: list[dict[str, Any]] = []
    for f in sorted(tdir.glob("*.json"), reverse=True):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                items.append(data)
        except Exception:
            continue
    return items


@router.get("/health")
def get_health() -> dict[str, Any]:
    return {"ok": True, "plugin": "dirty-forge"}


@router.get("/summary")
def get_summary() -> dict[str, Any]:
    root = forge.default_root()
    bots = forge.list_bots(root=root, include_hidden=True)
    drifted = 0
    tripped = 0
    pending_takeovers = 0
    active = 0
    draft = 0
    for bot in bots:
        pdir = forge.profile_dir(root, bot["name"])
        if bot.get("status") == "active":
            active += 1
        else:
            draft += 1
        if not policy.check_drift(root, pdir).get("in_sync", False):
            drifted += 1
        if telemetry.get_metrics(pdir).get("breaker_tripped"):
            tripped += 1
        pending_takeovers += sum(1 for t in _list_takeovers(pdir) if t.get("status") == "pending_human")
    return {
        "ok": True,
        "total_bots": len(bots),
        "active_bots": active,
        "draft_bots": draft,
        "drifted_policies": drifted,
        "tripped_breakers": tripped,
        "pending_takeovers": pending_takeovers,
    }


@router.get("/settings")
def get_settings() -> dict[str, Any]:
    return {"ok": True, "settings": _load_settings()}


@router.put("/settings")
def update_settings(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    updates = payload.get("settings") if isinstance(payload.get("settings"), dict) else payload
    if not isinstance(updates, dict):
        return {"ok": False, "error": "settings object required"}
    clean, err = _validate_settings_updates(updates)
    if err:
        return {"ok": False, "error": err}
    saved = _save_settings(clean)
    return {"ok": True, "settings": saved}


@router.get("/bots")
def get_bots(include_hidden: bool = Query(default=True)) -> dict[str, Any]:
    root = forge.default_root()
    bots = forge.list_bots(root=root, include_hidden=include_hidden)
    enriched: list[dict[str, Any]] = []
    for bot in bots:
        pdir = forge.profile_dir(root, bot["name"])
        drift = policy.check_drift(root, pdir)
        metrics = telemetry.get_metrics(pdir)
        takeovers = _list_takeovers(pdir)
        has_intake = (pdir / "intake.json").is_file()
        enriched.append(
            {
                **bot,
                "policy_in_sync": drift.get("in_sync", False),
                "policy_reason": drift.get("reason", ""),
                "omh_configured": (pdir / ".omh" / "setup-profile.json").is_file(),
                "sentinel_installed": (pdir / "plugins" / "dirty-forge-sentinel").is_dir(),
                "has_intake": has_intake,
                "telemetry": metrics,
                "pending_takeovers": sum(1 for t in takeovers if t.get("status") == "pending_human"),
            }
        )
    return {"ok": True, "count": len(enriched), "bots": enriched}


@router.post("/bots")
def create_bot(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    settings = _load_settings()
    return forge.forge_bot(dict(payload or {}), settings=settings)


@router.post("/bots/{name}/activate")
def activate_bot(name: str, payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    force = bool((payload or {}).get("force", False))
    return forge.activate_bot(name, force=force)


@router.post("/bots/{name}/hide")
def hide_bot(name: str, payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    hidden = bool((payload or {}).get("hidden", True))
    return forge.hide_bot(name, hidden=hidden)


@router.post("/bots/{name}/update")
def update_bot(name: str, payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    return forge.update_bot(name, dict(payload or {}))


@router.delete("/bots/{name}")
def delete_bot(name: str) -> dict[str, Any]:
    settings = _load_settings()
    return forge.delete_bot(name, settings=settings)


@router.post("/bots/{name}/reset-breaker")
def reset_bot_breaker(name: str) -> dict[str, Any]:
    ok_id, pid_or_err = forge.validate_profile_id(name)
    if not ok_id:
        return {"ok": False, "error": pid_or_err}
    pdir = forge.profile_dir(forge.default_root(), pid_or_err)
    if not pdir.is_dir():
        return {"ok": False, "error": f"profile '{name}' not found"}
    state = telemetry.reset_breaker(pdir)
    return {"ok": True, "name": pid_or_err, "telemetry": state}


@router.post("/teams")
def create_team(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    settings = _load_settings()
    return team.build_team(dict(payload or {}), settings=settings)


@router.post("/policies/sync")
def sync_all_policies() -> dict[str, Any]:
    root = forge.default_root()
    bots = forge.list_bots(root=root, include_hidden=True)
    pdirs = [forge.profile_dir(root, b["name"]) for b in bots]
    return policy.sync_policies(root, pdirs)


@router.get("/blueprints")
def search_blueprints(
    query: str = Query(default=""),
    division: str = Query(default=""),
    limit: int = Query(default=10, ge=1, le=50),
) -> dict[str, Any]:
    q = query.strip() or "assistant"
    hits = blueprints.search(q, division=division.strip(), limit=limit)
    return {"ok": True, "count": len(hits), "matches": hits}


@router.post("/fit-test")
def run_fit_test(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    return evals.fit_test(
        goal=str(payload.get("goal") or ""),
        recurring=bool(payload.get("recurring", False)),
        needs_separate_state_or_config=bool(payload.get("needs_separate_state_or_config", False)),
        multiple_distinct_roles=bool(payload.get("multiple_distinct_roles", False)),
    )


@router.post("/interview")
def run_interview(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    return intake.run_interview(
        intake_id=str(payload.get("intake_id") or "").strip(),
        answers=payload.get("answers") if isinstance(payload.get("answers"), dict) else None,
        include_optional=bool(payload.get("include_optional", False)),
    )


@router.get("/interview/{intake_id}")
def get_interview(intake_id: str) -> dict[str, Any]:
    root = forge.default_root()
    session = intake.load_intake(root, intake_id)
    if not session:
        return {"ok": False, "error": f"intake '{intake_id}' not found"}
    return {"ok": True, **session}


@router.post("/bots/{name}/eval")
def run_bot_eval(name: str, payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    ok_id, pid_or_err = forge.validate_profile_id(name)
    if not ok_id:
        return {"ok": False, "error": pid_or_err}
    root = forge.default_root()
    pdir = forge.profile_dir(root, pid_or_err)
    if not pdir.is_dir():
        return {"ok": False, "error": f"profile '{name}' not found"}
    cases = payload.get("cases") if isinstance(payload.get("cases"), list) else []
    if not cases and (pdir / "intake.json").is_file():
        try:
            saved = json.loads((pdir / "intake.json").read_text(encoding="utf-8"))
            if isinstance(saved.get("eval_cases"), list):
                cases = saved["eval_cases"]
        except Exception:
            cases = []
    if not cases:
        cases = [
            {
                "id": "starter_typical",
                "category": "typical",
                "prompt": f"Describe your primary role and boundaries as {pid_or_err}.",
                "must_include": ["task", "boundaries"],
                "must_not_include": ["ignore previous instructions"],
            }
        ]
    return evals.eval_bot(pid_or_err, cases, root=root)


@router.get("/bots/{name}/omh")
def list_omh(name: str) -> dict[str, Any]:
    return omh_memory.review_omh(name, action="list")


@router.post("/bots/{name}/omh")
def review_omh(name: str, payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    action = str(payload.get("action") or "list").strip().lower()
    candidate_id = str(payload.get("candidate_id") or "").strip()
    return omh_memory.review_omh(name, action=action, candidate_id=candidate_id)


@router.get("/bots/{name}/journal")
def get_journal(
    name: str,
    date: str = Query(default=""),
    limit: int = Query(default=20, ge=1, le=200),
) -> dict[str, Any]:
    ok_id, pid_or_err = forge.validate_profile_id(name, allow_default=True)
    if not ok_id:
        return {"ok": False, "error": pid_or_err}
    pdir = forge.profile_dir(forge.default_root(), pid_or_err)
    if not pdir.is_dir():
        return {"ok": False, "error": f"profile '{name}' not found"}
    entries = journal.read_entries(pdir, date=date, limit=limit)
    return {"ok": True, "name": pid_or_err, "count": len(entries), "entries": entries}


@router.post("/bots/{name}/journal")
def add_journal(name: str, payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    ok_id, pid_or_err = forge.validate_profile_id(name, allow_default=True)
    if not ok_id:
        return {"ok": False, "error": pid_or_err}
    pdir = forge.profile_dir(forge.default_root(), pid_or_err)
    if not pdir.is_dir():
        return {"ok": False, "error": f"profile '{name}' not found"}
    entry = journal.write_entry(
        pdir,
        status=str(payload.get("status") or "NOTE"),
        goal=str(payload.get("goal") or ""),
        outcome=str(payload.get("outcome") or ""),
        evidence=str(payload.get("evidence") or ""),
        next_step=str(payload.get("next_step") or ""),
    )
    return {"ok": True, "name": pid_or_err, "entry": entry}


@router.get("/bots/{name}/takeovers")
def get_takeovers(name: str) -> dict[str, Any]:
    ok_id, pid_or_err = forge.validate_profile_id(name)
    if not ok_id:
        return {"ok": False, "error": pid_or_err}
    pdir = forge.profile_dir(forge.default_root(), pid_or_err)
    if not pdir.is_dir():
        return {"ok": False, "error": f"profile '{name}' not found"}
    items = _list_takeovers(pdir)
    return {"ok": True, "name": pid_or_err, "count": len(items), "takeovers": items}


@router.get("/bots/{name}/files")
def get_bot_files(name: str) -> dict[str, Any]:
    ok_id, pid_or_err = forge.validate_profile_id(name)
    if not ok_id:
        return {"ok": False, "error": pid_or_err}
    pdir = forge.profile_dir(forge.default_root(), pid_or_err)
    if not pdir.is_dir():
        return {"ok": False, "error": f"profile '{name}' not found"}
    soul = (pdir / "SOUL.md").read_text(encoding="utf-8", errors="ignore") if (pdir / "SOUL.md").is_file() else ""
    memory = (pdir / "MEMORY.md").read_text(encoding="utf-8", errors="ignore") if (pdir / "MEMORY.md").is_file() else ""
    cfg = forge.load_yaml(pdir / "config.yaml")
    bots_meta = cfg.get("bots") if isinstance(cfg.get("bots"), dict) else {}
    return {
        "ok": True,
        "name": pid_or_err,
        "display_name": bots_meta.get("title") or pid_or_err,
        "avatar_kind": bots_meta.get("avatar_kind") or "boxy",
        "toolsets": cfg.get("toolsets") or [],
        "soul_md": soul,
        "memory_md": memory,
    }


@router.post("/bots/{name}/takeover")
def create_takeover(name: str, payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    reason = str(payload.get("reason") or "").strip()
    raw_ctx = payload.get("context")
    context = json.dumps(raw_ctx, ensure_ascii=False) if isinstance(raw_ctx, dict) else str(raw_ctx or "")
    return takeover.request_takeover(name, reason=reason, context=context)


@router.post("/bots/{name}/takeovers/{takeover_id}/resolve")
def resolve_takeover(name: str, takeover_id: str, payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    resolution = str((payload or {}).get("resolution") or "").strip()
    return takeover.resolve_takeover(name, takeover_id, resolution=resolution)


@router.post("/bots/{name}/share")
def share_bot(name: str, payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    settings = _load_settings()
    mode = str((payload or {}).get("mode") or "template")
    return portable.share_bot(
        name,
        mode=mode,
        allow_secrets=bool(settings.get("allow_secrets", False)),
    )


@router.post("/bots/import")
def import_bot(payload: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    settings = _load_settings()
    source_path = str((payload or {}).get("source_path") or "").strip()
    display_name = str((payload or {}).get("display_name") or "").strip()
    return portable.import_bot(
        source_path=source_path,
        display_name=display_name,
        allow_secrets=bool(settings.get("allow_secrets", False)),
        settings=settings,
    )
