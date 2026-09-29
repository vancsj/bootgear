"""CLI-level tests for a node's `max_visits` cap.

Drives the host `task` wrapper as a subprocess against scratch ledgers and
scratch machine files: `state validate` for the schema, `state transition`
for the Nth-entry refusal counted from the `## state` log.
"""
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
TASK_BIN = PLUGIN_DIR / "scripts" / "task"

SETTLEMENT_HEAD = """\
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
"""

# `loop` may be entered twice; `clarify` twice counting init's implicit entry.
MACHINE = """\
name: capped
nodes:
  clarify:
    max_visits: 2
    next: [loop]
  loop:
    max_visits: 2
    next: [loop, back, succeeded]
  back:
    next: [clarify]
  succeeded:
    terminal: true
  failed:
    terminal: true
"""


def _task(*args, cwd=None):
    return subprocess.run([str(TASK_BIN), *args], capture_output=True,
                          text=True, check=False, cwd=cwd)


class MaxVisitsSchemaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="engine-max-visits-schema-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _validate(self, clarify_extra="", succeeded_extra=""):
        path = self.tmp / "machine.yaml"
        path.write_text(
            "name: m\nnodes:\n"
            f"  clarify:\n{clarify_extra}    next: [succeeded]\n"
            f"  succeeded:\n    terminal: true\n{succeeded_extra}"
            "  failed:\n    terminal: true\n"
        )
        return _task("state", "validate", str(path))

    def test_positive_integer_is_valid(self):
        for value in ("1", "5"):
            with self.subTest(value=value):
                result = self._validate(clarify_extra=f"    max_visits: {value}\n")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn(": ok", result.stdout)

    def test_non_positive_or_non_integer_is_a_problem(self):
        for value in ("0", "-1", "'3'", "true", "1.5", "null"):
            with self.subTest(value=value):
                result = self._validate(clarify_extra=f"    max_visits: {value}\n")
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn("`max_visits` must be a positive integer", result.stdout)

    def test_terminal_node_may_not_set_it(self):
        result = self._validate(succeeded_extra="    max_visits: 1\n")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("node 'succeeded': `max_visits` is not allowed on a terminal node",
                      result.stdout)


class MaxVisitsTransitionTest(unittest.TestCase):
    def setUp(self):
        self.session_dir = Path(tempfile.mkdtemp(prefix="engine-max-visits-"))
        self.addCleanup(shutil.rmtree, self.session_dir, ignore_errors=True)
        settlement = self.session_dir / "settlement.txt"
        settlement.write_text(
            SETTLEMENT_HEAD.format()
            + textwrap.indent(MACHINE, "  ")
            + f"session_dir: {self.session_dir}\n"
        )
        self.run_id = "test-run"
        self.ledger = self.session_dir / f"{self.run_id}.md"
        result = self._transition_raw("session", "init", self.run_id,
                                      "--settlement-file", str(settlement))
        self.assertEqual(result.returncode, 0, result.stderr)

    def _transition_raw(self, *args):
        return _task(*args, "--dir", str(self.session_dir))

    def _move(self, dest, expect_success=True):
        result = self._transition_raw("state", "transition", self.run_id,
                                      "--to", dest, "--reason", f"to {dest}")
        if expect_success:
            self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def _assert_refused_unchanged(self, dest):
        before = self.ledger.read_bytes()
        result = self._move(dest, expect_success=False)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.ledger.read_bytes(), before)
        return result

    def test_entry_past_the_cap_is_refused_naming_it_and_failed(self):
        self._move("loop")
        self._move("loop")
        result = self._assert_refused_unchanged("loop")
        self.assertIn("'loop' has max_visits: 2", result.stderr)
        self.assertIn("already entered it 2 time(s)", result.stderr)
        self.assertIn("'failed' stays legal", result.stderr)

    def test_failed_stays_legal_at_the_cap(self):
        self._move("loop")
        self._move("loop")
        self._assert_refused_unchanged("loop")
        self._move("failed")
        state = self.ledger.read_text()
        self.assertIn("current: failed", state)

    def test_start_node_counts_the_implicit_init_entry(self):
        self._move("loop")
        self._move("back")
        self._move("clarify")
        self._move("loop")
        self._move("back")
        result = self._assert_refused_unchanged("clarify")
        self.assertIn("'clarify' has max_visits: 2", result.stderr)

    def test_other_destinations_are_unaffected_by_the_cap(self):
        self._move("loop")
        self._move("loop")
        self._move("succeeded")
        self.assertIn("current: succeeded", self.ledger.read_text())


if __name__ == "__main__":
    unittest.main()
