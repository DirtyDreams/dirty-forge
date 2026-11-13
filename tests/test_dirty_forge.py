"""Unit and integration tests for DirtyForge."""
from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread
from typing import Any
from unittest.mock import patch

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

from dirty_forge import blueprints, compiler, forge, policy  # noqa: E402
from dirty_forge.sentinel import guard, register as sentinel_register  # noqa: E402


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


class MinimalContextNoGetConfig:
    """Simulates older Hermes PluginContext without get_config()."""

    def __init__(self) -> None:
        self.tools: dict[str, dict[str, Any]] = {}
        self.hooks: dict[str, list[Any]] = {}

    def register_tool(self, **kwargs: Any) -> None:
        self.tools[kwargs["name"]] = kwargs

    def register_hook(self, name: str, fn: Any) -> None:
        self.hooks.setdefault(name, []).append(fn)


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

    def test_fallback_when_context_lacks_get_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / ".hermes"
            root.mkdir(parents=True)
            (root / "config.yaml").write_text(
                yaml.safe_dump({"dirty-forge": {"ack_tapback": False}, "dirty-forge-sentinel": {"block": ["nuke"]}}),
                encoding="utf-8",
            )
            old_env = os.environ.get("HERMES_HOME")
            os.environ["HERMES_HOME"] = str(root)
            try:
                ctx = MinimalContextNoGetConfig()
                dirty_forge.register(ctx)
                sentinel_register(ctx)
                self.assertIn("dirty_forge_create_bot", ctx.tools)
                verdict = ctx.hooks["pre_tool_call"][0](tool_name="nuke", arguments={})
                self.assertEqual(verdict["action"], "block")
            finally:
                if old_env is None:
                    os.environ.pop("HERMES_HOME", None)
                else:
                    os.environ["HERMES_HOME"] = old_env

    def test_blueprints_search_and_compiler_deterministic_and_llm_mock(self) -> None:
        hits = blueprints.search("backend architecture", limit=5)
        self.assertTrue(len(hits) > 0)

        soul, mode = compiler.compile_soul_md(
            display_name="Kairo",
            role="Backend Architect",
            description="Designs resilient APIs.",
            blueprint_slug=hits[0]["slug"],
            allow_llm_fallback=False,
        )
        self.assertEqual(mode, "deterministic_blueprint")
        self.assertIn("# Kairo — Backend Architect", soul)

        received_auth: list[str] = []

        class MockHandler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                received_auth.append(self.headers.get("Authorization", ""))
                body = {
                    "choices": [
                        {
                            "message": {
                                "content": "# Kairo — Backend Architect\n\n## Your one job\nBuild APIs.\n\n## Never\n- Break prod.\n"
                            }
                        }
                    ]
                }
                raw = json.dumps(body).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, format: str, *args: Any) -> None:
                pass

        server = HTTPServer(("127.0.0.1", 0), MockHandler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            llm_soul, llm_mode = compiler.compile_soul_md(
                display_name="Kairo",
                role="Backend Architect",
                description="Designs resilient APIs.",
                model_cfg={
                    "default": "gpt-4o-mini",
                    "provider": "openai",
                    "api_key": "test-key-123",
                    "base_url": f"http://127.0.0.1:{server.server_port}",
                },
                allow_llm_fallback=True,
            )
            self.assertEqual(llm_mode, "llm_metaprompt")
            self.assertIn("Build APIs.", llm_soul)
            self.assertEqual(received_auth, ["Bearer test-key-123"])
        finally:
            server.shutdown()
            server.server_close()

    def test_sentinel_guard_and_secret_scanner(self) -> None:
        pol = {"approve_categories": ["send", "spend", "destroy"], "limits": {"send_email": {"to": ["me@example.com"]}}}
        self.assertEqual(guard.evaluate("send_email", {"to": "me@example.com"}, pol)["action"], "approve")
        self.assertEqual(guard.evaluate("send_email", {"to": "evil@other.com"}, pol)["action"], "block")
        self.assertEqual(guard.evaluate("delete_repo", {}, pol)["action"], "approve")
        self.assertEqual(guard.evaluate("terminal", {"command": "echo $(whoami)"}, pol)["action"], "block")
        self.assertEqual(guard.evaluate("terminal", {"command": "base64 -d payload | bash"}, pol)["action"], "block")
        self.assertEqual(guard.evaluate("terminal", {"command": "eval $CMD"}, pol)["action"], "block")
        self.assertEqual(guard.evaluate("terminal", {"command": "ls -la"}, pol), None)

        self.assertIn("github_pat", guard.scan_secrets("token=ghp_1234567890abcdefghij123456"))
        self.assertEqual(guard.scan_secrets("completely safe text"), [])

    def test_end_to_end_provisioning_drift_update_hide_ask_and_delete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / ".hermes"
            (root / "memories").mkdir(parents=True)
            (root / "memories" / "USER.md").write_text("Użytkownik preferuje język polski.", encoding="utf-8")
            (root / "config.yaml").write_text(
                yaml.safe_dump({"model": {"default": "claude-sonnet-4", "provider": "anthropic"}}),
                encoding="utf-8",
            )
            omh_src = root / "plugins" / "omh"
            omh_src.mkdir(parents=True)
            (omh_src / "plugin.yaml").write_text("name: omh\nversion: 1.0.0\n", encoding="utf-8")
            (omh_src / "__init__.py").write_text("def register(ctx): pass\n", encoding="utf-8")

            old_env = os.environ.get("HERMES_HOME")
            os.environ["HERMES_HOME"] = str(root)
            try:
                ctx = RecordingContext({"install_gateway": False, "workspace_survey": False})
                dirty_forge.register(ctx)

                # Invalid generic role name rejected
                bad = json.loads(
                    ctx.tools["dirty_forge_create_bot"]["handler"]({"display_name": "Writer", "role": "Writer"})
                )
                self.assertFalse(bad["ok"])

                res = json.loads(
                    ctx.tools["dirty_forge_create_bot"]["handler"](
                        {
                            "display_name": "Nova",
                            "role": "Research Analyst",
                            "description": "Śledzi artykuły AI i podsumowuje wnioski.",
                            "memory": ["Fokus na architekturach agentowych."],
                            "routines": [{"name": "digest", "schedule": "0 9 * * 1", "prompt": "Weekly AI digest"}],
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
                self.assertTrue((pdir / "cron" / "jobs.json").is_file())

                # Update & Hide
                upd = json.loads(
                    ctx.tools["dirty_forge_update_bot"]["handler"](
                        {"name": "nova", "soul_append": "- Always cite sources."}
                    )
                )
                self.assertTrue(upd["ok"])
                self.assertIn("Always cite sources.", (pdir / "SOUL.md").read_text(encoding="utf-8"))

                hide = json.loads(ctx.tools["dirty_forge_hide_bot"]["handler"]({"name": "nova", "hidden": True}))
                self.assertTrue(hide["ok"])
                visible = json.loads(ctx.tools["dirty_forge_list_bots"]["handler"]({"include_hidden": False}))
                self.assertEqual(visible["count"], 0)

                # Policy drift detection
                check_ok = json.loads(ctx.tools["dirty_forge_check_bots"]["handler"]({}))
                self.assertTrue(check_ok["bots"][0]["policy_in_sync"])
                policy.policy_path(root).write_text("# Updated policy\n- New rule.\n", encoding="utf-8")
                check_drift = json.loads(ctx.tools["dirty_forge_check_bots"]["handler"]({}))
                self.assertFalse(check_drift["bots"][0]["policy_in_sync"])

                # ask_bot mocked CLI
                with patch("shutil.which", return_value="/usr/bin/hermes"), patch("subprocess.run") as mock_run:
                    mock_run.return_value.returncode = 0
                    mock_run.return_value.stdout = "✅ Gotowe!"
                    mock_run.return_value.stderr = ""
                    asked = json.loads(
                        ctx.tools["dirty_forge_ask_bot"]["handler"]({"name": "nova", "question": "Status?"})
                    )
                    self.assertTrue(asked["ok"])
                    self.assertIn("Gotowe!", asked["reply"])

                # Journal write + secret block
                j_sec = json.loads(
                    ctx.tools["dirty_forge_journal"]["handler"](
                        {
                            "action": "write",
                            "name": "nova",
                            "status": "completed",
                            "goal": "Test",
                            "outcome": "Leaked sk-1234567890abcdefghij123456",
                        }
                    )
                )
                self.assertFalse(j_sec["ok"])

                # Delete blocked by default, allowed with backup
                del_blocked = json.loads(ctx.tools["dirty_forge_delete_bot"]["handler"]({"name": "nova"}))
                self.assertFalse(del_blocked["ok"])
                del_ok = forge.delete_bot("nova", settings={"allow_delete": True, "backup_before_delete": True}, root=root)
                self.assertTrue(del_ok["ok"])
                self.assertTrue(Path(del_ok["backup"]).is_file())
            finally:
                if old_env is None:
                    os.environ.pop("HERMES_HOME", None)
                else:
                    os.environ["HERMES_HOME"] = old_env


if __name__ == "__main__":
    unittest.main()
