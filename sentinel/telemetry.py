"""Profile-scoped tool telemetry and circuit breaker for DirtyForge Bots."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_MAX_CALLS = 40
DEFAULT_MAX_ERRORS = 5


def _telemetry_dir(profile_dir: Path) -> Path:
    d = profile_dir / "telemetry"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _state_path(profile_dir: Path) -> Path:
    return _telemetry_dir(profile_dir) / "state.json"


def _metrics_path(profile_dir: Path) -> Path:
    return _telemetry_dir(profile_dir) / "metrics.jsonl"


def _load_state(profile_dir: Path) -> dict[str, Any]:
    path = _state_path(profile_dir)
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {
        "total_calls": 0,
        "total_errors": 0,
        "consecutive_errors": 0,
        "breaker_tripped": False,
        "trip_reason": "",
        "last_updated": "",
    }


def _save_state(profile_dir: Path, state: dict[str, Any]) -> None:
    _state_path(profile_dir).write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def record_tool_event(
    profile_dir: Path,
    tool_name: str,
    ok: bool,
    error_msg: str = "",
    max_calls: int = DEFAULT_MAX_CALLS,
    max_errors: int = DEFAULT_MAX_ERRORS,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    state = _load_state(profile_dir)
    state["total_calls"] = int(state.get("total_calls", 0)) + 1
    if ok:
        state["consecutive_errors"] = 0
    else:
        state["total_errors"] = int(state.get("total_errors", 0)) + 1
        state["consecutive_errors"] = int(state.get("consecutive_errors", 0)) + 1

    if max_calls > 0 and state["total_calls"] >= max_calls:
        state["breaker_tripped"] = True
        state["trip_reason"] = f"max_calls reached ({state['total_calls']}/{max_calls})"
    elif max_errors > 0 and state["consecutive_errors"] >= max_errors:
        state["breaker_tripped"] = True
        state["trip_reason"] = f"max_consecutive_errors reached ({state['consecutive_errors']}/{max_errors})"

    state["last_updated"] = now
    _save_state(profile_dir, state)

    event = {
        "ts": now,
        "tool": tool_name,
        "ok": bool(ok),
        "error": (error_msg or "")[:300],
    }
    with _metrics_path(profile_dir).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    return state


def get_metrics(profile_dir: Path) -> dict[str, Any]:
    state = _load_state(profile_dir)
    recent: list[dict[str, Any]] = []
    mpath = _metrics_path(profile_dir)
    if mpath.is_file():
        lines = mpath.read_text(encoding="utf-8", errors="ignore").splitlines()[-20:]
        for line in lines:
            try:
                recent.append(json.loads(line))
            except Exception:
                pass
    return {**state, "recent_events": recent}


def reset_breaker(profile_dir: Path) -> dict[str, Any]:
    state = _load_state(profile_dir)
    state["consecutive_errors"] = 0
    state["total_calls"] = 0
    state["breaker_tripped"] = False
    state["trip_reason"] = ""
    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    _save_state(profile_dir, state)
    return state
