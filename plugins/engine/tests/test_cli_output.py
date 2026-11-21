import json
import shutil
import unittest

from cli_output_test_support import MACHINE, SETTLEMENT, CliOutputTestCase


class CliOutputTest(CliOutputTestCase):
    # --- mode -------------------------------------------------------------

    def test_pipe_default_is_prose(self):
        result = self._task("session", "read", self.run_id, "--dir",
                            str(self.session_dir), "--section", "state")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith("current: clarify\nstarted: "), result.stdout)

    def test_session_validate_returns_strict_json_summary(self):
        settlement = self.tmp / "strict.txt"
        settlement.write_text(SETTLEMENT)
        init = self._task("session", "init", "strict-run", "--dir",
                          str(self.session_dir), "--settlement-file", str(settlement))
        self.assertEqual(init.returncode, 0, init.stderr)
        result = self._task("session", "validate", "strict-run", "--dir",
                            str(self.session_dir), "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["run_id"], "strict-run")
        self.assertTrue(data["valid"])
        self.assertEqual(data["fields"]["task_type"], "ticket-to-pr")
        self.assertEqual(data["fields"]["state_machine"], "smoke")

    def test_session_validate_settlement_file_accepts_file_without_session_dir(self):
        settlement = self.tmp / "no-dir-file.txt"
        settlement.write_text(SETTLEMENT)
        result = self._task("session", "validate", "no-dir-run", "--dir",
                            str(self.session_dir), "--settlement-file", str(settlement),
                            "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["valid"])

    def test_session_validate_accepts_party_config_id_in_roster(self):
        result = self._validate_party_config(
            "    independent-reviewer:\n      mechanism: native_subagent\n", "party-in-roster")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_session_validate_refuses_party_config_id_missing_from_roster(self):
        result = self._validate_party_config(
            "    independnt-reviewer:\n      mechanism: native_subagent\n", "party-typo")
        self.assertEqual(result.returncode, 1)
        self.assertIn("independnt-reviewer", result.stderr)
        self.assertIn("not in debate_roster", result.stderr)

    def test_session_validate_refuses_quoted_enabled_flag(self):
        result = self._validate_party_config(
            "    independent-reviewer:\n      enabled: 'no'\n", "party-quoted-enabled")
        self.assertEqual(result.returncode, 1)
        self.assertIn("enabled", result.stderr)

    def test_session_validate_groups_strict_refusal_problems(self):
        settlement = self.tmp / "invalid-strict.txt"
        settlement.write_text("task_type: custom\nsession_dir: /wrong\n")
        result = self._task("session", "validate", "invalid-run", "--dir",
                            str(self.session_dir), "--settlement-file", str(settlement),
                            "--prose")
        self.assertEqual(result.returncode, 1)
        self.assertIn("task_type", result.stderr)
        self.assertIn("approach", result.stderr)
        self.assertNotIn("session_dir", result.stderr)

    def test_session_init_refuses_a_settlement_that_validate_refuses(self):
        settlement = self.tmp / "prose-goal.txt"
        settlement.write_text(SETTLEMENT.replace(
            "goal:\n  succeeded: output contract holds\n  failed: never\n",
            "goal: output contract holds\n"))
        result = self._task("session", "init", "refused-run", "--dir",
                            str(self.session_dir), "--settlement-file", str(settlement),
                            "--prose")
        self.assertEqual(result.returncode, 1)
        self.assertIn("goal", result.stderr)
        self.assertFalse((self.session_dir / "refused-run.md").exists())

    def test_session_init_refusal_does_not_say_strict(self):
        settlement = self.tmp / "missing-field.txt"
        settlement.write_text(SETTLEMENT.replace("request_assessment: fixture assessment\n", ""))
        result = self._task("session", "init", "missing-field-run", "--dir",
                            str(self.session_dir), "--settlement-file", str(settlement),
                            "--prose")
        self.assertEqual(result.returncode, 1)
        self.assertIn("request_assessment", result.stderr)
        diagnostic = result.stderr[result.stderr.index("session init refused"):]
        self.assertNotIn("strict", diagnostic)
        self.assertFalse((self.session_dir / "missing-field-run.md").exists())

    def test_session_init_refuses_prose_permitted_mutations(self):
        old = "  permitted_mutations: [run tests]\n"
        self.assertIn(old, SETTLEMENT)
        settlement = self.tmp / "prose-mutations.txt"
        settlement.write_text(SETTLEMENT.replace(old, "  permitted_mutations: run tests\n"))
        result = self._task("session", "init", "prose-mutations-run", "--dir",
                            str(self.session_dir), "--settlement-file", str(settlement),
                            "--prose")
        self.assertEqual(result.returncode, 1)
        self.assertIn("autonomy.permitted_mutations", result.stderr)
        self.assertIn("must be a non-empty list", result.stderr)
        self.assertFalse((self.session_dir / "prose-mutations-run.md").exists())

    def test_session_init_refuses_empty_or_blank_permitted_mutations(self):
        old = "  permitted_mutations: [run tests]\n"
        self.assertIn(old, SETTLEMENT)
        for label, value in (("empty", "[]"), ("blank", '[""]')):
            with self.subTest(list=label):
                run_id = f"{label}-mutations-run"
                settlement = self.tmp / f"{label}-mutations.txt"
                settlement.write_text(SETTLEMENT.replace(old, f"  permitted_mutations: {value}\n"))
                result = self._task("session", "init", run_id, "--dir",
                                    str(self.session_dir), "--settlement-file", str(settlement),
                                    "--prose")
                self.assertEqual(result.returncode, 1)
                self.assertIn("autonomy.permitted_mutations", result.stderr)
                self.assertIn("must be a non-empty list", result.stderr)
                self.assertFalse((self.session_dir / f"{run_id}.md").exists())

    def test_session_init_refuses_questions_left_open(self):
        old = "  no_further_questions: true\n"
        self.assertIn(old, SETTLEMENT)
        settlement = self.tmp / "open-questions.txt"
        settlement.write_text(SETTLEMENT.replace(old, "  no_further_questions: false\n"))
        result = self._task("session", "init", "open-questions-run", "--dir",
                            str(self.session_dir), "--settlement-file", str(settlement),
                            "--prose")
        self.assertEqual(result.returncode, 1)
        self.assertIn("autonomy.no_further_questions", result.stderr)
        self.assertIn("must be true", result.stderr)
        self.assertFalse((self.session_dir / "open-questions-run.md").exists())

    def test_state_json_lists_transitions(self):
        moved = self._task("state", "transition", self.run_id, "--dir",
                           str(self.session_dir), "--to", "succeeded",
                           "--reason", "done", "--prose")
        self.assertEqual(moved.returncode, 0, moved.stderr)
        data = json.loads(self._session("read", "--section", "state").stdout)
        self.assertEqual(data["current"], "succeeded")
        [transition] = data["transitions"]
        self.assertEqual((transition["from"], transition["to"]), ("clarify", "succeeded"))
        self.assertRegex(transition["at"], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
        self.assertTrue(transition["line"].startswith(f"- {transition['at']} clarify"))

    def test_read_json_shapes(self):
        whole = json.loads(self._session("read").stdout)
        self.assertEqual(set(whole), {"run_id", "title", "sections", "closed"})
        self.assertIsNone(whole["closed"])
        self.assertIn("task_type: ticket-to-pr", whole["sections"]["settlement"])
        self.assertEqual(whole["sections"]["todos"], [])
        todo = self._session("update-todo", "write tests")
        self.assertEqual(json.loads(todo.stdout), {"todo": "write tests", "status": "added"})
        self.assertEqual(json.loads(self._session("read", "--open-only").stdout),
                         {"run_id": self.run_id, "open_todos": ["- [ ] write tests"]})
        last = json.loads(self._session("read", "--last", "2").stdout)
        self.assertEqual((last["decisions"], last["decisions_total"]), ([], 0))
        self.assertEqual(json.loads(self._session("read", "--question", "q1").stdout),
                         {"run_id": self.run_id, "question": "q1", "decisions": []})

    def test_stdout_to_regular_file_is_prose(self):
        out = self.tmp / "out.txt"
        with out.open("w") as handle:
            result = self._task("session", "read", self.run_id, "--dir",
                                str(self.session_dir), "--section", "state",
                                stdout=handle)
        self.assertEqual(result.returncode, 0, result.stderr)
        text = out.read_text()
        self.assertTrue(text.startswith("current: clarify\nstarted: "), text)

    def test_prose_flag_on_a_pipe(self):
        result = self._session("read", "--section", "state", "--prose")
        self.assertTrue(result.stdout.startswith("current: clarify\n"), result.stdout)

    # --- refusals ---------------------------------------------------------

    def test_argparse_refusal_is_runnable(self):
        result = self._task("state", "transition", self.run_id, "--dir",
                            str(self.session_dir), "--to", "succeeded", "--prose")
        self.assertEqual(result.returncode, 2)
        self.assertIn("task state transition: error: the following arguments are "
                      "required: --reason", result.stderr)
        self.assertNotIn("usage:", result.stderr)
        self._assert_refusal_lines(
            result.stderr, "state transition", 'state transition --dir <session-dir> --to <node> '
                           '--reason "<why>"')

    def test_domain_refusal_is_runnable(self):
        result = self._session("read", "--last", "0", "--prose")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr.splitlines()[-1], "--last must be a positive integer")
        self._assert_refusal_lines(
            result.stderr, "session read", "session read --dir <session-dir> --section state")

    def test_explicit_json_refusal_is_one_json_error_object(self):
        result = self._session("read", "--last", "0")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        error = json.loads(result.stderr)["error"]
        self.assertEqual(error["command"], "session read")
        self.assertEqual(error["message"], "--last must be a positive integer")
        self.assertEqual(error["example"], f"{self.prog} session read --dir "
                                           f"<session-dir> --section state")
        self.assertIn("session recall", error["commands"])
        self.assertLessEqual(len(error["commands"]), 5)
        self.assertNotIn("session read", error["commands"])
        self.assertEqual(set(error["examples"]), set(self.frequent))

    # --- one refusal per scan ---------------------------------------------

    def test_malformed_ledger_reports_every_problem_once(self):
        text = self.ledger.read_text()
        text = text.replace("## todos\n\n",
                            "## todos\n- [y] bad box\n- []\n\n")
        text = text.replace("## decisions\n\n",
                            "## decisions\n- 2026-09-24 10:00 [debate] [q2] round 0, "
                            "party 'a': x\n\n")
        self.ledger.write_text(text)
        result = self._session("read", "--section", "state", "--prose")
        self.assertEqual(result.returncode, 1)
        message = f"malformed ledger at {self.ledger.resolve()}: 3 problem(s)"
        lines = result.stderr.splitlines()
        self.assertIn(message, lines, result.stderr)
        self.assertTrue(all(line.startswith("  ") for line in lines[lines.index(message) + 1:]),
                        result.stderr)
        self.assertLess(result.stderr.index("example: "), result.stderr.index(message))
        self.assertIn("  question id out of sequence (1):\n", result.stderr)
        self.assertIn("'q2' is the first entry tagging this question, but 'q1'",
                      result.stderr)
        self.assertIn("  bad todo checkbox (2):\n", result.stderr)
        self.assertIn("- '- [y] bad box': ", result.stderr)
        self.assertIn("- '- []': ", result.stderr)

    def test_structure_problems_are_reported_together(self):
        text = self.ledger.read_text().replace("## pitches\n", "").replace(
            "## todos\n", "## todos\n\n## todos\n")
        self.ledger.write_text(text)
        result = self._session("read", "--prose")
        self.assertEqual(result.returncode, 1)
        self.assertIn("2 problem(s)", result.stderr)
        self.assertIn("  missing section (1):\n    - '## pitches'", result.stderr)
        self.assertIn("  duplicated section (1):\n    - '## todos' ×2", result.stderr)

    def test_record_decision_reports_every_problem_once(self):
        result = self._session("record-decision", "--mode", "solo", "--question", "q9",
                               "--summary", "AMENDMENT session_dir: a -> b", "--prose")
        self.assertEqual(result.returncode, 1)
        self.assertIn("record-decision (2):", result.stderr)
        self.assertIn("--question is only for debate modes", result.stderr)
        self.assertIn("'session_dir' cannot be recorded as an AMENDMENT", result.stderr)

    # --- caller-relative paths --------------------------------------------

    def test_relative_dir_and_path_resolve_against_caller_cwd(self):
        caller = self.tmp / "caller"
        caller.mkdir()
        (caller / "machine.yaml").write_text(MACHINE)
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        shutil.copytree(self.session_dir, caller / "rel-session")
        read = self._json_task("session", "read", self.run_id, "--dir", "rel-session",
                               "--section", "state", cwd=elsewhere,
                               GEAR_CALLER_CWD=str(caller))
        self.assertEqual(read.returncode, 0, read.stderr)
        self.assertEqual(json.loads(read.stdout)["current"], "clarify")
        validated = self._json_task("state", "validate", "machine.yaml", cwd=elsewhere,
                                    GEAR_CALLER_CWD=str(caller))
        self.assertEqual(validated.returncode, 0, validated.stderr)
        self.assertEqual(json.loads(validated.stdout),
                         {"path": str((caller / "machine.yaml").resolve()), "ok": True, "problems": []})

    # --- next steps -------------------------------------------------------

    def test_next_question_id_names_round_0(self):
        result = self._session("next-question-id")
        data = json.loads(result.stdout)
        self.assertEqual(data["question"], "q1")
        self.assertEqual(
            data["next"],
            f"{self.prog} session record-decision {self.run_id} --dir "
            f"{self.session_dir.resolve()} --mode debate --question q1 --summary "
            f"\"round 0, party '<role>': <topic, scope, principles, cutoff>\"")
        prose = self._session("next-question-id", "--prose")
        self.assertEqual(prose.stdout.splitlines()[0], "q1")
        self.assertEqual(prose.stdout.splitlines()[1], f"next: {data['next']}")

    def test_scope_settled_names_round_1(self):
        self._session("record-decision", "--mode", "debate", "--question", "q1",
                      "--summary", "round 0, party 'a': scope")
        result = self._session("record-decision", "--mode", "scope-settled",
                               "--question", "q1", "--summary", "scope_settled: done")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertTrue(data["line"].endswith("[scope-settled] [q1] scope_settled: done"))
        self.assertEqual(
            data["next"],
            f"{self.prog} session record-decision {self.run_id} --dir "
            f"{self.session_dir.resolve()} --mode debate --question q1 --summary "
            f"\"round 1, party '<role>': <position>\"")

    def test_solo_decision_has_no_next(self):
        result = self._session("record-decision", "--mode", "solo", "--summary", "pick A")
        self.assertNotIn("next", json.loads(result.stdout))
        prose = self._session("record-decision", "--mode", "solo", "--summary", "pick B",
                              "--prose")
        self.assertEqual(prose.stdout, "DECISION recorded\n")


if __name__ == "__main__":
    unittest.main()
