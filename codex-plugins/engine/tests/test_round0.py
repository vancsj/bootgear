"""CLI-level tests for the round-0 scoping phase in `session.py`.

Drives `scripts/task` as a subprocess against a scratch ledger, the same
contract `debate/SKILL.md` and `execute` actually use, rather than
importing session.py's internals directly.
"""
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
      next: [succeeded]
    succeeded:
      terminal: true
    failed:
      terminal: true
session_dir: {session_dir}
"""


class Round0Test(unittest.TestCase):
    def setUp(self):
        self.session_dir = Path(tempfile.mkdtemp(prefix="engine-round0-test-"))
        self.addCleanup(shutil.rmtree, self.session_dir, ignore_errors=True)
        settlement_file = self.session_dir / "settlement.txt"
        settlement_file.write_text(SETTLEMENT.format(session_dir=self.session_dir))
        self.run_id = "test-run"
        self._task("session", "init", self.run_id,
                   "--settlement-file", str(settlement_file))
        self._task("session", "next-question-id", self.run_id)

    def _task(self, *args, expect_success=True):
        result = subprocess.run(
            [str(TASK_BIN), *args, "--dir", str(self.session_dir)],
            capture_output=True, text=True, check=False,
        )
        if expect_success:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def _record(self, mode, summary, question="q1", expect_success=True):
        return self._task("session", "record-decision", self.run_id,
                           "--mode", mode, "--question", question,
                           "--summary", summary, expect_success=expect_success)

    def test_round1_before_round0_is_rejected(self):
        result = self._record(
            "debate", "round 1, party 'main agent': premature substance",
            expect_success=False)
        self.assertIn("must be 'round 0", result.stderr)

    def test_scope_settled_as_first_entry_is_rejected(self):
        result = self._record(
            "scope-settled", "scope_settled: premature close",
            expect_success=False)
        self.assertIn("round-0 scoping phase has no entries yet", result.stderr)

    def test_round1_after_round0_but_before_scope_settled_is_rejected(self):
        self._record("debate", "round 0, party 'main agent': stance")
        result = self._record(
            "debate", "round 1, party 'main agent': jumping ahead",
            expect_success=False)
        self.assertIn("no scope-settled close yet", result.stderr)

    def test_full_round0_then_round1_succeeds(self):
        self._record("debate", "round 0, party 'main agent': stance")
        self._record("scope-settled",
                      "scope_settled: topic X, scope Y, principles Z, cutoff W")
        self._record("debate", "round 1, party 'main agent': real position")

        result = self._task("session", "read", self.run_id, "--question", "q1")
        self.assertIn("round 0, party 'main agent'", result.stdout)
        self.assertIn("scope_settled:", result.stdout)
        self.assertIn("round 1, party 'main agent'", result.stdout)

    def test_scope_settled_does_not_close_the_question(self):
        self._record("debate", "round 0, party 'main agent': stance")
        self._record("scope-settled",
                      "scope_settled: topic X, scope Y, principles Z, cutoff W")

        result = self._task("session", "close", self.run_id, "succeeded",
                             expect_success=False)
        self.assertIn("q1", result.stderr)
        self.assertIn("no closing entry yet", result.stderr)


if __name__ == "__main__":
    unittest.main()
