"""Append-only daily work journals for DirtyForge Bots."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .sentinel.guard import scan_secrets

JOURNAL_MARKER = "<!-- dirty-forge-journal:v1 -->"
JOURNAL_POLICY = f"""{JOURNAL_MARKER}
## Work journal & metacognition
- After meaningful work, use `dirty_forge_journal` to record the goal, outcome, evidence, and next step.
- Journal completed work, material decisions, failures, and blockers. Skip routine chatter.
- When you discover a reusable lesson or user preference, update memory rather than duplicating entries.
- Never store credentials, private reasoning, or secrets in the journal.
"""

STATUSES = {"planned", "progress", "completed", "blocked", "failed"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def inject_journal_policy(soul_md: str) -> str:
    if JOURNAL_MARKER in soul_md:
        return soul_md
    return soul_md.rstrip() + "\n\n" + JOURNAL_POLICY


def journal_dir(profile_dir: Path) -> Path:
    d = profile_dir / "journal"
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_entry(
    profile_dir: Path,
    status: str,
    goal: str,
    outcome: str,
    evidence: str = "",
    next_step: str = "",
) -> dict[str, Any]:
    status_l = (status or "").strip().lower()
    if status_l not in STATUSES:
        return {"ok": False, "error": f"invalid status '{status}'; expected one of {sorted(STATUSES)}"}
    combined = "\n".join([goal, outcome, evidence, next_step])
    secrets = scan_secrets(combined)
    if secrets:
        return {"ok": False, "error": f"refused to write journal entry: secret pattern detected ({', '.join(secrets)})"}

    now = datetime.now(timezone.utc)
    day = now.strftime("%Y-%m-%d")
    stamp = now.strftime("%H:%M:%SZ")
    path = journal_dir(profile_dir) / f"{day}.md"
    lines = [
        f"## [{stamp}] {status_l.upper()} — {goal.strip()[:300]}",
        f"- **Outcome:** {outcome.strip()[:2000]}",
    ]
    if evidence.strip():
        lines.append(f"- **Evidence:** {evidence.strip()[:1000]}")
    if next_step.strip():
        lines.append(f"- **Next step:** {next_step.strip()[:500]}")
    entry = "\n".join(lines) + "\n\n"

    with path.open("a", encoding="utf-8") as fh:
        fh.write(entry)
    return {"ok": True, "file": str(path), "date": day, "status": status_l}


def read_entries(profile_dir: Path, date: str = "", limit: int = 20) -> dict[str, Any]:
    jdir = profile_dir / "journal"
    if not jdir.is_dir():
        return {"ok": True, "entries": []}
    if date:
        if not DATE_RE.match(date):
            return {"ok": False, "error": "date must be YYYY-MM-DD"}
        files = [jdir / f"{date}.md"] if (jdir / f"{date}.md").is_file() else []
    else:
        files = sorted(jdir.glob("*.md"), reverse=True)[:5]

    blocks: list[str] = []
    for f in files:
        text = f.read_text(encoding="utf-8", errors="ignore")
        for chunk in text.split("\n## "):
            chunk = chunk.strip()
            if chunk:
                blocks.append(("## " + chunk) if not chunk.startswith("## ") else chunk)
    return {"ok": True, "entries": blocks[: max(1, min(limit, 50))]}
