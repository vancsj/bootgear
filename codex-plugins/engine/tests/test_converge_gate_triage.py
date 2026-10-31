"""Run the converge triage gate tests against the Codex copy of converge.

The tests live with the converge plugin. This module runs that file in a
subprocess with `CONVERGE_SRC` set to the Codex engine's converge source.
"""
import os
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
GATE_TESTS = REPO / "plugins" / "converge" / "tests" / "test_gate_triage.py"
CODEX_SRC = REPO / "codex-plugins" / "engine" / "src"


class ConvergeGateTriageOnCodexTest(unittest.TestCase):
    def test_gate_triage_tests_pass_on_the_codex_converge(self):
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(GATE_TESTS)],
            capture_output=True, text=True, check=False, cwd=GATE_TESTS.parent,
            env={**os.environ, "CONVERGE_SRC": str(CODEX_SRC)})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
