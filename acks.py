"""Status emoji acknowledgements for DirtyForge Bots."""
from __future__ import annotations

from pathlib import Path

ACK_MARKER = "<!-- dirty-forge-acks:v1 -->"

ACKS = [
    ("👀", "picked up the request and started working"),
    ("💬", "answering directly, no tool work needed first"),
    ("✅", "the work is finished"),
    ("✋", "needs user approval before proceeding"),
    ("⚠️", "blocked or an error occurred"),
    ("⏳", "scheduled for later instead of running now"),
]

ACK_POLICY = (
    f"{ACK_MARKER}\n"
    "## Say where the request stands\n"
    "Begin every reply with one emoji that shows the state of the user's request, "
    "followed by a space, then your answer as normal.\n\n"
    + "\n".join(f"- {emoji} — {meaning}" for emoji, meaning in ACKS)
    + "\n\n"
    "- One emoji at the very start, with no meta-commentary about reacting.\n"
    "- Never send the emoji alone as the entire reply.\n"
    "- If a single turn starts and finishes the work, use the end state (✅, ✋, or ⚠️).\n"
)


def acks_enabled(profile_dir: Path) -> bool:
    soul = profile_dir / "SOUL.md"
    return soul.exists() and ACK_MARKER in soul.read_text(encoding="utf-8", errors="ignore")


def inject_acks(soul_md: str) -> str:
    if ACK_MARKER in soul_md:
        return soul_md
    return soul_md.rstrip() + "\n\n" + ACK_POLICY
