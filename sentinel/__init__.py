"""DirtyForge Sentinel sub-plugin: enforces policy at pre_tool_call."""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from . import guard, telemetry


def _active_profile_dir() -> Path:
    hermes_home = Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser()
    profile = os.environ.get("HERMES_PROFILE", "").strip()
    if profile and profile != "default":
        candidate = hermes_home / "profiles" / profile
        if candidate.is_dir():
            return candidate
    return hermes_home


def _read_config(ctx: Any, key: str, default: Any = None) -> Any:
    if hasattr(ctx, "get_config"):
        return ctx.get_config(key, default=default)
    cfg_path = _active_profile_dir() / "config.yaml"
    if not cfg_path.is_file():
        cfg_path = Path(os.environ.get("HERMES_HOME", "~/.hermes")).expanduser() / "config.yaml"
    if cfg_path.is_file():
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        node = data.get("dirty-forge-sentinel") or {}
        if isinstance(node, dict) and key in node:
            return node[key]
    return default


def _record_trip_takeover(pdir: Path, reason: str) -> None:
    tdir = pdir / "takeovers"
    tdir.mkdir(parents=True, exist_ok=True)
    tid = f"to-{uuid.uuid4().hex[:8]}"
    payload = {
        "id": tid,
        "status": "pending_human",
        "reason": f"Circuit breaker tripped: {reason}",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    (tdir / f"{tid}.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _result_is_error(result: Any) -> tuple[bool, str]:
    if isinstance(result, dict):
        if result.get("ok") is False or result.get("error"):
            return True, str(result.get("error") or "tool returned ok=false")
        return False, ""
    if isinstance(result, str):
        try:
            parsed = json.loads(result)
            if isinstance(parsed, dict) and (parsed.get("ok") is False or parsed.get("error")):
                return True, str(parsed.get("error") or "tool returned ok=false")
        except Exception:
            pass
    return False, ""


def register(ctx: Any) -> None:
    def on_pre_tool_call(
        tool_name: str = "",
        args: dict[str, Any] | None = None,
        arguments: dict[str, Any] | None = None,
        **kwargs: Any,
    ):
        pdir = _active_profile_dir()
        state = telemetry._load_state(pdir)
        if state.get("breaker_tripped"):
            return {
                "action": "block",
                "message": f"Circuit breaker tripped ({state.get('trip_reason')}). Call dirty_forge_bot_metrics with reset_breaker=true to resume.",
            }

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

    def on_post_tool_call(
        tool_name: str = "",
        result: Any = None,
        **kwargs: Any,
    ) -> None:
        pdir = _active_profile_dir()
        max_calls = int(_read_config(ctx, "circuit_breaker_max_calls", default=telemetry.DEFAULT_MAX_CALLS))
        max_errors = int(_read_config(ctx, "circuit_breaker_max_errors", default=telemetry.DEFAULT_MAX_ERRORS))
        is_err, err_msg = _result_is_error(result)
        was_tripped = bool(telemetry._load_state(pdir).get("breaker_tripped"))
        state = telemetry.record_tool_event(
            pdir,
            tool_name=tool_name,
            ok=not is_err,
            error_msg=err_msg,
            max_calls=max_calls,
            max_errors=max_errors,
        )
        if not was_tripped and state.get("breaker_tripped"):
            _record_trip_takeover(pdir, str(state.get("trip_reason") or "limit exceeded"))

    ctx.register_hook("pre_tool_call", on_pre_tool_call)
    ctx.register_hook("post_tool_call", on_post_tool_call)
