"""DirtyForge Sentinel sub-plugin: enforces policy at pre_tool_call."""
from __future__ import annotations

from typing import Any

from . import guard


def register(ctx: Any) -> None:
    def on_pre_tool_call(tool_name: str = "", arguments: dict[str, Any] | None = None, **kwargs: Any):
        policy = ctx.get_config("sentinel_policy", default=None)
        if policy is None:
            policy = {
                "approve_categories": ctx.get_config("approve_categories", default=["send", "spend", "destroy"]),
                "approve_tools": ctx.get_config("approve_tools", default=[]),
                "block": ctx.get_config("block", default=[]),
                "limits": ctx.get_config("limits", default={}),
            }
        return guard.evaluate(tool_name, arguments, policy)

    ctx.register_hook("pre_tool_call", on_pre_tool_call)
