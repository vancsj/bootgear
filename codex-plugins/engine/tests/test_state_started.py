"""CLI-level tests for the `started:` field in `## state`.

Drives `scripts/task` as a subprocess against a scratch ledger, the same
contract other tests in this suite use. Covers `cmd_transition` preserving
the `started:` header line in `## state`: rebuilding the section
positionally would fold it into the transition log and reorder it on the
first transition.
"""
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
TASK_BIN = PLUGIN_DIR / "scripts" / "task"

SETTLEMENT = """\
task_type: ticket-to-pr
approach: smoke test
principles: none
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
  permitted_mutations: [edit files]
goal:
  succeeded: smoke test passes
  failed: never
state_machine: |
  name: smoke
  nodes:
    clarify:
      next: [impl]
    impl:
      next: [succeeded]
    succeeded:
      terminal: true
    failed:
      terminal: true
session_dir: {session_dir}
"""

_STARTED_RE = re.compile(r"(?m)^started: (\d{4}-\d{2}-\d{2} \d{2}:\d{2})\s*$")


class StateStartedTest(unittest.TestCase):
    def setUp(self):
        self.session_dir = Path(tempfile.mkdtemp(prefix="engine-state-started-test-"))
        self.addCleanup(shutil.rmtree, self.session_dir, ignore_errors=True)
        settlement_file = self.session_dir / "settlement.txt"
        settlement_file.write_text(SETTLEMENT.format(session_dir=self.session_dir))
        self.run_id = "test-run"
        self._task("session", "init", self.run_id,
                   "--settlement-file", str(settlement_file))

    def _task(self, *args, expect_success=True):
        result = subprocess.run(
            [str(TASK_BIN), *args, "--dir", str(self.session_dir)],
            capture_output=True, text=True, check=False,
        )
        if expect_success:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def _state_section(self):
        return self._task("session", "read", self.run_id,
                           "--section", "state").stdout

    def test_init_writes_started(self):
        state = self._state_section()
        self.assertRegex(state, r"(?m)^current: clarify\s*$")
        self.assertRegex(state, _STARTED_RE)

    def test_started_survives_one_transition(self):
        before_match = _STARTED_RE.search(self._state_section())
        self.assertIsNotNone(before_match)
        assert before_match is not None
        before = before_match.group(1)
        self._task("state", "transition", self.run_id,
                   "--to", "impl", "--reason", "first")
        state = self._state_section()
        m = _STARTED_RE.search(state)
        self.assertIsNotNone(m, f"started: line missing after transition:\n{state}")
        assert m is not None
        self.assertEqual(m.group(1), before)
        # started: must stay a header line, never folded into the log as
        # if it were itself a "- <ts> a -> b (reason)" transition entry.
        for line in state.splitlines():
            if line.startswith("- "):
                self.assertNotIn("started:", line)

    def test_started_survives_two_transitions_and_log_order_is_preserved(self):
        before_match = _STARTED_RE.search(self._state_section())
        self.assertIsNotNone(before_match)
        assert before_match is not None
        before = before_match.group(1)
        self._task("state", "transition", self.run_id,
                   "--to", "impl", "--reason", "first")
        self._task("state", "transition", self.run_id,
                   "--to", "succeeded", "--reason", "second")
        state = self._state_section()
        lines = state.splitlines()

        self.assertEqual(lines[0], "current: succeeded")
        m = _STARTED_RE.search(state)
        self.assertIsNotNone(m)
        assert m is not None
        self.assertEqual(m.group(1), before)

        log_lines = [line for line in lines if line.startswith("- ")]
        self.assertEqual(len(log_lines), 2)
        self.assertIn("clarify -> impl (first)", log_lines[0])
        self.assertIn("impl -> succeeded (second)", log_lines[1])


if __name__ == "__main__":
    unittest.main()
