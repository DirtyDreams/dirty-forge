"""Deterministic pre_tool_call gate and secret hygiene for DirtyForge Bots."""
from __future__ import annotations

import re
from typing import Any

SEND = ("send", "post", "publish", "email", "mail", "tweet", "message", "reply", "comment")
SPEND = ("pay", "buy", "purchase", "charge", "checkout", "order", "transfer", "withdraw")
DESTROY = ("delete", "destroy", "remove", "drop", "purge", "wipe", "truncate")

CATEGORIES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("send, post or publish", SEND),
    ("spend money", SPEND),
    ("delete data", DESTROY),
)

SHELL_TOOL_NAMES = {"terminal", "bash", "shell", "execute_command", "run_command", "code_execution"}

_CMD_INJECTION_PATTERNS = (
    re.compile(r"\$\([^)]+\)"),
    re.compile(r"`[^`]+`"),
    re.compile(r"(?:^|[;&|])\s*(?:curl|wget|nc|ncat|socat)\b[^|]*\|\s*(?:sh|bash|zsh|python\d?)\b", re.I),
    re.compile(r"\bbase64\s+(?:-d|--decode)\b[^|]*\|\s*(?:sh|bash|zsh)\b", re.I),
    re.compile(r"(?:^|[;&|])\s*eval\s+", re.I),
    re.compile(r"(?:^|[;&|])\s*rm\s+-rf\s+/(?:\s|$)", re.I),
)

_SECRET_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgho_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
)

_PROMPT_INJECTION_PATTERNS = (
    ("ignore_instructions", re.compile(r"\bignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions\b", re.I)),
    ("system_prompt_override", re.compile(r"\b(?:override|replace|disregard)\s+(?:the\s+)?(?:system\s+prompt|soul\.md|policy)\b", re.I)),
    ("bypass_guardrails", re.compile(r"\b(?:bypass|disable|turn\s+off)\s+(?:sentinel|approval|guardrails?)\b", re.I)),
    ("secret_exfiltration", re.compile(r"\b(?:exfiltrate|leak|dump|print)\s+(?:all\s+)?(?:api\s*keys?|tokens?|secrets?|credentials?|\.env)\b", re.I)),
    ("hidden_html_directive", re.compile(r"<!--[^>]*(?:ignore|override|bypass|system)[^>]*-->", re.I)),
)


def scan_secrets(text: str) -> list[str]:
    """Return a list of matched secret pattern labels without leaking the secret itself."""
    if not text:
        return []
    findings: list[str] = []
    labels = (
        "openai_or_api_key",
        "github_pat",
        "github_oauth",
        "aws_access_key",
        "private_key_block",
        "slack_token",
    )
    for label, pattern in zip(labels, _SECRET_PATTERNS):
        if pattern.search(text):
            findings.append(label)
    return findings


def scan_prompt_injection(text: str) -> list[str]:
    """Detect indirect prompt-injection / memory-poisoning patterns (OWASP Agentic 2026)."""
    if not text:
        return []
    return [label for label, pat in _PROMPT_INJECTION_PATTERNS if pat.search(text)]


def redact_text(text: str, ctx: Any = None) -> str:
    """Scrub secrets via Hermes ctx.redact_text() when available, falling back to regex redaction."""
    if not text:
        return ""
    if ctx is not None and callable(getattr(ctx, "redact_text", None)):
        try:
            return str(ctx.redact_text(text))
        except Exception:
            pass
    out = text
    for pat in _SECRET_PATTERNS:
        out = pat.sub("[REDACTED]", out)
    return out


def detect_command_injection(tool: str, args: dict[str, Any] | None) -> str | None:
    """Detect shell subshell/pipe-to-shell/destructive root patterns in terminal-like tools."""
    if not args or not isinstance(args, dict):
        return None
    tool_l = tool.lower()
    if tool_l not in SHELL_TOOL_NAMES and "shell" not in tool_l and "terminal" not in tool_l:
        return None
    cmd = str(args.get("command") or args.get("cmd") or args.get("script") or "")
    if not cmd:
        return None
    for pat in _CMD_INJECTION_PATTERNS:
        if pat.search(cmd):
            return f"Blocked potential command injection / destructive shell pattern in `{tool}`."
    return None


def _normalise(names: Any) -> frozenset[str]:
    if not isinstance(names, (list, tuple)):
        return frozenset()
    return frozenset(n.strip().lower() for n in names if isinstance(n, str) and n.strip())


def _category(tool: str) -> str | None:
    parts = set(tool.lower().replace("-", "_").replace(".", "_").split("_"))
    for label, words in CATEGORIES:
        if parts & set(words):
            return label
    return None


def _values(value: Any) -> list[str] | None:
    if isinstance(value, str):
        return [value.strip().lower()] if value.strip() else []
    if isinstance(value, (list, tuple)):
        out: list[str] = []
        for item in value:
            if not isinstance(item, str) or not item.strip():
                return None
            out.append(item.strip().lower())
        return out
    return None


def _limit_verdict(tool: str, args: dict[str, Any] | None, policy: dict[str, Any]) -> dict[str, str] | None:
    limits = policy.get("limits")
    if not isinstance(limits, dict):
        return None
    tool_limits = limits.get(tool) or limits.get(tool.lower())
    if not isinstance(tool_limits, dict):
        return None
    args = args if isinstance(args, dict) else {}
    for arg_name, allowed_raw in tool_limits.items():
        allowed = _normalise(allowed_raw)
        if not allowed:
            continue
        passed = _values(args.get(arg_name))
        if passed is None or not passed or any(v not in allowed for v in passed):
            return {
                "action": "block",
                "message": f"Sentinel blocked `{tool}`: `{arg_name}` is outside allowed policy limits.",
            }
    return None


def evaluate(tool: str, args: dict[str, Any] | None, policy: dict[str, Any] | None) -> dict[str, str] | None:
    """Return a Hermes pre_tool_call directive: block, approve, or None."""
    policy = policy if isinstance(policy, dict) else {}
    blocked = _normalise(policy.get("block"))
    if tool.lower() in blocked:
        return {"action": "block", "message": f"Sentinel blocked `{tool}` per Bot policy."}

    injection_msg = detect_command_injection(tool, args)
    if injection_msg:
        return {"action": "block", "message": injection_msg}

    limit_hit = _limit_verdict(tool, args, policy)
    if limit_hit:
        return limit_hit

    approve_tools = _normalise(policy.get("approve_tools"))
    if tool.lower() in approve_tools:
        return {
            "action": "approve",
            "message": f"`{tool}` requires operator approval.",
            "rule_key": f"dirty_forge_sentinel:{tool.lower()}",
        }

    approve_cats = _normalise(policy.get("approve_categories"))
    cat = _category(tool)
    if cat:
        cat_aliases = {
            "send, post or publish": {"send", "post", "publish", "send, post or publish"},
            "spend money": {"spend", "spend money"},
            "delete data": {"destroy", "delete", "delete data"},
        }
        if approve_cats & cat_aliases.get(cat, {cat}):
            return {
                "action": "approve",
                "message": f"`{tool}` falls under `{cat}` and requires approval.",
                "rule_key": f"dirty_forge_sentinel:cat:{cat.split(',')[0].strip()}",
            }

    return None
