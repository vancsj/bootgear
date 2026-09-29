"""Tests for the aggregate session recall command."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
TASK_BIN = PLUGIN_DIR / "scripts" / "task"


class SessionRecallTest(unittest.TestCase):
    def setUp(self):
        self.session_dir = Path(tempfile.mkdtemp(prefix="engine-recall-test-"))
        self.addCleanup(shutil.rmtree, self.session_dir, ignore_errors=True)
        settlement_file = self.session_dir / "settlement.yaml"
        settlement_file.write_text(
            "task_type: ticket-to-pr\n"
            "goal: verify aggregate recall\n"
        )
        self.run_id = "recall-test"
        self._task("session", "init", self.run_id,
                   "--settlement-file", str(settlement_file))

    def _task(self, *args):
        result = subprocess.run(
            [str(TASK_BIN), *args, "--dir", str(self.session_dir)],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_recall_prints_required_recovery_views(self):
        self._task("session", "record-decision", self.run_id,
                   "--mode", "solo", "--summary", "settlement confirmed")
        self._task("session", "update-todo", self.run_id, "verify state")
        self._task("session", "record-pitch", self.run_id, "recall command added")

        output = self._task("session", "recall", self.run_id)

        self.assertIn("-- settlement --", output)
        self.assertIn("task_type: ticket-to-pr", output)
        self.assertIn("-- decisions (full) --", output)
        self.assertIn("settlement confirmed", output)
        self.assertIn("-- open todos --", output)
        self.assertIn("- [ ] verify state", output)
        self.assertIn("-- state --", output)
        self.assertIn("current: clarify", output)
        self.assertIn("-- recent pitches (last 3) --", output)
        self.assertIn("recall command added", output)


if __name__ == "__main__":
    unittest.main()
