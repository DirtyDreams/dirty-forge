"""DirtyForge — Hermes Agent plugin for building complete, hardened Bots and teams."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from . import doctor, schemas, tapback, tools

_SETTINGS_KEYS = (
    "inherit_model",
    "fallback_model",
    "probe_local_models",
    "omh_memory_mode",
    "inherit_plugins",
    "enforce_approvals",
    "journal_enabled",
    "ack_reactions",
    "ack_tapback",
    "workspace_survey",
    "workspace_roots",
    "install_gateway",
    "allow_secrets",
    "allow_delete",
    "backup_before_delete",
)


def _cfg_get(ctx: Any, key: str, default: Any = None) -> Any:
    if hasattr(ctx, "get_config"):
        return ctx.get_config(key, default=default)
    from . import forge

    cfg = forge.load_yaml(forge.default_root() / "config.yaml")
    plugin_cfg = cfg.get("dirty-forge") or cfg.get("dirty_forge") or {}
    if isinstance(plugin_cfg, dict) and key in plugin_cfg:
        return plugin_cfg[key]
    return default


def register(ctx: Any) -> None:
    def settings() -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k in _SETTINGS_KEYS:
            val = _cfg_get(ctx, k, default=None)
            if val is not None:
                out[k] = val
        return out

    tool_specs = (
        ("dirty_forge_search_blueprints", schemas.SEARCH_BLUEPRINTS, tools.search_blueprints, "🔍", "Search specialist blueprints and SOUL.md metaprompt guide", False),
        ("dirty_forge_create_bot", schemas.CREATE_BOT, tools.create_bot, "🧪", "Provision a complete Hermes Bot profile", True),
        ("dirty_forge_create_team", schemas.CREATE_TEAM, tools.create_team, "🧬", "Build a team of Bots with a lead", True),
        ("dirty_forge_list_bots", schemas.LIST_BOTS, tools.list_bots, "📋", "List Hermes Bots on this machine", False),
        ("dirty_forge_update_bot", schemas.UPDATE_BOT, tools.update_bot, "✏️", "Update an existing Bot", False),
        ("dirty_forge_copy_bot", schemas.COPY_BOT, tools.copy_bot, "👯", "Duplicate a Bot under a new name", True),
        ("dirty_forge_teach_bot", schemas.TEACH_BOT, tools.teach_bot, "🎓", "Teach a Bot a repeatable skill", False),
        ("dirty_forge_share_bot", schemas.SHARE_BOT, tools.share_bot, "📦", "Export a Bot as a template or backup", True),
        ("dirty_forge_import_bot", schemas.IMPORT_BOT, tools.import_bot, "📥", "Import a Bot from a template", True),
        ("dirty_forge_check_bots", schemas.CHECK_BOTS, tools.check_bots, "🩺", "Health & policy-drift check for all Bots", False),
        ("dirty_forge_sync_policies", schemas.SYNC_POLICIES, tools.sync_policies, "📜", "Propagate shared BOT-POLICY.md to drifted Bots", False),
        ("dirty_forge_omh_review", schemas.OMH_REVIEW, tools.omh_review, "🧠", "Review queued OMH memory candidates for a Bot", False),
        ("dirty_forge_journal", schemas.JOURNAL, tools.agent_journal, "📓", "Read or write a Bot's work journal", False),
        ("dirty_forge_ask_bot", schemas.ASK_BOT, tools.ask_bot, "📨", "Ask another Bot a question", False),
        ("dirty_forge_handoff_bot", schemas.HANDOFF_BOT, tools.handoff_bot, "🤝", "Hand off task ownership to another Bot", True),
        ("dirty_forge_hide_bot", schemas.HIDE_BOT, tools.hide_bot, "🙈", "Hide or unhide a Bot in the roster", False),
        ("dirty_forge_delete_bot", schemas.DELETE_BOT, tools.delete_bot, "🗑️", "Delete a Bot (off unless enabled)", True),
    )

    for name, schema, handler, emoji, desc, needs_settings in tool_specs:
        if needs_settings:
            bound = (lambda h: lambda args, **kw: h(args, settings=settings(), **kw))(handler)
        else:
            bound = handler
        ctx.register_tool(name=name, toolset="dirty_forge", schema=schema, handler=bound, emoji=emoji, description=desc)

    if hasattr(ctx, "register_cli_command"):
        ctx.register_cli_command(
            name="dirty-forge-doctor",
            help="Check DirtyForge installation, blueprints, and Bots",
            setup_fn=lambda p: p.add_argument("--json", action="store_true", help="JSON output"),
            handler_fn=lambda a: doctor.cli(a, settings=settings()),
        )

    marks = tapback.Tapback(ctx, lambda: _cfg_get(ctx, "ack_tapback", default=True) is not False)
    ctx.register_hook("pre_llm_call", marks.on_turn_start)
    ctx.register_hook("post_llm_call", marks.on_turn_end)

    skills_dir = Path(__file__).parent / "skills"
    if skills_dir.is_dir() and hasattr(ctx, "register_skill"):
        for child in sorted(skills_dir.iterdir()):
            if child.is_dir() and (child / "SKILL.md").is_file():
                ctx.register_skill(child.name, child / "SKILL.md")
