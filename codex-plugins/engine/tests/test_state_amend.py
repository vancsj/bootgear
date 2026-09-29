"""CLI-level tests for mid-run state machine amendment.

Drives the host `task` wrapper as a subprocess against scratch ledgers:
`state amend` appends to `## machines`, `state show` prints the machine in
force, `state transition` enforces it, and ledgers without the section (or
with a column-0 `## machines` line inside settlement) keep working.
"""
import json
import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

import yaml

PLUGIN_DIR = Path(__file__).resolve().parents[1]
TASK_BIN = PLUGIN_DIR / "scripts" / "task"

SETTLEMENT_HEAD = """\
task_type: ticket-to-pr
approach: amend test
goal:
  succeeded: amend works
  failed: never
state_machine: |
"""

V1 = """\
name: amendable
nodes:
  clarify:
    next: [work]
  work:
    next: [succeeded]
  succeeded:
    terminal: true
  failed:
    terminal: true
"""

# Adds `fix`, keeps `work -> succeeded`.
V2 = """\
name: amendable
nodes:
  clarify:
    next: [work]
  work:
    reminder:
      do: "Work, then fix or finish."
      branches:
        fix: "A correction is needed."
        succeeded: "Done."
    next: [fix, succeeded]
  fix:
    next: [work]
  succeeded:
    terminal: true

  failed:
    terminal: true
"""

# Removes `work -> succeeded`; `succeeded` is reached through `fix`.
V2_NO_FINISH = """\
name: amendable
nodes:
  clarify:
    next: [work]
  work:
    next: [fix]
  fix:
    next: [work, succeeded]
  succeeded:
    terminal: true
  failed:
    terminal: true
"""

# Valid, but drops `work`.
NO_WORK = """\
name: amendable
nodes:
  clarify:
    next: [fix]
  fix:
    next: [succeeded]
  succeeded:
    terminal: true
  failed:
    terminal: true
"""

# `work` carries a leave gate.
GATED = V1.replace("  work:\n    next: [succeeded]\n",
                   "  work:\n    reminder:\n      leave: \"work is recorded\"\n"
                   "    next: [succeeded]\n")

# Valid, but `succeeded` is unreachable from `work`.
WORK_LOOPS = """\
name: amendable
nodes:
  clarify:
    next: [work, succeeded]
  work:
    next: [fix]
  fix:
    next: [work]
  succeeded:
    terminal: true
  failed:
    terminal: true
"""

# V2 with block scalars whose trailing newlines and indented blank lines a
# raw-text copy would not round-trip.
V2_BLOCK = V2 + "description: |+\n  a\n     \n  b\n\n\n"

# `giveup` can only end the run `failed`.
FAIL_ONLY = """\
name: amendable
nodes:
  clarify:
    next: [work, giveup]
  work:
    next: [succeeded]
  giveup:
    next: [failed]
  succeeded:
    terminal: true
  failed:
    terminal: true
"""


def _task(*args):
    return subprocess.run([str(TASK_BIN), *args], capture_output=True,
                          text=True, check=False,
                          env={**os.environ, "BOOTGEAR_OUTPUT": "prose"})


def _settlement(machine: str, extra: str = "") -> str:
    return SETTLEMENT_HEAD.replace("approach: amend test\n",
                                   f"approach: amend test\n{extra}") \
        + textwrap.indent(machine, "  ")


class StateAmendTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="engine-state-amend-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.dir = str(self.tmp)
        self.ledger = self.tmp / "run.md"

    def _ok(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def _refused(self, result, *needles):
        self.assertNotEqual(result.returncode, 0, result.stdout)
        for needle in needles:
            self.assertIn(needle, result.stderr)
        return result

    def _init(self, machine=V1):
        settlement = self.tmp / "settlement.txt"
        settlement.write_text(_settlement(machine))
        self._ok(_task("session", "init", "run", "--dir", self.dir,
                       "--settlement-file", str(settlement)))

    def _machine(self, text, name="machine.yaml"):
        path = self.tmp / name
        path.write_text(text)
        return str(path)

    def _amend(self, text, reason="add fix", name="machine.yaml"):
        return _task("state", "amend", "run", "--dir", self.dir,
                     "--machine-file", self._machine(text, name), "--reason", reason)

    def _transition(self, dest, reason="next"):
        return _task("state", "transition", "run", "--dir", self.dir,
                     "--to", dest, "--reason", reason)

    def _show(self):
        return json.loads(self._ok(_task("state", "show", "run", "--dir", self.dir,
                                         "--json")).stdout)

    def _at_work(self, machine=V1):
        self._init(machine)
        self._ok(self._transition("work"))

    def test_amend_then_transition_into_a_node_only_v2_has(self):
        self._at_work()
        self._refused(self._transition("fix"), "'fix' is not a node")
        result = self._ok(self._amend(V2))
        self.assertIn("AMENDED  state_machine v1 -> v2 at work (added: fix; "
                      "removed: none; edges changed: work)", result.stdout)
        self.assertIn("do: Work, then fix or finish.", result.stdout)
        self._ok(self._transition("fix"))
        self._ok(self._transition("work"))
        text = self.ledger.read_text()
        self.assertIn("[solo] AMENDMENT state_machine: v1 -> v2 (added: fix; removed: "
                      "none; full machine in ## machines), add fix", text)
        self.assertIn("\n## machines\n- v2 ", text)
        self.assertIn(" at work (add fix)\n  name: amendable\n", text)
        self.assertNotIn("\n\n    failed:", text)
        self._ok(_task("session", "read", "run", "--dir", self.dir))

    def test_an_edge_removed_in_v2_is_refused(self):
        self._at_work()
        self._ok(self._amend(V2_NO_FINISH, "route finishing through fix"))
        self._refused(self._transition("succeeded"),
                      "'work' has no transition to 'succeeded'")
        self._ok(self._transition("fix"))
        self._ok(self._transition("succeeded"))

    def test_an_invalid_machine_is_refused_with_its_problems(self):
        self._at_work()
        bad = V2.replace("  fix:\n    next: [work]\n", "  fix:\n    next: [nowhere]\n")
        self._refused(self._amend(bad), "--machine-file",
                      "`next:` destination 'nowhere' is not a defined node")
        self.assertNotIn("## machines", self.ledger.read_text())

    def test_a_machine_missing_the_current_node_is_refused(self):
        self._at_work()
        self._refused(self._amend(NO_WORK), "has no 'work' node")

    def test_an_identical_machine_is_refused(self):
        self._at_work()
        self._refused(self._amend(V1), "identical to the machine in force (v1)")
        self._ok(self._amend(V2))
        self._refused(self._amend(V2), "identical to the machine in force (v2)")

    def test_a_closed_ledger_is_refused(self):
        self._at_work()
        self._ok(self._transition("succeeded"))
        self._ok(_task("session", "close", "run", "--dir", self.dir, "succeeded"))
        self._refused(self._amend(V2), "is closed")

    def test_a_terminal_current_node_is_refused(self):
        self._at_work()
        self._ok(self._transition("succeeded"))
        self._refused(self._amend(V2.replace("  work:\n", "  work:\n    max_visits: 3\n")),
                      "'succeeded' is terminal")

    def test_a_reason_containing_an_arrow_is_refused(self):
        self._at_work()
        self._refused(self._amend(V2, "work -> fix"), "--reason", "' -> '")

    def test_every_problem_is_reported_together(self):
        self._at_work()
        result = self._refused(self._amend(V1, "a -> b"), "2 problem(s)")
        self.assertIn("identical", result.stderr)
        self.assertIn("' -> '", result.stderr)

    def test_v3_follows_v2(self):
        self._at_work()
        self._ok(self._amend(V2))
        result = self._ok(self._amend(V2_NO_FINISH, "route finishing through fix",
                                      "v3.yaml"))
        self.assertIn("v2 -> v3 at work (added: none; removed: none; "
                      "edges changed: work, fix)", result.stdout)
        shown = self._show()
        self.assertEqual((shown["version"], shown["source"]), (3, "## machines v3"))
        self.assertEqual(self.ledger.read_text().count("\n## machines\n"), 1)

    def test_show_before_and_after(self):
        self._at_work()
        before = self._show()
        self.assertEqual((before["version"], before["source"], before["current"]),
                         (1, "settlement", "work"))
        self.assertNotIn("fix", before["machine"]["nodes"])
        prose = self._ok(_task("state", "show", "run", "--dir", self.dir)).stdout
        self.assertTrue(prose.startswith("MACHINE  v1 (settlement)\nname: amendable\n"))
        self._ok(self._amend(V2))
        after = self._show()
        self.assertEqual((after["version"], after["source"]), (2, "## machines v2"))
        self.assertIn("fix", after["machine"]["nodes"])
        prose = self._ok(_task("state", "show", "run", "--dir", self.dir)).stdout
        self.assertTrue(prose.startswith("MACHINE  v2 (## machines v2)\n"))

    def test_an_out_of_order_machines_entry_is_refused(self):
        self._at_work()
        self._ok(self._amend(V2))
        self.ledger.write_text(self.ledger.read_text().replace("\n- v2 ", "\n- v3 "))
        self._refused(_task("state", "show", "run", "--dir", self.dir),
                      "## machines v3 is out of sequence — expected v2")
        self._refused(self._transition("fix"), "out of sequence")

    def test_a_machines_entry_that_is_not_yaml_is_refused(self):
        self._at_work()
        self._ok(self._amend(V2))
        head, _, tail = self.ledger.read_text().partition("\n## machines\n")
        self.ledger.write_text(head + "\n## machines\n"
                               + tail.replace("  name: amendable", "  name: [unclosed", 1))
        self._refused(_task("state", "show", "run", "--dir", self.dir),
                      "## machines v2 is not valid YAML")

    def test_a_ledger_without_machines_reads_transitions_and_closes(self):
        self._at_work()
        read = json.loads(self._ok(_task("session", "read", "run", "--dir", self.dir,
                                         "--json")).stdout)
        self.assertEqual(read["sections"]["machines"], [])
        section = self._ok(_task("session", "read", "run", "--dir", self.dir,
                                 "--section", "machines"))
        self.assertEqual(section.stdout.strip(), "(none)")
        self._ok(self._transition("succeeded"))
        self._ok(_task("session", "close", "run", "--dir", self.dir, "succeeded"))
        self.assertNotIn("## machines", self.ledger.read_text())

    def test_record_decision_refuses_a_state_machine_amendment(self):
        self._at_work()
        self._refused(_task("session", "record-decision", "run", "--dir", self.dir,
                            "--mode", "solo", "--summary",
                            "AMENDMENT state_machine: v1 -> v2"),
                      "state amend run --dir", "--machine-file")

    def _old_style_ledger(self):
        """A ledger as an older engine version could write it: settlement holds a
        column-0 `## machines` line, no `## machines` section follows."""
        self.ledger.write_text(
            "# session: run — 2026-09-24\n\n"
            "## settlement\n" + _settlement(V1, "## machines\n")
            + f"session_dir: {self.tmp}\n\n"
            "## decisions\n\n## todos\n\n## pitches\n\n"
            "## state\ncurrent: clarify\nstarted: 2026-09-24 10:00\n")

    def test_an_old_ledger_with_machines_in_settlement_reads_transitions_and_closes(self):
        self._old_style_ledger()
        read = json.loads(self._ok(_task("session", "read", "run", "--dir", self.dir,
                                         "--json")).stdout)
        self.assertIn("## machines", read["sections"]["settlement"])
        self.assertEqual(read["sections"]["machines"], [])
        self.assertEqual(self._show()["version"], 1)
        self._ok(self._transition("work"))
        self._ok(self._transition("succeeded"))
        self._ok(_task("session", "close", "run", "--dir", self.dir, "succeeded"))

    def test_an_old_ledger_with_machines_in_settlement_can_be_amended(self):
        self._old_style_ledger()
        self._ok(self._transition("work"))
        self._ok(self._amend(V2))
        self.assertEqual(self._show()["version"], 2)
        self._ok(self._transition("fix"))

    def test_init_refuses_a_column_0_machines_line_in_settlement(self):
        settlement = self.tmp / "settlement.txt"
        settlement.write_text(_settlement(V1, "## machines\n"))
        self._refused(_task("session", "init", "run", "--dir", self.dir,
                            "--settlement-file", str(settlement)),
                      "reads as a ledger section heading")

    def test_absent_and_empty_machines_both_give_v1(self):
        self._at_work()
        self.assertEqual(self._show()["version"], 1)
        self.ledger.write_text(self.ledger.read_text() + "\n## machines\n")
        shown = self._show()
        self.assertEqual((shown["version"], shown["source"]), (1, "settlement"))
        self._ok(self._transition("succeeded"))

    def test_amend_reuses_an_empty_heading(self):
        self._at_work()
        self.ledger.write_text(self.ledger.read_text() + "\n## machines\n")
        self._ok(self._amend(V2))
        text = self.ledger.read_text()
        self.assertEqual(text.count("## machines\n"), 1)
        self.assertIn("\n## machines\n- v2 ", text)
        self.assertEqual(self._show()["version"], 2)

    def test_a_duplicated_machines_heading_is_malformed(self):
        self._at_work()
        self._ok(self._amend(V2))
        self.ledger.write_text(self.ledger.read_text() + "\n## machines\n")
        self._refused(_task("session", "read", "run", "--dir", self.dir),
                      "'## machines' ×2")

    def test_closed_must_follow_machines(self):
        self._at_work()
        self._ok(self._amend(V2))
        self._ok(self._transition("succeeded"))
        self._ok(_task("session", "close", "run", "--dir", self.dir, "succeeded"))
        text = self.ledger.read_text()
        self.assertLess(text.index("\n## machines\n"), text.index("\n## closed\n"))
        self._ok(_task("session", "read", "run", "--dir", self.dir))


    def test_amend_json_keys_and_next(self):
        self._at_work()
        path = self._machine(V2)
        result = self._ok(_task("state", "amend", "run", "--dir", self.dir,
                                "--machine-file", path, "--reason", "add fix", "--json"))
        data = json.loads(result.stdout)
        self.assertEqual(set(data), {"from_version", "to_version", "current", "added",
                                     "removed", "edges_changed", "reminder", "next"})
        self.assertEqual((data["from_version"], data["to_version"], data["current"]),
                         (1, 2, "work"))
        self.assertEqual((data["added"], data["removed"], data["edges_changed"]),
                         (["fix"], [], ["work"]))
        self.assertEqual(data["next"], "Work, then fix or finish.")
        self.assertEqual(data["reminder"]["do"], "Work, then fix or finish.")

    def test_full_read_json_carries_the_machines_section(self):
        self._at_work()
        self._ok(self._amend(V2))
        read = json.loads(self._ok(_task("session", "read", "run", "--dir", self.dir,
                                         "--json")).stdout)
        machines = read["sections"]["machines"]
        self.assertTrue(machines[0].startswith("- v2 "))
        self.assertTrue(machines[0].endswith(" at work (add fix)"))
        self.assertIn("  name: amendable", machines)
        self.assertNotIn("current: work", machines)

    def test_a_block_scalar_machine_re_amended_identically_is_refused(self):
        self._at_work()
        self._ok(self._amend(V2_BLOCK))
        self.assertEqual(self._show()["machine"], yaml.safe_load(V2_BLOCK))
        self._refused(self._amend(V2_BLOCK), "identical to the machine in force (v2)")

    def test_amend_refuses_changing_the_current_nodes_gate(self):
        self._at_work(GATED)
        changed = GATED.replace("work is recorded", "anything goes")
        self._refused(self._amend(changed), "changes 'work''s `reminder.leave`",
                      "once the run has left 'work'")
        self._refused(self._amend(V1), "changes 'work''s `reminder.leave`")
        self._refused(self._amend(V2), "changes 'work''s `reminder.leave`")

    def test_a_fail_only_node_is_still_enterable(self):
        self._init(FAIL_ONLY)
        self._ok(self._transition("giveup"))
        self._ok(self._transition("failed"))

    def test_amend_refuses_a_machine_with_no_path_to_succeeded(self):
        self._at_work()
        self._refused(self._amend(WORK_LOOPS),
                      "no `next:` path from 'work' to 'succeeded'")


class PrReviewWalkTest(unittest.TestCase):
    """The built-in pr-review graph, leave gates stripped: every fix has a
    legal edge back to review, and fix's own max_visits bounds the loop."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="engine-state-pr-review-walk-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        machine = yaml.safe_load((PLUGIN_DIR / "state-machines" / "pr-review.yaml").read_text())
        for node in machine["nodes"].values():
            reminder = node.get("reminder") or {}
            reminder.pop("leave", None)
            reminder.pop("leave_check", None)
        settlement = self.tmp / "settlement.txt"
        settlement.write_text(_settlement(yaml.safe_dump(machine, sort_keys=False)))
        result = _task("session", "init", "run", "--dir", str(self.tmp),
                       "--settlement-file", str(settlement))
        self.assertEqual(result.returncode, 0, result.stderr)

    def _to(self, dest):
        return _task("state", "transition", "run", "--dir", str(self.tmp),
                     "--to", dest, "--reason", "walk")

    def test_four_fixes_each_return_to_review_and_a_fifth_is_capped(self):
        walk = ["inspect", "review", "review-debate", "review"] + ["fix", "review"] * 4
        for dest in walk:
            result = self._to(dest)
            self.assertEqual(result.returncode, 0, f"{dest}: {result.stderr}")
        refused = self._to("fix")
        self.assertNotEqual(refused.returncode, 0, refused.stdout)
        self.assertIn("'fix' has max_visits: 4", refused.stderr)
        self.assertIn("already entered it 4 time(s)", refused.stderr)
        self.assertEqual(self._to("succeeded").returncode, 0)

if __name__ == "__main__":
    unittest.main()
