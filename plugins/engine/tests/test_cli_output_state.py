import json
import shlex
import subprocess

from cli_output_test_support import SETTLEMENT, CliOutputTestCase, _env


class CliOutputTest(CliOutputTestCase):
    def test_transition_to_succeeded_names_close(self):
        result = self._session("record-pitch", "shipped")
        self.assertTrue(json.loads(result.stdout)["line"].endswith(" — shipped"))
        result = self._json_task("state", "transition", self.run_id, "--dir",
                                 str(self.session_dir), "--to", "succeeded",
                                 "--reason", "done")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual((data["from"], data["to"], data["reminder"]),
                         ("clarify", "succeeded", None))
        self.assertIn("condition genuinely holds now", data["confirm"])
        self.assertEqual(data["next"], f"{self.prog} session close {self.run_id} --dir "
                                       f"{self.session_dir.resolve()} --outcome succeeded")

    def test_transition_prose_ends_with_next_on_terminal_only(self):
        result = self._task("state", "transition", self.run_id, "--dir",
                            str(self.session_dir), "--to", "failed",
                            "--reason", "cannot", "--prose")
        lines = result.stdout.splitlines()
        self.assertEqual(lines[0], "STATE    clarify -> failed")
        self.assertTrue(lines[1].startswith("CONFIRM  before entering 'failed'"))
        self.assertEqual(lines[2], f"next: {self.prog} session close {self.run_id} --dir "
                                   f"{self.session_dir.resolve()} --outcome failed --reason "
                                   f"\"<why the goal is undoable>\"")

    def test_state_current_prints_node_and_full_reminder(self):
        data = self._current_json()
        self.assertEqual(set(data), {"current", "terminal", "reminder", "next", "destinations"})
        self.assertEqual((data["current"], data["terminal"]), ("clarify", False))
        self.assertEqual(set(data["reminder"]),
                         {"do", "branches", "leave", "leave_check", "exit_checks"})
        self.assertEqual(data["reminder"]["do"], "check the output contract")
        self.assertEqual(data["next"], "check the output contract")
        prose = self._current(None, "--prose")
        self.assertEqual(prose.returncode, 0, prose.stderr)
        self.assertEqual(prose.stdout.splitlines(),
                         ["STATE    current: clarify", "do: check the output contract", "destinations: succeeded, failed"])

    def test_state_current_node_without_reminder(self):
        self._init_run("bare-run", SETTLEMENT.replace(
            "      reminder:\n        do: check the output contract\n", ""))
        prose = self._current("bare-run", "--prose")
        self.assertEqual(prose.returncode, 0, prose.stderr)
        self.assertEqual(prose.stdout.splitlines(),
                         ["STATE    current: clarify", "no reminder: work toward goal", "destinations: succeeded, failed"])
        data = self._current_json("bare-run")
        self.assertEqual(set(data), {"current", "terminal", "reminder", "destinations"})
        self.assertIsNone(data["reminder"])

    def test_state_current_reads_strip_chomping_machine_block(self):
        self._init_run("strip-run", SETTLEMENT.replace(
            "state_machine: |\n", "state_machine: |-\n"))
        data = self._current_json("strip-run")
        self.assertEqual((data["current"], data["terminal"]), ("clarify", False))

    def test_state_current_terminal_on_open_ledger_names_close(self):
        self._transition("succeeded")
        close = (f"{self.prog} session close {self.run_id} --dir "
                 f"{self.session_dir.resolve()} --outcome succeeded")
        prose = self._current(None, "--prose")
        self.assertEqual(prose.returncode, 0, prose.stderr)
        self.assertEqual(prose.stdout.splitlines(),
                         ["STATE    current: succeeded", "terminal: close the ledger",
                          f"next: {close}"])
        data = self._current_json()
        self.assertEqual((data["current"], data["terminal"], data["reminder"]),
                         ("succeeded", True, None))
        self.assertEqual(data["next"], close)

    def test_state_current_terminal_on_closed_ledger(self):
        self._transition("succeeded")
        closed = self._session("close", "succeeded")
        self.assertEqual(closed.returncode, 0, closed.stderr)
        prose = self._current(None, "--prose")
        self.assertEqual(prose.returncode, 0, prose.stderr)
        self.assertEqual(prose.stdout.splitlines(),
                         ["STATE    current: succeeded", "terminal: the run already ended"])
        self.assertNotIn("next", self._current_json())

    def test_state_current_reads_the_amended_machine(self):
        machine = self.tmp / "amended.yaml"
        machine.write_text(
            "name: smoke\n"
            "nodes:\n"
            "  clarify:\n"
            "    next: [succeeded]\n"
            "    reminder:\n"
            "      do: check the amended contract with the debate skill\n"
            "  succeeded:\n"
            "    terminal: true\n"
            "  failed:\n"
            "    terminal: true\n")
        amended = self._task("state", "amend", self.run_id, "--dir", str(self.session_dir),
                             "--machine-file", str(machine), "--reason", "r", "--prose")
        self.assertEqual(amended.returncode, 0, amended.stderr)
        self.assertEqual(self._current_json()["reminder"]["do"],
                         "check the amended contract with the debate skill")

    def test_legacy_reminder_skill_folds_into_do(self):
        legacy = SETTLEMENT.replace(
            "    clarify:\n      next: [succeeded]\n",
            "    clarify:\n      next: [work, succeeded]\n"
        ).replace(
            "        do: check the output contract\n",
            "        do: check the output contract\n        skill: test\n"
            "    work:\n      next: [succeeded]\n      reminder:\n        skill: debate\n")
        self._init_run_raw("old-run", legacy)
        prose = self._current("old-run", "--prose")
        self.assertEqual(prose.returncode, 0, prose.stderr)
        self.assertEqual(prose.stdout.splitlines(),
                         ["STATE    current: clarify",
                          "do: check the output contract Call the test skill.", "destinations: work, succeeded, failed"])
        data = self._current_json("old-run")
        self.assertEqual(data["reminder"]["do"],
                         "check the output contract Call the test skill.")
        self.assertNotIn("skill", data["reminder"])
        moved = self._json_task("state", "transition", "old-run", "--dir",
                                str(self.session_dir), "--to", "work", "--reason", "r")
        self.assertEqual(moved.returncode, 0, moved.stderr)
        reminder = json.loads(moved.stdout)["reminder"]
        self.assertEqual(reminder["do"], "Call the debate skill.")
        self.assertNotIn("skill", reminder)

    def test_terminal_node_with_reminder_has_no_next_once_closed(self):
        self._init_run("pitch-run", SETTLEMENT.replace(
            "    succeeded:\n      terminal: true\n",
            "    succeeded:\n      terminal: true\n      reminder:\n        do: report the pitch\n"))
        moved = self._task("state", "transition", "pitch-run", "--dir", str(self.session_dir),
                           "--to", "succeeded", "--reason", "r", "--prose")
        self.assertEqual(moved.returncode, 0, moved.stderr)
        close = (f"{self.prog} session close pitch-run --dir "
                 f"{self.session_dir.resolve()} --outcome succeeded")
        self.assertEqual(self._current_json("pitch-run")["next"], close)
        closed = self._json_task("session", "close", "pitch-run", "--dir",
                                 str(self.session_dir), "succeeded")
        self.assertEqual(closed.returncode, 0, closed.stderr)
        data = self._current_json("pitch-run")
        self.assertEqual(data["reminder"]["do"], "report the pitch")
        self.assertNotIn("next", data)
        recalled = json.loads(self._json_task("session", "recall", "pitch-run", "--dir",
                                              str(self.session_dir)).stdout)
        self.assertNotIn("next", recalled["current_node"])

    def test_state_current_refuses_unusable_machine(self):
        self._init_run_raw("no-machine", SETTLEMENT.split("state_machine: |")[0])
        result = self._current("no-machine", "--prose")
        self.assertEqual(result.returncode, 1)
        self.assertIn("no 'state_machine: |' block", result.stderr)
        self._init_run_raw("scalar-node", SETTLEMENT.replace(
            "    clarify:\n      next: [succeeded]\n"
            "      reminder:\n        do: check the output contract\n",
            "    clarify: oops\n"))
        result = self._current("scalar-node", "--prose")
        self.assertEqual(result.returncode, 1)
        self.assertIn("is not a node in this run's state_machine", result.stderr)

    def test_close_from_a_non_terminal_names_a_runnable_transition(self):
        for outcome in ("succeeded", "failed"):
            with self.subTest(outcome=outcome):
                self.setUp()
                argv = self._refused_close_fix(
                    outcome, f"close {outcome} requires current state '{outcome}', "
                             f"but it is 'clarify'")
                self.assertEqual(argv[1:3], ["state", "transition"])
                self.assertIn(f"--to {outcome}", " ".join(argv))
                closed = self._session(*self._close_args(outcome), "--prose")
                self.assertEqual(closed.returncode, 0, closed.stderr)

    def test_close_after_the_other_terminal_names_a_runnable_close(self):
        for ended, outcome in (("failed", "succeeded"), ("succeeded", "failed")):
            with self.subTest(ended=ended):
                self.setUp()
                self._transition(ended)
                argv = self._refused_close_fix(
                    outcome, f"close {outcome} refused: the run already ended at "
                             f"'{ended}'")
                self.assertEqual(argv[1:3], ["session", "close"])
                self.assertEqual(argv[-2:] if ended == "succeeded" else argv[-4:-2],
                                 ["--outcome", ended])
                self.assertIn("## closed\n", self.ledger.read_text())
                self.assertIn(f" — {ended}", self.ledger.read_text())

    def test_close_without_a_direct_edge_defers_to_transitions_refusal(self):
        settlement = self.tmp / "indirect.txt"
        settlement.write_text(SETTLEMENT.replace("next: [succeeded]", "next: [review]")
                              .replace("    succeeded:\n",
                                       "    review:\n      next: [succeeded]\n    succeeded:\n"))
        self.run_id = "indirect-run"
        init = self._task("session", "init", self.run_id, "--dir", str(self.session_dir),
                          "--settlement-file", str(settlement))
        self.assertEqual(init.returncode, 0, init.stderr)
        self.ledger = self.session_dir / f"{self.run_id}.md"
        refused = self._session("close", "succeeded", "--prose")
        self.assertIn("has no legal edge to 'succeeded'", refused.stderr.splitlines()[-1])
        argv = shlex.split(refused.stderr.splitlines()[-1].split(" — run: ", 1)[1])
        prefix = shlex.split(self.prog)
        self.assertEqual(argv[:len(prefix)], prefix)
        args = (a if not a.startswith("<") else "r" for a in argv[len(prefix):])
        fixed = subprocess.run([*self.task_command, *args], capture_output=True, text=True,
                               check=False, env=_env())
        self.assertEqual(fixed.returncode, 1, fixed.stderr)
        self.assertIn("legal destinations", fixed.stderr)
        self.assertIn("'review'", fixed.stderr)

    def test_close_from_a_gated_node_defers_to_transitions_refusal(self):
        settlement = self.tmp / "gated.txt"
        settlement.write_text(SETTLEMENT.replace(
            "        do: check the output contract\n",
            "        do: check the output contract\n        leave: the contract holds\n"))
        self.run_id = "gated-run"
        init = self._task("session", "init", self.run_id, "--dir", str(self.session_dir),
                          "--settlement-file", str(settlement))
        self.assertEqual(init.returncode, 0, init.stderr)
        self.ledger = self.session_dir / f"{self.run_id}.md"
        refused = self._session("close", "succeeded", "--prose")
        line = refused.stderr.splitlines()[-1]
        self.assertIn("--confirm-leave", line)
        argv = shlex.split(line.split(" — run: ", 1)[1])
        prefix = shlex.split(self.prog)
        self.assertEqual(argv[:len(prefix)], prefix)
        args = (a if not a.startswith("<") else "r" for a in argv[len(prefix):])
        fixed = subprocess.run([*self.task_command, *args], capture_output=True, text=True,
                               check=False, env=_env())
        self.assertEqual(fixed.returncode, 1, fixed.stderr)
        self.assertIn("--confirm-leave", fixed.stderr)

    def test_close_without_a_current_line_is_a_malformed_ledger(self):
        text = self.ledger.read_text()
        self.ledger.write_text(text.replace("current: clarify\n", ""))
        result = self._session("close", "succeeded", "--prose")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("'## state' has no 'current: <node>' line", result.stderr)
        self.assertNotIn(" — run: ", result.stderr)
        self.assertNotIn("## closed", self.ledger.read_text())

    def test_close_after_matching_transition_closes(self):
        self._transition("succeeded")
        result = self._session("close", "succeeded", "--prose")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("## closed", self.ledger.read_text())

    # --- refusals, not tracebacks or result objects -----------------------

    def test_diagram_of_invalid_machine_is_a_refusal(self):
        machine = self.tmp / "bad.yaml"
        machine.write_text("name: bad\nnodes:\n  clarify:\n    next: [nowhere]\n")
        prose = self._task("state", "diagram", str(machine), "--prose")
        self.assertEqual(prose.returncode, 1)
        self.assertEqual(prose.stdout, "")
        self.assertIn("refusing to diagram an invalid machine", prose.stderr)
        self._assert_refusal_lines(prose.stderr, "state diagram", "state diagram <machine.yaml>")
        piped = self._json_task("state", "diagram", str(machine))
        self.assertEqual(piped.returncode, 1)
        self.assertEqual(piped.stdout, "")
        error = json.loads(piped.stderr)["error"]
        self.assertEqual(error["command"], "state diagram")
        self.assertTrue(error["problems"][0]["items"])
