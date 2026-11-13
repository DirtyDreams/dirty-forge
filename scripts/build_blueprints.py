#!/usr/bin/env python3
"""Build data/blueprints.json from the agency-agents catalog."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

DEFAULT_AGENCY_ROOT = Path(__file__).resolve().parents[2] / "agency-agents"
DEFAULT_OUT = Path(__file__).resolve().parents[1] / "data" / "blueprints.json"

_SOUL_HEADER_RE = re.compile(
    r"(identity|learning.*memory|communication|style|critical.rule|rules.you.must.follow)",
    re.I,
)


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def split_sections(body: str) -> tuple[str, str]:
    soul_parts: list[str] = []
    mission_parts: list[str] = []
    current_target = mission_parts
    for line in body.splitlines(keepends=True):
        if line.startswith("## "):
            current_target = soul_parts if _SOUL_HEADER_RE.search(line) else mission_parts
        current_target.append(line)
    return "".join(soul_parts).strip(), "".join(mission_parts).strip()


def parse_agent(path: Path, agency_root: Path) -> dict[str, Any] | None:
    text = path.read_text(encoding="utf-8", errors="ignore")
    if not text.startswith("---\n"):
        return None
    parts = text.split("---\n", 2)
    if len(parts) < 3:
        return None
    fields: dict[str, str] = {}
    for line in parts[1].splitlines():
        if ":" not in line or line.startswith((" ", "\t")):
            continue
        k, v = line.split(":", 1)
        fields[k.strip()] = v.strip().strip('"').strip("'")
    name = fields.get("name", "").strip()
    if not name:
        return None
    rel = path.relative_to(agency_root)
    soul_sec, mission_sec = split_sections(parts[2].lstrip("\n"))
    return {
        "slug": slugify(name),
        "name": name,
        "division": rel.parts[0],
        "description": fields.get("description", "").strip(),
        "vibe": fields.get("vibe", "").strip(),
        "emoji": fields.get("emoji", "").strip(),
        "color": fields.get("color", "").strip(),
        "source_path": str(rel),
        "soul_excerpt": soul_sec[:3500],
        "mission_excerpt": mission_sec[:3500],
    }


def build(agency_root: Path, out_path: Path) -> int:
    divisions_file = agency_root / "divisions.json"
    if not divisions_file.is_file():
        raise SystemExit(f"divisions.json not found at {divisions_file}")
    divisions = sorted(json.loads(divisions_file.read_text(encoding="utf-8"))["divisions"].keys())
    blueprints: list[dict[str, Any]] = []
    seen: set[str] = set()
    for div in divisions:
        div_dir = agency_root / div
        if not div_dir.is_dir():
            continue
        for md in sorted(div_dir.rglob("*.md")):
            parsed = parse_agent(md, agency_root)
            if parsed and parsed["slug"] not in seen:
                seen.add(parsed["slug"])
                blueprints.append(parsed)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(blueprints, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(blueprints)} blueprints to {out_path}")
    return len(blueprints)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build DirtyForge blueprints.json from agency-agents.")
    parser.add_argument("--agency-root", type=Path, default=DEFAULT_AGENCY_ROOT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    build(args.agency_root, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
