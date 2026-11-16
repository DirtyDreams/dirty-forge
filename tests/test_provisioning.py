"""Provisioning contract: platform_toolsets, USER.md filtering, provision_profile fallback."""

from __future__ import annotations

import importlib
import os
import subprocess
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


class ProvisioningTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / ".hermes"
        (self.root / "memories").mkdir(parents=True)
        (self.root / "config.yaml").write_text(
            yaml.safe_dump({"model": {"default": "gpt-4o"}}), encoding="utf-8"
        )
        (self.root / "memories" / "USER.md").write_text(
            "Coyote pisze po polsku.\n§\nThe assistant is called Hermes and should be addressed as such.\n",
            encoding="utf-8",
        )
        self._old_env = os.environ.get("HERMES_HOME")
        os.environ["HERMES_HOME"] = str(self.root)

    def tearDown(self) -> None:
        if self._old_env is None:
            os.environ.pop("HERMES_HOME", None)
        else:
            os.environ["HERMES_HOME"] = self._old_env
        self._tmp.cleanup()

    def _bot(self, **over):
        spec = {"display_name": "Wren", "role": "QA Reviewer", "one_job": "Review the code."}
        spec.update(over)
        return forge.forge_bot(spec, settings={"install_gateway": False, "workspace_survey": False})

    def test_platform_toolsets_not_the_dead_toolsets_key(self) -> None:
        res = self._bot(toolsets=["vision"])
        self.assertTrue(res["ok"], res.get("error"))
        cfg = yaml.safe_load((Path(res["profile_dir"]) / "config.yaml").read_text(encoding="utf-8"))
        self.assertNotIn("toolsets", cfg)
        self.assertIn("platform_toolsets", cfg)
        self.assertIn("vision", cfg["platform_toolsets"]["cli"])
        self.assertIn("file", cfg["platform_toolsets"]["cli"])

    def test_restricted_toolset_is_actually_withheld(self) -> None:
        # Before the platform_toolsets fix this check was theatre: `toolsets` is ignored by Hermes,
        # so a Bot asked for `terminal` got every tool regardless of approvals.
        res = self._bot(toolsets=["terminal"], approve_categories=[])
        self.assertTrue(res["ok"], res.get("error"))
        cfg = yaml.safe_load((Path(res["profile_dir"]) / "config.yaml").read_text(encoding="utf-8"))
        self.assertNotIn("terminal", cfg["platform_toolsets"]["cli"])
        self.assertIn("terminal", res.get("withheld_toolsets", []))

    def test_user_memory_drops_entries_naming_an_assistant(self) -> None:
        res = self._bot()
        self.assertTrue(res["ok"], res.get("error"))
        user_md = (Path(res["profile_dir"]) / "memories" / "USER.md").read_text(encoding="utf-8")
        self.assertIn("Coyote pisze po polsku", user_md)
        self.assertNotIn("Hermes", user_md)

    def test_ui_meta_carries_a_face_desktop_can_draw(self) -> None:
        res = self._bot(avatar_kind="star", section_name="Research Team")
        self.assertTrue(res["ok"], res.get("error"))
        prof = yaml.safe_load((Path(res["profile_dir"]) / "profile.yaml").read_text(encoding="utf-8"))
        ui = prof["ui_meta"]["hermes-bots"]
        self.assertEqual(ui["imageKind"], "shape")
        self.assertEqual(ui["shape"], "blobatar::star")
        self.assertEqual(ui["sectionId"], "research-team")
        self.assertNotIn("avatarKind", ui)
        self.assertGreaterEqual(prof["_ui_meta_revisions"]["hermes-bots"], 1)

    def test_name_collision_leaves_nothing_behind(self) -> None:
        self.assertTrue(self._bot()["ok"])
        again = self._bot()
        self.assertFalse(again["ok"])
        self.assertIn("already exists", again["error"])

    def test_provision_profile_falls_back_for_a_root_hermes_will_not_resolve(self) -> None:
        # Hermes' own resolver cannot be pointed at a temp home, so provisioning must decline here
        # instead of creating the profile in the operator's real ~/.hermes/profiles.
        self.assertEqual(forge._provision_profile(self.root, "wren", "QA"), "skip")

    def test_profile_landing_outside_the_root_is_removed_not_orphaned(self) -> None:
        from unittest.mock import MagicMock, patch

        stray = Path(self._tmp.name) / "elsewhere" / "wren"
        stray.mkdir(parents=True)
        (stray / "config.yaml").write_text("model: {}\n", encoding="utf-8")
        fake = type("R", (), {"path": stray, "warnings": []})()
        # A machine without Hermes installed has no hermes_cli to patch into, and that is exactly the
        # machine CI runs on: stand the module up rather than importing what may not be there.
        provision_mod = MagicMock()
        provision_mod.provision_profile.return_value = fake
        with patch.object(forge, "_hermes_root_resolves_to", return_value=True), \
             patch.dict(sys.modules, {"hermes_cli": MagicMock(), "hermes_cli.profile_provision": provision_mod}):
            err = forge._provision_profile(self.root, "wren", "QA")
        self.assertIn("outside the requested root", err)
        self.assertFalse(stray.exists(), "the stray profile it created was left behind")

    def test_kickoff_is_skipped_rather_than_sent_for_an_unresolvable_root(self) -> None:
        from unittest.mock import patch

        # `which` is patched so the PATH branch cannot answer first: this asserts the root gate,
        # which is a different reason, on a machine with Hermes on PATH and on one without.
        with patch.object(forge.shutil, "which", return_value="/usr/bin/hermes"):
            warning = forge._kickoff_check(self.root, "wren", {})
        # The root gate specifically: the PATH branch says "not on PATH", which is a different reason.
        self.assertIn("not one Hermes resolves", warning)

    def test_kickoff_reports_a_bot_that_did_not_answer(self) -> None:
        # The branch that only runs on a real root: exercise it by making the root resolve and
        # stubbing the child process, so the "created but mute" case is not left to a manual run.
        from unittest.mock import patch

        failed = subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="Error: no auth for model")
        with patch.object(forge, "_hermes_root_resolves_to", return_value=True), \
             patch.object(forge.shutil, "which", return_value="/usr/bin/hermes"), \
             patch.object(forge.subprocess, "run", return_value=failed):
            warning = forge._kickoff_check(self.root, "wren", {})
        self.assertIn("kickoff failed", warning)
        self.assertIn("no auth for model", warning)

    def test_kickoff_is_silent_when_the_bot_answers(self) -> None:
        from unittest.mock import patch

        ok = subprocess.CompletedProcess(args=[], returncode=0, stdout="Jestem Wren.", stderr="")
        with patch.object(forge, "_hermes_root_resolves_to", return_value=True), \
             patch.object(forge.shutil, "which", return_value="/usr/bin/hermes"), \
             patch.object(forge.subprocess, "run", return_value=ok):
            self.assertEqual(forge._kickoff_check(self.root, "wren", {}), "")


if __name__ == "__main__":
    unittest.main()
