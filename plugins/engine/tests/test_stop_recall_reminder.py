import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
HOOK = PLUGIN_DIR / "hooks" / "stop_recall_reminder.py"


class StopRecallReminderTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="engine-stop-reminder-test-")
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.home = self.root / "home"
        self.run_id = "test-run"
        self.ledger_dir = self.home / ".bootgear" / "session"
        self.ledger_dir.mkdir(parents=True)
        self.ledger = self.ledger_dir / f"{self.run_id}.md"
        self.ledger.write_text("## state\ncurrent: impl\n")

    def _run_hook(self, **extra):
        payload = {
            "session_id": self.run_id,
            "cwd": str(self.project),
            "hook_event_name": "Stop",
            **extra,
        }
        result = subprocess.run(
            ["python3", str(HOOK)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env={**os.environ, "HOME": str(self.home)},
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout) if result.stdout.strip() else {}

    def test_home_ledger_found_when_cwd_session_dir_holds_other_runs(self):
        project_session = self.project / ".bootgear" / "session"
        project_session.mkdir(parents=True)
        (project_session / "other-run.md").write_text("## state\ncurrent: impl\n")

        output = self._run_hook()
        self.assertEqual(output["hookSpecificOutput"]["hookEventName"], "Stop")
        self.assertTrue((self.ledger_dir / f".{self.run_id}.stop_reminder_state").exists())

    def test_cwd_ledger_is_not_a_run_location(self):
        project_session = self.project / ".bootgear" / "session"
        project_session.mkdir(parents=True)
        self.ledger.rename(project_session / f"{self.run_id}.md")

        self.assertEqual(self._run_hook(), {})

    def test_stop_continues_once_with_recall_context(self):
        output = self._run_hook()

        self.assertEqual(output["hookSpecificOutput"]["hookEventName"], "Stop")
        self.assertIn("call `recall`", output["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(self._run_hook(stop_hook_active=True), {})

    def test_closed_run_is_silent(self):
        self.ledger.write_text("## state\ncurrent: succeeded\n## closed\n")

        self.assertEqual(self._run_hook(), {})


if __name__ == "__main__":
    unittest.main()
