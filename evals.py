"""Fit Test (smallest sufficient setup) and Bot Evaluation Gate for DirtyForge."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import forge, journal
from .sentinel import guard

_SKILL_ESCALATION_RE = re.compile(
    r"(ignore\s+(?:previous|all)\s+instructions|bypass\s+(?:approval|sentinel|guard)|"
    r"disable\s+approval|auto[- ]approve\s+all|override\s+SOUL)",
    re.I,
)


def scan_skill_safety(skill_md: str) -> list[str]:
    """Check SKILL.md content for prompt-injection / privilege-escalation instructions (arXiv:2610.08098)."""
    findings = guard.scan_secrets(skill_md)
    if _SKILL_ESCALATION_RE.search(skill_md or ""):
        findings.append("privilege_escalation_instruction")
    return findings


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]{3,}", (text or "").lower()))


def fit_test(
    goal: str,
    recurring: bool = False,
    needs_separate_state_or_config: bool = False,
    multiple_distinct_roles: bool = False,
    root: Path | None = None,
) -> dict[str, Any]:
    """5-question Fit Test returning the smallest sufficient Hermes setup before creating a Bot."""
    r = root or forge.default_root()
    existing = forge.list_bots(root=r, include_hidden=False)
    goal_tokens = _tokenize(goal)
    scored: list[tuple[int, str]] = []
    for b in existing:
        role_tokens = _tokenize(str(b.get("role") or ""))
        overlap = len(goal_tokens & role_tokens)
        if overlap > 0:
            scored.append((overlap, b["name"]))
    scored.sort(reverse=True)
    matching = [name for _, name in scored]

    if multiple_distinct_roles and needs_separate_state_or_config:
        rec = "team"
        reason = "Multiple distinct roles with separate state/configuration boundaries."
    elif needs_separate_state_or_config:
        rec = "single_bot"
        reason = "Persistent responsibility requiring isolated SOUL.md, memory, or toolset configuration."
    elif recurring:
        rec = "routine"
        reason = "Recurring work without needing a new Bot profile; attach a cron routine to an existing profile."
    elif matching:
        rec = "reuse_existing"
        reason = f"Existing Bot(s) ({', '.join(matching)}) appear to cover this domain; add a skill if needed."
    else:
        rec = "skill"
        reason = "A focused SKILL.md procedure (2-3 skills max) is sufficient without creating a new profile."

    task_card_template = {
        "role_and_one_result": "",
        "target_user": "",
        "inputs": "",
        "exact_output_format": "",
        "out_of_scope": "",
        "sources_of_truth": "",
        "forbidden_tools": "",
        "requires_approval": ["send", "spend", "destroy"],
        "escalate_when": "",
        "good_example": "",
        "bad_example_to_avoid": "",
    }
    return {
        "ok": True,
        "recommendation": rec,
        "reason": reason,
        "matching_existing_bots": matching,
        "recommended_max_skills": 3,
        "task_card_template": task_card_template,
    }


def eval_bot(
    name: str,
    cases: list[dict[str, Any]],
    root: Path | None = None,
) -> dict[str, Any]:
    """Run controlled pass/fail evaluation cases against a Bot and save the audit report."""
    r = root or forge.default_root()
    ok_id, pid_or_err = forge.validate_profile_id(name, allow_default=False)
    if not ok_id:
        return {"ok": False, "error": pid_or_err}
    pid = pid_or_err
    pdir = forge.profile_dir(r, pid)
    if not pdir.is_dir():
        return {"ok": False, "error": f"Bot '{name}' not found"}
    if not cases:
        return {"ok": False, "error": "at least one evaluation case is required"}

    cfg = forge.load_yaml(pdir / "config.yaml")
    sentinel_pol = cfg.get("dirty-forge-sentinel") or {"approve_categories": ["send", "spend", "destroy"]}
    enabled_toolsets = set(cfg.get("toolsets") or [])
    hermes_bin = shutil.which("hermes")
    timeout_sec = max(30.0, forge.core_tool_deadline(r) - forge.DEADLINE_MARGIN)

    results: list[dict[str, Any]] = []
    passed = 0
    for idx, case in enumerate(cases[:20]):
        cid = str(case.get("id") or f"case-{idx + 1}")
        kind = str(case.get("kind") or "typical")
        prompt = str(case.get("prompt") or "").strip()
        expected_tool = str(case.get("expected_sentinel_tool") or "").strip()

        if kind == "unauthorized_action" and expected_tool:
            verdict = guard.evaluate(expected_tool, case.get("tool_args") or {}, sentinel_pol)
            tool_l = expected_tool.lower()
            layered_blocked = tool_l not in enabled_toolsets
            ok = (verdict is not None and verdict.get("action") in ("approve", "block")) or layered_blocked
            results.append(
                {
                    "id": cid,
                    "kind": kind,
                    "passed": ok,
                    "sentinel_verdict": verdict,
                    "toolset_withheld": layered_blocked,
                }
            )
            if ok:
                passed += 1
            continue

        if not hermes_bin:
            results.append({"id": cid, "kind": kind, "passed": False, "error": "hermes CLI unavailable"})
            continue

        try:
            proc = subprocess.run(
                [hermes_bin, "-p", pid, "chat", "-q", prompt],
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
            reply = (proc.stdout or proc.stderr or "").strip()
            must_contain = [str(s).lower() for s in (case.get("must_contain") or [])]
            must_not = [str(s).lower() for s in (case.get("must_not_contain") or [])]
            reply_l = reply.lower()
            ok = (
                proc.returncode == 0
                and all(m in reply_l for m in must_contain)
                and all(m not in reply_l for m in must_not)
            )
            if ok:
                passed += 1
            results.append({"id": cid, "kind": kind, "passed": ok, "reply_excerpt": reply[:400]})
        except Exception as exc:
            results.append({"id": cid, "kind": kind, "passed": False, "error": str(exc)})

    report = {
        "bot": pid,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total": len(results),
        "passed": passed,
        "pass_rate": round(passed / len(results), 3) if results else 0.0,
        "results": results,
    }
    evals_dir = pdir / "evals"
    evals_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = evals_dir / f"eval-{stamp}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    journal.write_entry(
        pdir,
        status="completed" if passed == len(results) else "progress",
        goal="Bot evaluation gate",
        outcome=f"Passed {passed}/{len(results)} cases ({report['pass_rate'] * 100:.1f}%).",
        evidence=str(report_path),
    )
    return {"ok": True, **report, "report_path": str(report_path)}
