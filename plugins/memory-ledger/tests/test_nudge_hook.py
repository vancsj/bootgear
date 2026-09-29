"""Tests for plugins/memory-ledger/hooks/nudge.py.

Drives the hook as a subprocess, the same way it actually runs — stdin JSON
in, stdout hook-output JSON (or nothing) out. Isolates HOME per test so the
marker file and `_ledger_configured` check never touch the real machine's
memory-ledger state.
"""
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / "hooks" / "nudge.py"


class NudgeHookTest(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp(prefix="nudge-hook-test-"))
        shared = self.home / ".memory-ledger" / "shared"
        shared.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(shared)], check=True)
        self.session_id = "test-session"

    def _run(self, tool_name: str, tool_input: dict | None = None,
              event: str = "PostToolUse") -> dict:
        payload = {
            "session_id": self.session_id,
            "hook_event_name": event,
            "tool_name": tool_name,
            "tool_input": tool_input or {},
        }
        result = subprocess.run(
            ["python3", str(HOOK)],
            input=json.dumps(payload),
            capture_output=True, text=True,
            env={"HOME": str(self.home), "PATH": "/usr/bin:/bin"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        if not result.stdout.strip():
            return {}
        return json.loads(result.stdout)

    def _marker(self) -> dict:
        marker_path = self.home / ".memory-ledger" / ".nudge-state" / f"{self.session_id}.last"
        return json.loads(marker_path.read_text())

    def test_nudges_on_any_tool_no_filter(self):
        # A plain Write call (not search-shaped) must still nudge: there is
        # no tool filter.
        out = self._run("Write", {"file_path": "/tmp/x.py", "content": "x"})
        self.assertIn("hookSpecificOutput", out)
        self.assertIn("memory-ledger", out["hookSpecificOutput"]["additionalContext"])

    def test_cooldown_suppresses_second_nudge(self):
        self._run("Write", {"file_path": "/tmp/x.py"})
        out = self._run("Bash", {"command": "ls"})
        self.assertEqual(out, {})

    def test_ledger_invocation_resets_without_nudging(self):
        out = self._run("Bash", {"command": "python3 ledger.py resolve 'q'"})
        self.assertEqual(out, {})
        self.assertEqual(self._marker()["event"], "ledger-used")

    def test_quoted_ledger_path_counts_as_invocation(self):
        out = self._run("Bash", {"command": 'python3 "/x/scripts/ledger.py" resolve q'})
        self.assertEqual(out, {})
        self.assertEqual(self._marker()["event"], "ledger-used")

    def test_ledger_word_inside_a_name_is_not_an_invocation(self):
        self._run("Bash", {"command": "cat ledgerlib/x.py my-ledger.pyc"})
        self.assertEqual(self._marker()["event"], "nudged")

    def test_repeated_unfollowed_nudges_stay_ordinary_wording(self):
        # nudge.py deliberately carries no escalation logic (unlike engine's
        # state_nudge_reminder.py): its trigger set is broad enough that a
        # firing streak has little analytical value, so every unfollowed
        # nudge reads identically.
        marker_path = self.home / ".memory-ledger" / ".nudge-state" / f"{self.session_id}.last"
        import os
        import time

        first = self._run("Write", {"file_path": "/tmp/a.py"})
        self.assertEqual(self._marker()["event"], "nudged")

        past = time.time() - 301
        os.utime(marker_path, (past, past))
        second = self._run("Bash", {"command": "ls"})

        self.assertEqual(
            first["hookSpecificOutput"]["additionalContext"],
            second["hookSpecificOutput"]["additionalContext"],
        )
        self.assertEqual(self._marker()["event"], "nudged")

    def test_reports_unconfigured_without_nudging(self):
        bare_home = Path(tempfile.mkdtemp(prefix="nudge-hook-test-bare-"))
        payload = {
            "session_id": self.session_id,
            "hook_event_name": "PostToolUse",
            "tool_name": "Write",
            "tool_input": {},
        }
        result = subprocess.run(
            ["python3", str(HOOK)],
            input=json.dumps(payload),
            capture_output=True, text=True,
            env={"HOME": str(bare_home), "PATH": "/usr/bin:/bin"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            {"hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": "memory-ledger: unconfigured",
            }},
        )


if __name__ == "__main__":
    unittest.main()
