"""Task handoffs between DirtyForge Bots with secret scanning, journaling, and ack state tracking."""
from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import forge, journal
from .sentinel.guard import scan_prompt_injection, scan_secrets

MAX_TASK = 2_000
MAX_CONTEXT = 8_000
REPLY_KEEP = 4_000

_ACK_STATE = {
    "✅": "completed",
    "✋": "awaiting_approval",
    "⚠️": "blocked",
    "⏳": "scheduled",
}


def _reply_state(reply: str) -> str:
    stripped = (reply or "").lstrip()
    for emoji, state in _ACK_STATE.items():
        if stripped.startswith(emoji):
            return state
    return "replied"


def handoff_bot(spec: dict[str, Any], settings: dict[str, Any] | None = None) -> dict[str, Any]:
    root = Path(spec.get("hermes_root") or forge.default_root()).expanduser()
    to_id = forge.slugify_profile(str(spec.get("to") or ""))
    from_id = str(spec.get("from") or "default").strip() or "default"
    task = str(spec.get("task") or "").strip()[:MAX_TASK]
    context = str(spec.get("context") or "").strip()[:MAX_CONTEXT]

    if not to_id or not task:
        return {"ok": False, "error": "to and task are required"}
    to_dir = forge.profile_dir(root, to_id)
    if not to_dir.is_dir():
        return {"ok": False, "error": f"target Bot '{to_id}' not found"}

    secrets = scan_secrets(f"{task}\n{context}")
    if secrets:
        return {"ok": False, "error": f"handoff blocked: secret pattern detected ({', '.join(secrets)})"}
    inj = scan_prompt_injection(f"{task}\n{context}")
    if inj:
        return {"ok": False, "error": f"handoff blocked: prompt injection pattern detected ({', '.join(inj)})"}

    handoff_id = f"ho-{uuid.uuid4().hex[:10]}"
    handoffs_dir = to_dir / "handoffs"
    handoffs_dir.mkdir(parents=True, exist_ok=True)
    record: dict[str, Any] = {
        "id": handoff_id,
        "from": from_id,
        "to": to_id,
        "task": task,
        "context": context,
        "status": "open",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    record_path = handoffs_dir / f"{handoff_id}.json"

    from_dir = forge.profile_dir(root, from_id)
    if from_dir.is_dir():
        journal.write_entry(
            from_dir,
            status="progress",
            goal=f"Handoff to @{to_id}: {task[:120]}",
            outcome=f"Transferred ownership ({handoff_id}).",
        )

    hermes_bin = shutil.which("hermes")
    if not hermes_bin:
        record_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        return {"ok": True, "handoff_id": handoff_id, "status": "open", "note": "hermes CLI unavailable; queued"}

    prompt = (
        f"[HANDOFF {handoff_id} from @{from_id}]\n"
        f"You now own this task end-to-end:\n{task}\n"
    )
    if context:
        prompt += f"\nContext:\n{context}\n"

    timeout_sec = max(30.0, forge.core_tool_deadline(root) - forge.DEADLINE_MARGIN)
    try:
        proc = subprocess.run(
            [hermes_bin, "-p", to_id, "chat", "-q", prompt],
            capture_output=True,
            text=True,
            timeout=timeout_sec,
        )
        reply = (proc.stdout or proc.stderr or "").strip()[-REPLY_KEEP:]
        state = _reply_state(reply) if proc.returncode == 0 else "blocked"
        record["status"] = state
        record["reply_excerpt"] = reply[:1000]
        record["updated_at"] = datetime.now(timezone.utc).isoformat()
        record_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        journal.write_entry(
            to_dir,
            status="completed" if state == "completed" else ("blocked" if state == "blocked" else "progress"),
            goal=f"Handoff {handoff_id} from @{from_id}",
            outcome=reply[:500] or f"State: {state}",
        )
        return {"ok": proc.returncode == 0, "handoff_id": handoff_id, "to": to_id, "status": state, "reply": reply}
    except subprocess.TimeoutExpired:
        record["status"] = "timeout"
        record_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        return {"ok": False, "handoff_id": handoff_id, "status": "timeout", "error": f"timed out after {timeout_sec:.0f}s"}
    except Exception as exc:
        record["status"] = "error"
        record_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        return {"ok": False, "handoff_id": handoff_id, "error": str(exc)}
