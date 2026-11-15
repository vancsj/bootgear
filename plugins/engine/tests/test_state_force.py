"""Force bypasses workflow controls and preserves valid run data."""
import json

from test_state_leave_check import _exit_machine, _LeaveCheckLedger, _machine


class ForceTransitionTest(_LeaveCheckLedger):
    def test_current_exposes_the_run_specific_destination_choices(self):
        self._init()
        result = self._task("state", "current", self.run_id, "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["destinations"], ["done", "failed"])

    def test_force_skips_leave_confirmation_and_check_with_visible_record(self):
        self._init()
        result = self._move("done", "--force", CHECK_EXIT="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.argv_file.exists())
        self.assertIn("gate -> done (to done)", self._log_lines()[-1])
        for value in ("force", "requested=done", "leave-confirmation", "leave-check"):
            self.assertIn(value, self._log_lines()[-1])
            self.assertIn(value, result.stdout)
        self.assertNotIn("## closed", self.ledger.read_text())

    def test_force_json_names_requested_destination_reason_and_bypasses(self):
        self._init()
        result = self._move("done", "--force", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertTrue(report["force"])
        self.assertEqual(report["requested"], "done")
        self.assertEqual(report["reason"], "to done")
        self.assertEqual(report["bypassed"], ["leave-confirmation", "leave-check"])
        self.assertIn("state current", report["next"])

    def test_force_skips_exit_program_and_its_fallback(self):
        self._init(_exit_machine())
        result = self._move("done", "--force", CHECK_EXIT="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.argv_file.exists())
        self.assertIn("current: done", self.ledger.read_text())
        self.assertIn("exit-check", result.stdout)
        self.assertNotIn("-> retry", self.ledger.read_text())

    def test_force_crosses_an_absent_edge(self):
        self._init()
        before = self.ledger.read_bytes()
        ordinary = self._move("clarify")
        self.assertNotEqual(ordinary.returncode, 0)
        self.assertEqual(self.ledger.read_bytes(), before)
        result = self._move("clarify", "--force")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("edge", result.stdout)

    def test_force_crosses_visit_cap_and_preserves_visit_counting(self):
        machine = _machine().replace("  done:\n", "  done:\n    max_visits: 1\n")
        self._init(machine)
        self.assertEqual(self._move("done", "--force").returncode, 0)
        self.assertEqual(self._move("gate", "--force").returncode, 0)
        ordinary = self._move("done")
        self.assertIn("already entered it 1 time(s)", ordinary.stderr)
        result = self._move("done", "--force")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("visit-cap", result.stdout)

    def test_force_can_leave_a_terminal_node_while_the_run_is_open(self):
        self._init()
        self.assertEqual(self._move("failed").returncode, 0)
        result = self._move("done", "--force")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("terminal-node", result.stdout)
        self.assertNotIn("## closed", self.ledger.read_text())

    def test_force_rejects_closed_run_without_writes(self):
        self._init()
        self.assertEqual(self._move("failed").returncode, 0)
        closed = self._task("session", "close", self.run_id, "--outcome", "failed",
                            "--reason", "The fixture cannot continue.")
        self.assertEqual(closed.returncode, 0, closed.stderr)
        before = self.ledger.read_bytes()
        result = self._move("done", "--force")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("closed", result.stderr)
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_force_keeps_destination_reason_and_input_validation(self):
        self._init()
        cases = [
            (["--to", "missing", "--reason", "inspect"], "not a node"),
            (["--to", "done", "--reason", " "], "cannot be blank"),
            (["--to", "done", "--reason", "inspect", "--leave-arg", "broken"],
             "not name=value"),
        ]
        for arguments, message in cases:
            with self.subTest(arguments=arguments):
                before = self.ledger.read_bytes()
                result = self._task("state", "transition", self.run_id, "--force", *arguments)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)
                self.assertEqual(self.ledger.read_bytes(), before)
