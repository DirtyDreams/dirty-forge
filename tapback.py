"""Hermes Desktop tapback reaction hooks (pre_llm_call / post_llm_call)."""
from __future__ import annotations

from typing import Any, Callable


class Tapback:
    """Places non-intrusive status reactions on Desktop user messages."""

    def __init__(self, ctx: Any, is_enabled: Callable[[], bool]) -> None:
        self._ctx = ctx
        self._is_enabled = is_enabled

    def _react(self, emoji: str, **kwargs: Any) -> None:
        if not self._is_enabled():
            return
        react_fn = getattr(self._ctx, "react_to_message", None)
        if callable(react_fn):
            try:
                react_fn(emoji=emoji, message_id=kwargs.get("message_id"))
            except Exception:
                pass

    def on_turn_start(self, **kwargs: Any) -> None:
        self._react("👀", **kwargs)

    def on_turn_end(self, **kwargs: Any) -> None:
        if kwargs.get("error"):
            self._react("⚠️", **kwargs)
        elif kwargs.get("awaiting_approval"):
            self._react("✋", **kwargs)
        else:
            self._react("✅", **kwargs)
