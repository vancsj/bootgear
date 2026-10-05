import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
RUNNER = PLUGIN_DIR / "tests" / "run_host_adapter_fixture.py"


class CodexHostAdapterFixtureTest(unittest.TestCase):
    def test_codex_fixture_corpus_is_collected_and_runs(self):
        with tempfile.TemporaryDirectory(prefix="codex-host-adapter-test-home-") as home:
            result = subprocess.run(
                [sys.executable, str(RUNNER), "--host", "codex"],
                capture_output=True,
                text=True,
                env={**os.environ, "HOME": home},
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("host-adapter fixtures passed: codex", result.stdout)
