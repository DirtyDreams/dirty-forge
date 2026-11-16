"""Snapshot, diff and rollback: no edit to a Bot may be unrecoverable."""

from __future__ import annotations

import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

PLUGIN_DIR = Path(__file__).resolve().parents[1]
if str(PLUGIN_DIR.parent) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR.parent))

spec = importlib.util.spec_from_file_location(
    "dirty_forge",
    PLUGIN_DIR / "__init__.py",
    submodule_search_locations=[str(PLUGIN_DIR)],
)
dirty_forge = importlib.util.module_from_spec(spec)
sys.modules["dirty_forge"] = dirty_forge
assert spec and spec.loader
spec.loader.exec_module(dirty_forge)

from dirty_forge import forge  # noqa: E402


class HistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / ".hermes"
        (self.root / "memories").mkdir(parents=True)
        (self.root / "config.yaml").write_text(yaml.safe_dump({"model": {"default": "gpt-4o"}}), encoding="utf-8")
        self._old_env = os.environ.get("HERMES_HOME")
        os.environ["HERMES_HOME"] = str(self.root)
        made = forge.forge_bot(
            {"display_name": "Wren", "role": "QA Reviewer", "one_job": "Review the code.", "soul_md": "# Wren\n\nv1\n"},
            settings={"install_gateway": False, "workspace_survey": False},
        )
        self.assertTrue(made["ok"], made.get("error"))
        self.pdir = Path(made["profile_dir"])
        self.original_soul = (self.pdir / "SOUL.md").read_text(encoding="utf-8")

    def tearDown(self) -> None:
        if self._old_env is None:
            os.environ.pop("HERMES_HOME", None)
        else:
            os.environ["HERMES_HOME"] = self._old_env
        self._tmp.cleanup()

    def test_edit_snapshots_and_returns_a_diff(self) -> None:
        res = forge.update_bot("wren", {"soul_append": "extra habit"})
        self.assertTrue(res["ok"], res.get("error"))
        self.assertIn("snapshot", res)
        self.assertIn("extra habit", res["diff"])
        self.assertIn("extra habit", (self.pdir / "SOUL.md").read_text(encoding="utf-8"))

    def test_soul_replace_replaces_instead_of_stacking(self) -> None:
        forge.update_bot("wren", {"soul_append": "old line"})
        res = forge.update_bot("wren", {"soul_replace": "# Wren\n\nclean\n"})
        self.assertTrue(res["ok"], res.get("error"))
        soul = (self.pdir / "SOUL.md").read_text(encoding="utf-8")
        self.assertIn("clean", soul)
        self.assertNotIn("old line", soul)

    def test_rollback_restores_byte_for_byte(self) -> None:
        forge.update_bot("wren", {"soul_append": "temporary line"})
        res = forge.rollback_bot("wren")
        self.assertTrue(res["ok"], res.get("error"))
        self.assertIn("SOUL.md", res["restored"])
        self.assertEqual((self.pdir / "SOUL.md").read_text(encoding="utf-8"), self.original_soul)

    def test_rollback_is_itself_undoable(self) -> None:
        forge.update_bot("wren", {"soul_append": "temporary line"})
        rolled = (self.pdir / "SOUL.md").read_text(encoding="utf-8")
        res = forge.rollback_bot("wren")
        self.assertTrue(res["ok"], res.get("error"))
        undo = res["undo_snapshot"]
        back = forge.rollback_bot("wren", stamp=undo)
        self.assertTrue(back["ok"], back.get("error"))
        self.assertEqual((self.pdir / "SOUL.md").read_text(encoding="utf-8"), rolled)

    def test_two_edits_in_one_second_get_separate_snapshots(self) -> None:
        first = forge.update_bot("wren", {"soul_append": "one"})["snapshot"]
        second = forge.update_bot("wren", {"soul_append": "two"})["snapshot"]
        self.assertNotEqual(first, second)
        snaps = [d.name for d in (self.pdir / "history").iterdir() if d.is_dir()]
        self.assertIn(first, snaps)
        self.assertIn(second, snaps)

    def test_incomplete_snapshot_is_never_offered(self) -> None:
        # A directory in history/ without a manifest is not one of our snapshots: it is neither
        # restorable by name nor eligible to be "last" — and retention will not delete it.
        real = forge.update_bot("wren", {"soul_append": "real edit"})["snapshot"]
        stray = self.pdir / "history" / "99999999T999999999999Z"
        stray.mkdir(parents=True)
        (stray / "SOUL.md").write_text("half a bot", encoding="utf-8")  # no manifest.json
        named = forge.rollback_bot("wren", stamp=stray.name)
        self.assertFalse(named["ok"])
        self.assertIn("not found", named["error"])
        newest = forge.rollback_bot("wren")  # "last" is the real snapshot, not the stray directory
        self.assertTrue(newest["ok"], newest.get("error"))
        self.assertEqual(newest["from"], real)
        self.assertEqual((self.pdir / "SOUL.md").read_text(encoding="utf-8"), self.original_soul)

    def test_damaged_snapshot_is_refused_rather_than_partially_restored(self) -> None:
        made = forge.update_bot("wren", {"soul_append": "kept line"})
        snap = self.pdir / "history" / made["snapshot"]
        (snap / "config.yaml").unlink()  # the manifest still lists it
        res = forge.rollback_bot("wren", stamp=made["snapshot"])
        self.assertFalse(res["ok"])
        self.assertIn("damaged", res["error"])
        self.assertIn("config.yaml", res["error"])
        self.assertIn("kept line", (self.pdir / "SOUL.md").read_text(encoding="utf-8"))

    def test_retention_leaves_directories_it_did_not_create(self) -> None:
        foreign = self.pdir / "history" / "operator-notes"
        foreign.mkdir(parents=True)
        (foreign / "note.md").write_text("keep me", encoding="utf-8")
        for i in range(forge.HISTORY_KEEP + 3):
            forge.snapshot_bot(self.pdir, reason=f"bulk {i}")
        self.assertTrue(foreign.is_dir(), "retention deleted a directory it did not create")
        self.assertEqual((foreign / "note.md").read_text(encoding="utf-8"), "keep me")

    def test_no_snapshots_is_a_readable_error(self) -> None:
        history = self.pdir / "history"
        if history.is_dir():
            for snap in history.iterdir():
                for f in snap.iterdir():
                    f.unlink()
                snap.rmdir()
            history.rmdir()
        res = forge.rollback_bot("wren")
        self.assertFalse(res["ok"])
        self.assertIn("nothing to roll back", res["error"])

    def test_history_directory_without_snapshots_is_a_readable_error(self) -> None:
        (self.pdir / "history").mkdir(exist_ok=True)
        res = forge.rollback_bot("wren")
        self.assertFalse(res["ok"])
        self.assertIn("nothing to roll back", res["error"])

    def test_manual_soul_edit_is_the_base_of_the_next_change(self) -> None:
        # The operator edits SOUL.md outside the plugin; a later append must keep their text.
        handle = self.pdir / "SOUL.md"
        handle.write_text(handle.read_text(encoding="utf-8") + "\nhand-written line\n", encoding="utf-8")
        res = forge.update_bot("wren", {"soul_append": "plugin line"})
        self.assertTrue(res["ok"], res.get("error"))
        soul = handle.read_text(encoding="utf-8")
        self.assertIn("hand-written line", soul)
        self.assertIn("plugin line", soul)
        self.assertIn("plugin line", res["diff"])

    def test_retention_keeps_the_newest_twenty(self) -> None:
        for i in range(forge.HISTORY_KEEP + 4):
            forge.snapshot_bot(self.pdir, reason=f"bulk {i}")
        snaps = [d for d in (self.pdir / "history").iterdir() if d.is_dir()]
        self.assertEqual(len(snaps), forge.HISTORY_KEEP)  # not "at most": vacuously-empty would pass
        newest = max(d.name for d in snaps)
        self.assertTrue((self.pdir / "history" / newest / "manifest.json").is_file())
        self.assertTrue(all((d / "manifest.json").is_file() for d in snaps))

    def test_rollback_of_the_oldest_snapshot_at_the_retention_cap_still_restores(self) -> None:
        # The undo snapshot applies retention, and at the cap that deletes the very target being
        # restored. Reading the payload first is what makes this restore instead of silently no-op.
        for i in range(forge.HISTORY_KEEP):
            forge.snapshot_bot(self.pdir, reason=f"fill {i}")
        oldest = sorted(d.name for d in (self.pdir / "history").iterdir() if d.is_dir())[0]
        (self.pdir / "SOUL.md").write_text("# changed\n", encoding="utf-8")
        res = forge.rollback_bot("wren", stamp=oldest)
        self.assertTrue(res["ok"], res.get("error"))
        self.assertIn("SOUL.md", res["restored"])
        self.assertEqual((self.pdir / "SOUL.md").read_text(encoding="utf-8"), self.original_soul)


if __name__ == "__main__":
    unittest.main()
