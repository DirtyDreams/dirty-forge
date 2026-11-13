"""Unit and integration tests for DirtyForge."""
from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

import yaml

PLUGIN_DIR = Path(__file__).resolve().parents[1]
if str(PLUGIN_DIR.parent) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR.parent))

# Load as package 'dirty_forge' via importlib since directory name uses a hyphen
spec = importlib.util.spec_from_file_location(
    "dirty_forge",
    PLUGIN_DIR / "__init__.py",
    submodule_search_locations=[str(PLUGIN_DIR)],
)
dirty_forge = importlib.util.module_from_spec(spec)
sys.modules["dirty_forge"] = dirty_forge
assert spec and spec.loader
spec.loader.exec_module(dirty_forge)

from dirty_forge import blueprints, compiler, forge, journal, policy  # noqa: E402
from dirty_forge.sentinel import guard  # noqa: E402


class RecordingContext:
    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.tools: dict[str, dict[str, Any]] = {}
        self.hooks: dict[str, list[Any]] = {}
        self.cli_commands: dict[str, Any] = {}
        self.skills: dict[str, Path] = {}
        self._config = config or {}

    def get_config(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    def register_tool(self, **kwargs: Any) -> None:
        self.tools[kwargs["name"]] = kwargs

    def register_hook(self, name: str, fn: Any) -> None:
        self.hooks.setdefault(name, []).append(fn)

    def register_cli_command(self, **kwargs: Any) -> None:
        self.cli_commands[kwargs["name"]] = kwargs

    def register_skill(self, name: str, path: Path) -> None:
        self.skills[name] = path


class DirtyForgeTests(unittest.TestCase):
    def test_plugin_contract_and_schemas(self) -> None:
        manifest = yaml.safe_load((PLUGIN_DIR / "plugin.yaml").read_text(encoding="utf-8"))
        ctx = RecordingContext()
        dirty_forge.register(ctx)

        self.assertEqual(set(ctx.tools.keys()), set(manifest["provides_tools"]))
        for name, reg in ctx.tools.items():
            schema = reg["schema"]
            self.assertEqual(schema["name"], name)
            self.assertTrue(schema.get("description"))
            params = schema.get("parameters", {})
            self.assertEqual(params.get("type"), "object")
            self.assertIsInstance(params.get("properties"), dict)
            self.assertIsInstance(params.get("required"), list)

        self.assertIn("pre_llm_call", ctx.hooks)
        self.assertIn("post_llm_call", ctx.hooks)
        self.assertIn("dirty-forge-doctor", ctx.cli_commands)
        self.assertIn("dirty-forge", ctx.skills)

    def test_blueprints_search_and_compiler(self) -> None:
        hits = blueprints.search("backend architecture", limit=5)
        self.assertTrue(len(hits) > 0)
        pack = compiler.build_metaprompt_pack("backend architecture", hits[0]["slug"])
        self.assertIsNotNone(pack["primary_blueprint"])

        soul, mode = compiler.compile_soul_md(
            display_name="Kairo",
            role="Backend Architect",
            description="Designs resilient APIs.",
            blueprint_slug=hits[0]["slug"],
            allow_llm_fallback=False,
        )
        self.assertEqual(mode, "deterministic_blueprint")
        self.assertIn("# Kairo — Backend Architect", soul)
        self.assertIn("## Never", soul)

    def test_sentinel_guard_and_secret_scanner(self) -> None:
        pol = {"approve_categories": ["send", "spend", "destroy"], "limits": {"send_email": {"to": ["me@example.com"]}}}
        self.assertEqual(guard.evaluate("send_email", {"to": "me@example.com"}, pol)["action"], "approve")
        self.assertEqual(guard.evaluate("send_email", {"to": "evil@other.com"}, pol)["action"], "block")
        self.assertEqual(guard.evaluate("delete_repo", {}, pol)["action"], "approve")
        self.assertEqual(guard.evaluate("terminal", {"command": "echo $(whoami)"}, pol)["action"], "block")
        self.assertEqual(guard.evaluate("terminal", {"command": "ls -la"}, pol), None)

        self.assertIn("github_pat", guard.scan_secrets("token=ghp_1234567890abcdefghij123456"))
        self.assertEqual(guard.scan_secrets("completely safe text"), [])

    def test_end_to_end_provisioning_omh_journal_and_delete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / ".hermes"
            (root / "memories").mkdir(parents=True)
            (root / "memories" / "USER.md").write_text("User prefers concise Polish/English.", encoding="utf-8")
            (root / "config.yaml").write_text(
                yaml.safe_dump({"model": {"default": "claude-sonnet-4", "provider": "anthropic"}}),
                encoding="utf-8",
            )
            # Simulate installed omh plugin in root
            omh_src = root / "plugins" / "omh"
            omh_src.mkdir(parents=True)
            (omh_src / "plugin.yaml").write_text("name: omh\nversion: 1.0.0\n", encoding="utf-8")
            (omh_src / "__init__.py").write_text("def register(ctx): pass\n", encoding="utf-8")

            old_env = os.environ.get("HERMES_HOME")
            os.environ["HERMES_HOME"] = str(root)
            try:
                ctx = RecordingContext({"install_gateway": False, "workspace_survey": False})
                dirty_forge.register(ctx)

                res = json.loads(
                    ctx.tools["dirty_forge_create_bot"]["handler"](
                        {
                            "display_name": "Nova",
                            "role": "Research Analyst",
                            "description": "Tracks AI papers and summarizes findings.",
                            "memory": ["Focus on agentic architectures."],
                        }
                    )
                )
                self.assertTrue(res["ok"], res)
                self.assertEqual(res["omh_memory_mode"], "auto-safe")
                self.assertIn("omh", res["plugins_enabled"])
                self.assertIn("dirty-forge-sentinel", res["plugins_enabled"])

                pdir = Path(res["profile_dir"])
                self.assertTrue((pdir / "SOUL.md").is_file())
                self.assertTrue((pdir / ".omh" / "setup-profile.json").is_file())
                self.assertTrue((pdir / "plugins" / "omh" / "plugin.yaml").is_file())
                self.assertTrue((pdir / "plugins" / "dirty-forge-sentinel" / "guard.py").is_file())
                self.assertTrue((pdir / "memories" / "USER.md").is_file())

                check = json.loads(ctx.tools["dirty_forge_check_bots"]["handler"]({}))
                self.assertTrue(check["ok"])
                self.assertEqual(check["count"], 1)
                self.assertTrue(check["bots"][0]["policy_in_sync"])
                self.assertTrue(check["bots"][0]["omh_configured"])
                self.assertTrue(check["bots"][0]["sentinel_installed"])

                j_write = json.loads(
                    ctx.tools["dirty_forge_journal"]["handler"](
                        {
                            "action": "write",
                            "name": "nova",
                            "status": "completed",
                            "goal": "Initial setup",
                            "outcome": "Verified profile.",
                        }
                    )
                )
                self.assertTrue(j_write["ok"])
                j_read = json.loads(ctx.tools["dirty_forge_journal"]["handler"]({"action": "read", "name": "nova"}))
                self.assertEqual(len(j_read["entries"]), 1)

                # Delete blocked by default
                del_blocked = json.loads(ctx.tools["dirty_forge_delete_bot"]["handler"]({"name": "nova"}))
                self.assertFalse(del_blocked["ok"])

                # Delete allowed with backup
                del_ok = forge.delete_bot("nova", settings={"allow_delete": True, "backup_before_delete": True}, root=root)
                self.assertTrue(del_ok["ok"])
                self.assertTrue(Path(del_ok["backup"]).is_file())
                self.assertFalse(pdir.exists())
            finally:
                if old_env is None:
                    os.environ.pop("HERMES_HOME", None)
                else:
                    os.environ["HERMES_HOME"] = old_env


if __name__ == "__main__":
    unittest.main()
