"""Hermes Desktop tapback reaction hooks (pre_llm_call / post_llm_call)."""
from __future__ import annotations

from typing import Any, Callable


class Tapback:
    """Places non-intrusive status reactions on Desktop user messages, with ack-prefix fallback."""

    def __init__(self, ctx: Any, is_enabled: Callable[[], bool]) -> None:
        self._ctx = ctx
        self._is_enabled = is_enabled
        self.last_ack: str = ""

    def _react(self, emoji: str, **kwargs: Any) -> dict[str, str] | None:
        if not self._is_enabled():
            return None
        self.last_ack = emoji
        react_fn = getattr(self._ctx, "react_to_message", None)
        if callable(react_fn):
            try:
                react_fn(emoji=emoji, message_id=kwargs.get("message_id"))
                return None
            except Exception:
                pass
        return {"ack_prefix": emoji}

    def on_turn_start(self, **kwargs: Any) -> dict[str, str] | None:
        return self._react("👀", **kwargs)

    def on_turn_end(self, **kwargs: Any) -> dict[str, str] | None:
        if kwargs.get("error"):
            return self._react("⚠️", **kwargs)
        if kwargs.get("awaiting_approval"):
            return self._react("✋", **kwargs)
        return self._react("✅", **kwargs)
