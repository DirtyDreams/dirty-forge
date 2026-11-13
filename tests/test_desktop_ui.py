"""Tests for DirtyForge Hermes Desktop UI (desktop/plugin.js) and backend bridge (dashboard/plugin_api.py)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR.parent) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR.parent))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from dashboard import plugin_api  # noqa: E402


class DirtyForgeDesktopUITests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_home = os.environ.get("HERMES_HOME")
        os.environ["HERMES_HOME"] = self._tmp.name

    def tearDown(self) -> None:
        if self._old_home is None:
            os.environ.pop("HERMES_HOME", None)
        else:
            os.environ["HERMES_HOME"] = self._old_home
        self._tmp.cleanup()

    def test_backend_api_router_and_handlers_end_to_end(self) -> None:
        route_paths = {getattr(r, "path", "") for r in plugin_api.router.routes}
        self.assertIn("/health", route_paths)
        self.assertIn("/summary", route_paths)
        self.assertIn("/bots", route_paths)
        self.assertIn("/interview", route_paths)
        self.assertIn("/settings", route_paths)

        self.assertTrue(plugin_api.get_health()["ok"])

        # Settings roundtrip
        s_get = plugin_api.get_settings()
        self.assertTrue(s_get["ok"])
        self.assertFalse(s_get["settings"]["strict_intake"])

        s_put = plugin_api.update_settings({"settings": {"strict_intake": True, "allow_trusted_mcp": True}})
        self.assertTrue(s_put["ok"])
        self.assertTrue(s_put["settings"]["strict_intake"])
        self.assertTrue(s_put["settings"]["allow_trusted_mcp"])

        # Settings type validation rejects invalid values
        bad_int = plugin_api.update_settings({"settings": {"circuit_breaker_max_calls": 0}})
        self.assertFalse(bad_int["ok"])
        bad_mode = plugin_api.update_settings({"settings": {"omh_memory_mode": "invalid"}})
        self.assertFalse(bad_mode["ok"])
        bad_bool = plugin_api.update_settings({"settings": {"strict_intake": "yes"}})
        self.assertFalse(bad_bool["ok"])

        # Complete interview via REST handler
        iv = plugin_api.run_interview(
            {
                "answers": {
                    "display_name": "UI Spec Bot",
                    "role": "Issue Triage Specialist",
                    "one_job": "Triage incoming GitHub issues cleanly",
                    "target_user": "Engineering leads",
                    "inputs": "GitHub issue JSON",
                    "exact_output_format": "Markdown triage summary",
                    "sources_of_truth": "Issue body and repo labels",
                    "out_of_scope": "Never close issues or push code without approval",
                    "escalate_when": "Security vulnerability or critical outage reported",
                }
            }
        )
        self.assertTrue(iv["ok"])
        self.assertTrue(iv["ready_to_create"])
        intake_id = iv["intake_id"]

        iv_get = plugin_api.get_interview(intake_id)
        self.assertTrue(iv_get["ok"])

        # Create Bot from spec
        spec = dict(iv["create_bot_spec"])
        created = plugin_api.create_bot(spec)
        self.assertTrue(created["ok"])
        bot_name = created["name"]

        # Summary & roster & files
        summary = plugin_api.get_summary()
        self.assertEqual(summary["total_bots"], 1)

        bots = plugin_api.get_bots(include_hidden=True)
        self.assertEqual(bots["count"], 1)
        self.assertTrue(bots["bots"][0]["has_intake"])

        files = plugin_api.get_bot_files(bot_name)
        self.assertTrue(files["ok"])
        self.assertIn("## Task Card", files["soul_md"])

        # Eval cases, eval, metrics.jsonl, journal, takeover create & resolve, OMH
        ec = plugin_api.get_bot_eval_cases(bot_name)
        self.assertTrue(ec["ok"])
        self.assertGreaterEqual(len(ec["cases"]), 1)

        from dirty_forge import forge as df_forge
        from dirty_forge.sentinel import telemetry as df_telemetry

        pdir = df_forge.profile_dir(df_forge.default_root(), bot_name)
        df_telemetry.record_tool_event(pdir, "terminal", True)
        mt = plugin_api.get_bot_metrics(bot_name, limit=10)
        self.assertTrue(mt["ok"])
        self.assertEqual(len(mt["events"]), 1)
        self.assertEqual(mt["events"][0]["tool"], "terminal")

        ev = plugin_api.run_bot_eval(bot_name, {"cases": ec["cases"]})
        self.assertTrue(ev["ok"])

        jr = plugin_api.add_journal(
            bot_name,
            {"status": "NOTE", "goal": "UI check", "outcome": "Verified from API"},
        )
        self.assertTrue(jr["ok"])
        jr_list = plugin_api.get_journal(bot_name, date="", limit=20)
        self.assertGreaterEqual(jr_list["count"], 1)

        tk = plugin_api.create_takeover(bot_name, {"reason": "Manual operator check"})
        self.assertTrue(tk["ok"])
        tk_list = plugin_api.get_takeovers(bot_name)
        self.assertEqual(tk_list["count"], 1)
        self.assertEqual(plugin_api.get_summary()["pending_takeovers"], 1)

        tk_res = plugin_api.resolve_takeover(bot_name, tk["takeover_id"], {"resolution": "Handled"})
        self.assertTrue(tk_res["ok"])
        self.assertEqual(tk_res["status"], "resolved")
        self.assertEqual(plugin_api.get_summary()["pending_takeovers"], 0)

        omh = plugin_api.list_omh(bot_name)
        self.assertTrue(omh["ok"])

        # Extended doctor checks
        from dirty_forge import doctor as df_doctor
        doc = df_doctor.run_doctor()
        self.assertTrue(doc["desktop_ui_present"])
        self.assertTrue(doc["dashboard_api_present"])
        self.assertGreaterEqual(doc["intake_sessions"], 1)

        # Delete blocked by default allow_delete=False
        deleted = plugin_api.delete_bot(bot_name)
        self.assertFalse(deleted["ok"])

    def test_desktop_plugin_js_syntax_and_contract(self) -> None:
        plugin_js = ROOT_DIR / "desktop" / "plugin.js"
        self.assertTrue(plugin_js.is_file())

        # 1. Syntax check (ensures no JSX syntax slipped in)
        chk = subprocess.run(["node", "--check", str(plugin_js)], capture_output=True, text=True)
        self.assertEqual(chk.returncode, 0, msg=chk.stderr)

        # 2. Smoke-test ESM registration with mocked @hermes/plugin-sdk, react, react/jsx-runtime
        smoke_script = """
