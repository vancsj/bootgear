import concurrent.futures
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
HOOK = PLUGIN_DIR / "hooks" / "stop_recall_reminder.py"


class StopRecallReminderTest(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="codex-stop-reminder-test-"))
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.project = self.root / "project"
        self.project.mkdir()
        self.home = self.root / "home"
        self.ledger_dir = self.home / ".bootgear" / "session"
        self.ledger_dir.mkdir(parents=True)
        self.run_id = "test-run"
        self.ledger = self.ledger_dir / f"{self.run_id}.md"
        self.ledger.write_text("## settlement\ngoal: test\n## state\ncurrent: impl\n")
        self.marker = self.ledger_dir / f".{self.run_id}.stop_reminder_state"

    def _run_hook(self, event: str, turn_id: str = "turn-1", **extra) -> dict:
        payload = {
            "hook_event_name": event,
            "session_id": self.run_id,
            "turn_id": turn_id,
            "cwd": str(self.project),
            **extra,
        }
        env = os.environ.copy()
        env["HOME"] = str(self.home)
        result = subprocess.run(
            ["python3", str(HOOK)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout) if result.stdout.strip() else {}

    def test_home_ledger_found_when_cwd_session_dir_holds_other_runs(self):
        cwd_session = self.project / ".bootgear" / "session"
        cwd_session.mkdir(parents=True)
        (cwd_session / "other-run.md").write_text("## state\ncurrent: impl\n")

        output = self._run_hook("Stop")
        self.assertEqual(output["decision"], "block")
        self.assertTrue(self.marker.exists())

    def test_cwd_ledger_is_not_a_run_location(self):
        cwd_session = self.project / ".bootgear" / "session"
        cwd_session.mkdir(parents=True)
        self.ledger.rename(cwd_session / f"{self.run_id}.md")

        self.assertEqual(self._run_hook("Stop"), {})
        self.assertFalse((cwd_session / f".{self.run_id}.stop_reminder_state").exists())

    def test_stop_blocks_once_with_a_recall_reason(self):
        output = self._run_hook("Stop")

        self.assertEqual(output["decision"], "block")
        self.assertIn("call `recall`", output["reason"])
        self.assertNotIn("systemMessage", output)
        self.assertNotIn("hookSpecificOutput", output)
        self.assertTrue(json.loads(self.marker.read_text())["turns"][0]["stop_seen"])

    def test_active_stop_records_observation_without_output(self):
        output = self._run_hook("Stop", stop_hook_active=True)

        self.assertEqual(output, {})
        state = json.loads(self.marker.read_text())
        self.assertTrue(state["turns"][0]["stop_seen"])

    def test_missing_stop_falls_back_once_on_next_turn(self):
        self.assertEqual(self._run_hook("PostToolUse", "turn-1"), {})
        self.assertEqual(self._run_hook("PostToolUse", "turn-1"), {})

        fallback = self._run_hook("PostToolUse", "turn-2")
        self.assertEqual(fallback["hookSpecificOutput"]["hookEventName"], "PostToolUse")
        self.assertEqual(self._run_hook("PostToolUse", "turn-2"), {})
        state = json.loads(self.marker.read_text())
        self.assertTrue(state["turns"][0]["fallback_reminded"])

    def test_stop_prevents_fallback_on_next_turn(self):
        self.assertEqual(self._run_hook("Stop", "turn-1")["decision"], "block")

        self.assertEqual(self._run_hook("PostToolUse", "turn-2"), {})

    def test_missing_closed_and_malformed_inputs_are_silent(self):
        self.ledger.unlink()
        self.assertEqual(self._run_hook("Stop"), {})
        self.ledger.write_text("## closed\n")
        self.assertEqual(self._run_hook("Stop", "turn-2"), {})
        self.ledger.write_text("## state\ncurrent: impl\n")
        self.assertEqual(self._run_hook("Other", "turn-3"), {})
        self.assertEqual(self._run_hook("Stop", ""), {})
        self.assertFalse(self.marker.exists())

    def test_repeated_rapid_stop_is_bounded(self):
        self.assertIn("decision", self._run_hook("Stop"))
        state = json.loads(self.marker.read_text())
        state["nudge_count"] = 1
        state["last_nudge_at"] = time.time()
        self.marker.write_text(json.dumps(state))

        self.assertEqual(self._run_hook("Stop", "turn-2"), {})

    def test_sessions_have_separate_markers(self):
        other_run = "other-run"
        (self.ledger_dir / f"{other_run}.md").write_text(self.ledger.read_text())

        self.assertIn("decision", self._run_hook("Stop"))
        original_run = self.run_id
        self.run_id = other_run
        self.marker = self.ledger_dir / f".{other_run}.stop_reminder_state"
        self.assertIn("decision", self._run_hook("Stop"))
        self.run_id = original_run
        self.assertTrue((self.ledger_dir / f".{original_run}.stop_reminder_state").exists())

    def test_concurrent_new_turn_fallback_updates_are_atomic(self):
        self.assertEqual(self._run_hook("PostToolUse", "turn-1"), {})

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            outputs = list(pool.map(
                lambda _: self._run_hook("PostToolUse", "turn-2"), range(8)
            ))

        emitted = [output for output in outputs if output]
        self.assertEqual(len(emitted), 1)
        json.loads(self.marker.read_text())


if __name__ == "__main__":
    unittest.main()
