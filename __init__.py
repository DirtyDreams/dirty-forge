"""DirtyForge — Hermes Agent plugin for building complete, hardened Bots."""
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
    "allow_delete",
    "backup_before_delete",
)


def register(ctx: Any) -> None:
    def settings() -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k in _SETTINGS_KEYS:
            val = ctx.get_config(k, default=None)
            if val is not None:
                out[k] = val
        return out

    ctx.register_tool(
        name="dirty_forge_search_blueprints",
        toolset="dirty_forge",
        schema=schemas.SEARCH_BLUEPRINTS,
        handler=tools.search_blueprints,
        emoji="🔍",
        description="Search specialist blueprints and SOUL.md metaprompt guide",
    )
    ctx.register_tool(
        name="dirty_forge_create_bot",
        toolset="dirty_forge",
        schema=schemas.CREATE_BOT,
        handler=lambda args, **kw: tools.create_bot(args, settings=settings(), **kw),
        emoji="🧪",
        description="Provision a complete Hermes Bot profile",
    )
    ctx.register_tool(
        name="dirty_forge_list_bots",
        toolset="dirty_forge",
        schema=schemas.LIST_BOTS,
        handler=tools.list_bots,
        emoji="📋",
        description="List Hermes Bots on this machine",
    )
    ctx.register_tool(
        name="dirty_forge_update_bot",
        toolset="dirty_forge",
        schema=schemas.UPDATE_BOT,
        handler=tools.update_bot,
        emoji="✏️",
        description="Update an existing Bot",
    )
    ctx.register_tool(
        name="dirty_forge_check_bots",
        toolset="dirty_forge",
        schema=schemas.CHECK_BOTS,
        handler=tools.check_bots,
        emoji="🩺",
        description="Health & policy-drift check for all Bots",
    )
    ctx.register_tool(
        name="dirty_forge_journal",
        toolset="dirty_forge",
        schema=schemas.JOURNAL,
        handler=tools.agent_journal,
        emoji="📓",
        description="Read or write a Bot's work journal",
    )
    ctx.register_tool(
        name="dirty_forge_ask_bot",
        toolset="dirty_forge",
        schema=schemas.ASK_BOT,
        handler=tools.ask_bot,
        emoji="📨",
        description="Ask another Bot a question",
    )
    ctx.register_tool(
        name="dirty_forge_hide_bot",
        toolset="dirty_forge",
        schema=schemas.HIDE_BOT,
        handler=tools.hide_bot,
        emoji="🙈",
        description="Hide or unhide a Bot in the roster",
    )
    ctx.register_tool(
        name="dirty_forge_delete_bot",
        toolset="dirty_forge",
        schema=schemas.DELETE_BOT,
        handler=lambda args, **kw: tools.delete_bot(args, settings=settings(), **kw),
        emoji="🗑️",
        description="Delete a Bot (off unless enabled)",
    )

    if hasattr(ctx, "register_cli_command"):
        ctx.register_cli_command(
            name="dirty-forge-doctor",
            help="Check DirtyForge installation, blueprints, and Bots",
            setup_fn=lambda p: p.add_argument("--json", action="store_true", help="JSON output"),
            handler_fn=lambda a: doctor.cli(a, settings=settings()),
        )

    marks = tapback.Tapback(ctx, lambda: ctx.get_config("ack_tapback", default=True) is not False)
    ctx.register_hook("pre_llm_call", marks.on_turn_start)
    ctx.register_hook("post_llm_call", marks.on_turn_end)

    skills_dir = Path(__file__).parent / "skills"
    if skills_dir.is_dir() and hasattr(ctx, "register_skill"):
        for child in sorted(skills_dir.iterdir()):
            if child.is_dir() and (child / "SKILL.md").is_file():
                ctx.register_skill(child.name, child / "SKILL.md")