import { registerHooks } from 'node:module';

const mocks = {
  '@hermes/plugin-sdk': `
    export const ROUTES_AREA = 'routes';
    export const SIDEBAR_NAV_AREA = 'sidebar.nav';
    export const STATUSBAR_AREAS = { left: 'statusBar.left', right: 'statusBar.right' };
    export const PALETTE_AREA = 'palette';
    export const haptic = () => {};
    export const host = {
      navigate: () => {},
      notify: () => {},
      notifyError: () => {},
      composer: { insertText: async () => true, focus: () => {} },
    };
  `,
  'react': `
    export function useState(init) { return [typeof init === 'function' ? init() : init, () => {}]; }
    export function useEffect() {}
    export function useCallback(fn) { return fn; }
  `,
  'react/jsx-runtime': `
    export function jsx(type, props) { return { type, props }; }
    export function jsxs(type, props) { return { type, props }; }
  `,
};

registerHooks({
  resolve(specifier, context, nextResolve) {
    if (Object.hasOwn(mocks, specifier)) {
      return { url: 'mock://' + specifier, shortCircuit: true };
    }
    return nextResolve(specifier, context);
  },
  load(url, context, nextLoad) {
    if (url.startsWith('mock://')) {
      const key = url.slice('mock://'.length);
      return { format: 'module', source: mocks[key], shortCircuit: true };
    }
    return nextLoad(url, context);
  },
});

const mod = await import(process.argv[1]);
const plugin = mod.default;
const contributions = [];
const settingsPages = [];
const ctx = {
  register(c) { contributions.push(c); return () => {}; },
  registerMany(cs) { contributions.push(...cs); return () => {}; },
  registerSettingsPage(p) { settingsPages.push(p); return () => {}; },
  rest: async () => ({ ok: true, bots: [], settings: {} }),
  setInterval: () => () => {},
};
plugin.register(ctx);
for (const c of contributions) {
  if (typeof c.render === 'function') c.render();
}
for (const p of settingsPages) {
  if (typeof p.render === 'function') p.render();
}
console.log(JSON.stringify({
  id: plugin.id,
  areas: contributions.map((c) => c.area),
  settingsCount: settingsPages.length,
}));
"""
        res = subprocess.run(
            ["node", "--input-type=module", "-e", smoke_script, plugin_js.as_uri()],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0, msg=res.stderr)
        info = json.loads(res.stdout.strip())
        self.assertEqual(info["id"], "dirty-forge")
        self.assertIn("routes", info["areas"])
        self.assertIn("sidebar.nav", info["areas"])
        self.assertIn("statusBar.right", info["areas"])
        self.assertIn("palette", info["areas"])
        self.assertEqual(info["settingsCount"], 1)
