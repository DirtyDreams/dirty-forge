"""DirtyForge Sentinel sub-plugin: enforces policy at pre_tool_call."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from . import guard


def _read_config(ctx: Any, key: str, default: Any = None) -> Any:
    if hasattr(ctx, "get_config"):
        return ctx.get_config(key, default=default)
    hermes_home = Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser()
    cfg_path = hermes_home / "config.yaml"
    if cfg_path.is_file():
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        node = data.get("dirty-forge-sentinel") or {}
        if isinstance(node, dict) and key in node:
            return node[key]
    return default


def register(ctx: Any) -> None:
    def on_pre_tool_call(
        tool_name: str = "",
        args: dict[str, Any] | None = None,
        arguments: dict[str, Any] | None = None,
        **kwargs: Any,
    ):
        effective_args = args if args is not None else arguments
        policy = _read_config(ctx, "sentinel_policy", default=None)
        if policy is None:
            policy = {
                "approve_categories": _read_config(ctx, "approve_categories", default=["send", "spend", "destroy"]),
                "approve_tools": _read_config(ctx, "approve_tools", default=[]),
                "block": _read_config(ctx, "block", default=[]),
                "limits": _read_config(ctx, "limits", default={}),
            }
        return guard.evaluate(tool_name, effective_args, policy)

    ctx.register_hook("pre_tool_call", on_pre_tool_call)
