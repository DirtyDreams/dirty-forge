"""Human takeover requests and opt-in external CLI delegation for DirtyForge."""
from __future__ import annotations

import json
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import forge, journal
from .sentinel.guard import redact_text, scan_prompt_injection, scan_secrets

DEFAULT_ALLOWED_CLIS = ("codex", "claude", "aider")


def request_takeover(
    name: str,
    reason: str,
    context: str = "",
    root: Path | None = None,
) -> dict[str, Any]:
    r = root or forge.default_root()
    ok_id, pid_or_err = forge.validate_profile_id(name, allow_default=False)
    if not ok_id:
        return {"ok": False, "error": pid_or_err}
    pid = pid_or_err
    pdir = forge.profile_dir(r, pid)
    if not pdir.is_dir():
        return {"ok": False, "error": f"Bot '{name}' not found"}
    clean_reason = (reason or "").strip()
    if not clean_reason:
        return {"ok": False, "error": "reason is required"}

    tdir = pdir / "takeovers"
    tdir.mkdir(parents=True, exist_ok=True)
    tid = f"to-{uuid.uuid4().hex[:10]}"
    record = {
        "id": tid,
        "bot": pid,
        "status": "pending_human",
        "reason": redact_text(clean_reason)[:1000],
        "context": redact_text(context or "")[:4000],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    path = tdir / f"{tid}.json"
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    journal.write_entry(
        pdir,
        status="blocked",
        goal=f"Human takeover requested ({tid})",
        outcome=clean_reason[:300],
        evidence=str(path),
        next_step="Operator review required",
    )
    return {"ok": True, "takeover_id": tid, "bot": pid, "status": "pending_human", "path": str(path)}


def delegate_outside(
    cli: str,
    task: str,
    cwd: str = "",
    settings: dict[str, Any] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    settings = settings or {}
    if not settings.get("allow_external_delegation", False):
        return {"ok": False, "error": "delegate_outside is disabled (set allow_external_delegation: true in plugin config)"}

    cli_name = (cli or "").strip()
    if not cli_name or "/" in cli_name or "\\" in cli_name:
        return {"ok": False, "error": "cli must be a plain executable name (no path separators)"}
    allowed_raw = settings.get("allowed_external_clis") or list(DEFAULT_ALLOWED_CLIS)
    allowed = {str(x).strip().lower() for x in allowed_raw if str(x).strip()}
    if cli_name.lower() not in allowed:
        return {"ok": False, "error": f"cli '{cli_name}' is not in allowed_external_clis ({sorted(allowed)})"}

    clean_task = (task or "").strip()
    if not clean_task:
        return {"ok": False, "error": "task is required"}
    sec = scan_secrets(clean_task)
    if sec:
        return {"ok": False, "error": f"delegation blocked: secret pattern detected ({', '.join(sec)})"}
    inj = scan_prompt_injection(clean_task)
    if inj:
        return {"ok": False, "error": f"delegation blocked: prompt injection pattern detected ({', '.join(inj)})"}

    bin_path = shutil.which(cli_name)
    if not bin_path:
        return {"ok": False, "error": f"external CLI '{cli_name}' not found on PATH"}

    work_dir = Path(cwd).expanduser() if cwd else Path.cwd()
    if not work_dir.is_dir():
        return {"ok": False, "error": f"working directory not found: {cwd}"}

    r = root or forge.default_root()
    timeout_sec = min(120.0, max(30.0, forge.core_tool_deadline(r) - forge.DEADLINE_MARGIN))
    try:
        proc = subprocess.run(
            [bin_path, clean_task],
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            shell=False,
        )
        out = redact_text((proc.stdout or proc.stderr or "").strip())[-4000:]
        return {"ok": proc.returncode == 0, "cli": cli_name, "returncode": proc.returncode, "output": out}
    except subprocess.TimeoutExpired:
        return {"ok": False, "cli": cli_name, "error": f"timed out after {timeout_sec:.0f}s"}
    except Exception as exc:
        return {"ok": False, "cli": cli_name, "error": str(exc)}
