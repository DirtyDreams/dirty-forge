"""Lazy-router over data/blueprints.json for DirtyForge."""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any

_DATA_PATH = Path(__file__).parent / "data" / "blueprints.json"
_BLUEPRINTS: list[dict[str, Any]] | None = None
_WORD_RE = re.compile(r"[a-z0-9][a-z0-9+.#_-]*", re.I)


def _load() -> list[dict[str, Any]]:
    global _BLUEPRINTS
    if _BLUEPRINTS is None:
        if not _DATA_PATH.is_file():
            _BLUEPRINTS = []
        else:
            _BLUEPRINTS = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    return _BLUEPRINTS


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _WORD_RE.findall(text or "")}


def _score(bp: dict[str, Any], q_tokens: set[str], q_text: str) -> float:
    haystack = "\n".join(
        [
            bp.get("name", ""),
            bp.get("description", ""),
            bp.get("division", ""),
            bp.get("vibe", ""),
            bp.get("soul_excerpt", "")[:2000],
            bp.get("mission_excerpt", "")[:2000],
        ]
    ).lower()
    h_tokens = _tokens(haystack)
    overlap = q_tokens & h_tokens
    score = float(len(overlap))
    if q_text and q_text in haystack:
        score += 5.0
    name = bp.get("name", "").lower()
    desc = bp.get("description", "").lower()
    for tok in q_tokens:
        if tok in name:
            score += 3.0
        if tok in desc:
            score += 1.5
    if score == 0.0:
        return 0.0
    return score + (1.0 / math.sqrt(max(len(h_tokens), 1)))


def search(query: str, division: str = "", limit: int = 5) -> list[dict[str, Any]]:
    q_text = (query or "").strip().lower()
    q_tokens = _tokens(q_text)
    if not q_tokens:
        return []
    div_filter = (division or "").strip().lower()
    scored: list[tuple[float, dict[str, Any]]] = []
    for bp in _load():
        if div_filter and bp.get("division", "").lower() != div_filter:
            continue
        s = _score(bp, q_tokens, q_text)
        if s > 0:
            scored.append((s, bp))
    scored.sort(key=lambda item: (-item[0], item[1]["slug"]))
    cap = max(1, min(int(limit or 5), 15))
    return [
        {
            "slug": bp["slug"],
            "name": bp["name"],
            "division": bp["division"],
            "description": bp.get("description", ""),
            "vibe": bp.get("vibe", ""),
            "score": round(s, 3),
        }
        for s, bp in scored[:cap]
    ]


def lookup(slug_or_name: str) -> dict[str, Any] | None:
    needle = (slug_or_name or "").strip().lower()
    if not needle:
        return None
    slug = re.sub(r"[^a-z0-9]+", "-", needle).strip("-")
    for bp in _load():
        if bp["slug"] == slug or bp["name"].lower() == needle:
            return bp
    return None
