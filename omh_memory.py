"""OMH project memory candidate review helper (.omh/memory/candidates -> records/reviews)."""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import forge


def review_omh(
    name: str,
    action: str = "list",
    candidate_id: str = "",
    root: Path | None = None,
) -> dict[str, Any]:
    r = root or forge.default_root()
    pid = forge.slugify_profile(name) if name != "default" else "default"
    pdir = forge.profile_dir(r, pid)
    if not pdir.is_dir():
        return {"ok": False, "error": f"Bot '{name}' not found"}

    omh_mem = pdir / ".omh" / "memory"
    cand_dir = omh_mem / "candidates"
    rec_dir = omh_mem / "records"
    rev_dir = omh_mem / "reviews"
    for d in (cand_dir, rec_dir, rev_dir):
        d.mkdir(parents=True, exist_ok=True)

    act = (action or "list").strip().lower()
    if act == "list":
        items: list[dict[str, Any]] = []
        for f in sorted(cand_dir.glob("*.json")):
            try:
                payload = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                payload = {"raw": f.name}
            items.append({"id": f.stem, "file": f.name, "data": payload})
        return {"ok": True, "bot": pid, "count": len(items), "candidates": items}

    if act not in ("approve", "reject"):
        return {"ok": False, "error": "action must be 'list', 'approve', or 'reject'"}
    if not candidate_id.strip():
        return {"ok": False, "error": "candidate_id is required for approve/reject"}

    cand_file = cand_dir / f"{candidate_id.strip()}.json"
    if not cand_file.is_file():
        return {"ok": False, "error": f"candidate '{candidate_id}' not found"}

    review_record = {
        "candidate_id": candidate_id.strip(),
        "decision": act,
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
        "reviewed_by": "dirty-forge",
    }
    (rev_dir / f"{candidate_id.strip()}.json").write_text(json.dumps(review_record, indent=2) + "\n", encoding="utf-8")

    if act == "approve":
        shutil.move(str(cand_file), str(rec_dir / cand_file.name))
        return {"ok": True, "bot": pid, "candidate_id": candidate_id.strip(), "status": "approved"}

    cand_file.unlink()
    return {"ok": True, "bot": pid, "candidate_id": candidate_id.strip(), "status": "rejected"}
