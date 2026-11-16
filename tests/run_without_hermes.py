"""Run the whole suite as the CI runner sees it: no hermes_cli, no hermes_constants, no hermes CLI.

Blocks those imports with a meta path finder and empties PATH of ``hermes``, the way a machine
without Hermes installed behaves. Local proof that the suite is hermetic; CI is the same machine.

    python3 tests/run_without_hermes.py
"""
import os
import sys
import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_DIR))

BLOCKED = ("hermes_cli", "hermes_constants")


class _Block:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in BLOCKED:
            raise ModuleNotFoundError(f"No module named '{name}'")
        return None


for mod in list(sys.modules):
    if mod.split(".")[0] in BLOCKED:
        del sys.modules[mod]
sys.meta_path.insert(0, _Block())

# Keep the interpreter, drop the rest of PATH: `shutil.which("hermes")` must find nothing.
os.environ["PATH"] = "/nonexistent"

suite = unittest.TestLoader().discover(str(Path(__file__).resolve().parent))
result = unittest.TextTestRunner(verbosity=1).run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
