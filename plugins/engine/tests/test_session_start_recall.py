"""Subprocess-level tests for the SessionStart (compact) recall hook.

Drives `hooks/session_start_recall.py` the same way the platform actually
invokes it: JSON on stdin, JSON on stdout, with HOME pointed at a scratch
directory holding the session ledger. Exercises the 3-level principles merge
and each source's independent failure handling.
"""
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
HOOK = PLUGIN_DIR / "hooks" / "session_start_recall.py"

SETTLEMENT = """\
task_type: ticket-to-pr
approach: smoke test
principles: task-level principle text
source_of_truth:
  scope: ticket
debate_threshold: any
debate_round_cap: 10
convergence_policy: unanimous
consented_stop_allowed: true
debate_roster: [main-agent, independent-reviewer, adversarial-reviewer]
debate_party_config: {{}}
spec_skill: spec
test_skill: test
review_skill: review
autonomy:
  no_further_questions: true
  permitted_mutations: [commit]
goal: succeeded when done. failed when undoable.
session_dir: {session_dir}
"""


class SessionStartRecallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cwd = Path(self.tmp.name) / "project"
        self.home = Path(self.tmp.name) / "home"
        self.home.mkdir()
        self.session_dir = self.home / ".bootgear" / "session"
        self.session_dir.mkdir(parents=True)
        self.cwd_session_dir = self.cwd / ".bootgear" / "session"
        self.config_dir = self.cwd / ".bootgear" / "config"
        self.config_dir.mkdir(parents=True)
        self.run_id = "test-run-id"
        self.ledger = self.session_dir / f"{self.run_id}.md"
        self.ledger.write_text(
            "## settlement\n"
            + SETTLEMENT.format(session_dir=self.session_dir)
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _run_raw(self, run_id=None):
        result = subprocess.run(
            ["python3", str(HOOK)],
            input=json.dumps({
                "session_id": run_id or self.run_id,
                "cwd": str(self.cwd),
                "hook_event_name": "SessionStart",
                "source": "compact",
            }),
            capture_output=True,
            text=True,
            env={**os.environ, "HOME": str(self.home)},
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)["hookSpecificOutput"]

    def _run(self, run_id=None):
        return self._run_raw(run_id)["additionalContext"]

    def _set_mapping_goal(self):
        self.ledger.write_text(
            self.ledger.read_text().replace(
                "goal: succeeded when done. failed when undoable.",
                "goal:\n  succeeded: the mapping goal is rendered\n  failed: the mapping goal cannot be rendered\n",
            )
        )

    def test_mapping_goal_is_rendered(self):
        self._set_mapping_goal()
        msg = self._run()
        self.assertIn(
            "This run's /goal:\nsucceeded when the mapping goal is rendered\n"
            "failed when the mapping goal cannot be rendered",
            msg,
        )

    def test_emits_session_start_event(self):
        self.assertEqual(self._run_raw()["hookEventName"], "SessionStart")

    def test_no_sources_present_base_message_only(self):
        msg = self._run()
        self.assertIn("This session just compacted", msg)
        self.assertIn("This run's /goal:\nsucceeded when done", msg)
        self.assertIn("[task]", msg)
        self.assertNotIn("[project]", msg)
        self.assertNotIn("[user]", msg)

    def test_all_three_levels_present(self):
        (self.config_dir / "principles.md").write_text("- project rule\n")
        (self.home / ".claude").mkdir()
        (self.home / ".claude" / "principles.md").write_text("- user rule\n")
        msg = self._run()
        self.assertIn("[user]\n- user rule", msg)
        self.assertIn("[project]\n- project rule", msg)
        self.assertIn("[task]\ntask-level principle text", msg)

    def test_missing_project_file_only_skips_that_source(self):
        (self.home / ".claude").mkdir()
        (self.home / ".claude" / "principles.md").write_text("- user rule\n")
        msg = self._run()
        self.assertIn("[user]", msg)
        self.assertNotIn("[project]", msg)
        self.assertIn("[task]", msg)

    def test_empty_project_file_treated_as_absent(self):
        (self.config_dir / "principles.md").write_text("   \n\n")
        msg = self._run()
        self.assertNotIn("[project]", msg)
        self.assertIn("[task]", msg)

    def test_directory_instead_of_file_does_not_crash_other_sources(self):
        # A directory named principles.md where a file is expected.
        (self.config_dir / "principles.md").mkdir()
        msg = self._run()
        self.assertNotIn("[project]", msg)
        self.assertIn("[task]", msg)
        self.assertIn("This session just compacted", msg)

    def test_non_utf8_file_does_not_crash_other_sources(self):
        (self.config_dir / "principles.md").write_bytes(b"\xff\xfe\x00bad-utf8")
        (self.home / ".claude").mkdir()
        (self.home / ".claude" / "principles.md").write_text("- user rule\n")
        msg = self._run()
        self.assertNotIn("[project]", msg)
        self.assertIn("[user]\n- user rule", msg)
        self.assertIn("[task]", msg)

    def test_nonexistent_run_id_still_reads_project_level(self):
        (self.config_dir / "principles.md").write_text("- project rule\n")
        out = self._run("no-such-run")
        self.assertIn("[project]\n- project rule", out)
        self.assertNotIn("[task]", out)

    def test_cwd_ledger_is_not_a_run_location(self):
        self.cwd_session_dir.mkdir(parents=True)
        self.ledger.rename(self.cwd_session_dir / f"{self.run_id}.md")
        msg = self._run()
        self.assertNotIn("succeeded when done", msg)
        self.assertNotIn("[task]", msg)

    def test_home_ledger_found_when_cwd_session_dir_holds_other_runs(self):
        self.cwd_session_dir.mkdir(parents=True)
        (self.cwd_session_dir / "other-run.md").write_text(
            "## settlement\n" + SETTLEMENT.format(session_dir=self.cwd_session_dir)
        )
        msg = self._run()
        self.assertIn("succeeded when done", msg)
        self.assertIn("[task]", msg)


if __name__ == "__main__":
    unittest.main()
