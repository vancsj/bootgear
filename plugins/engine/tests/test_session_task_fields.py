import json
import unittest
from pathlib import Path

from session_task_fields_test_support import (
    TASK_TYPES,
    UNKNOWN_TASK_TYPES,
    SettlementCase,
)


class TaskTypeTest(SettlementCase):
    def test_validator_accepts_the_six_task_types(self):
        extras = {"triage": "triage_cutoff: product\n", "design-doc": "work_dir: ~/notes\n"}
        for task_type in TASK_TYPES:
            with self.subTest(task_type=task_type):
                result = self._validate(task_type, extras.get(task_type, ""))
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_validator_refuses_unknown_labels_and_lists_the_six_values(self):
        for task_type in UNKNOWN_TASK_TYPES:
            with self.subTest(task_type=task_type):
                result = self._validate(task_type)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("  task_type (1):\n"
                              f"    - must be one of: {', '.join(TASK_TYPES)}\n", result.stderr)


class StateMachineScalarTest(SettlementCase):
    def _quoted_machine(self, task_type: str = "ticket-to-pr") -> Path:
        body = self._settlement(task_type).split("state_machine: |\n", 1)[0]
        path = self.tmp / "quoted-machine.yaml"
        path.write_text(body + f"state_machine: {json.dumps(self.machine)}\n")
        return path

    def test_init_refuses_quoted_machine_before_writing_and_allows_correction(self):
        source = self._quoted_machine()
        args = ("session", "init", "quoted-run", "--dir", str(self.session_dir),
                "--settlement-file", str(source), "--prose")
        refused = self._task(*args)
        self.assertEqual(refused.returncode, 1, refused.stderr)
        self.assertIn("  state_machine (1):\n", refused.stderr)
        self.assertIn("must use a literal YAML block", refused.stderr)
        self.assertFalse((self.session_dir / "quoted-run.md").exists())

        source.write_text(self._settlement("ticket-to-pr"))
        accepted = self._task(*args)
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        current = self._task("state", "current", "quoted-run",
                             "--dir", str(self.session_dir), "--prose")
        self.assertEqual(current.returncode, 0, current.stderr)
        self.assertIn("current: clarify", current.stdout)

    def test_validate_groups_quoted_machine_and_other_missing_fields(self):
        source = self._quoted_machine("triage")
        result = self._task("session", "validate", "quoted-run",
                            "--dir", str(self.session_dir),
                            "--settlement-file", str(source), "--prose")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("  state_machine (1):\n", result.stderr)
        self.assertIn("must use a literal YAML block", result.stderr)
        self.assertIn("  triage_cutoff (1):\n", result.stderr)


class TriageCutoffTest(SettlementCase):
    def _one_user_file(self, root: Path) -> Path:
        path = root / ".bootgear" / "config" / "cutoff-one-user.yaml"
        path.parent.mkdir(parents=True)
        path.write_text("cutoff: {}\n")
        return path

    def test_triage_accepts_product(self):
        result = self._validate("triage", "triage_cutoff: product\n")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_triage_refuses_a_missing_cutoff(self):
        result = self._validate("triage")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("  triage_cutoff (1):\n", result.stderr)
        self.assertIn("is required for a triage run", result.stderr)

    def test_triage_refuses_a_cutoff_outside_the_set(self):
        result = self._validate("triage", "triage_cutoff: strict\n")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("must be one of: product, one-user", result.stderr)

    def test_other_types_refuse_a_cutoff_and_every_problem_is_in_one_message(self):
        result = self._validate("ticket-to-pr", "triage_cutoff: strict\ndebate_mode: sometimes\n")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("3 problem(s)", result.stderr)
        self.assertIn("  triage_cutoff (2):\n", result.stderr)
        self.assertIn("only a triage run has one, not 'ticket-to-pr'", result.stderr)
        self.assertIn("must be one of: product, one-user", result.stderr)
        self.assertIn("  debate_mode (1):\n", result.stderr)

    def test_one_user_needs_the_file_under_the_project_root(self):
        result = self._validate("triage", "triage_cutoff: one-user\n")
        self.assertEqual(result.returncode, 1, result.stderr)
        expected = self.project / ".bootgear" / "config" / "cutoff-one-user.yaml"
        self.assertIn(f"'one-user' needs {expected}, which is absent", result.stderr)
        self._one_user_file(self.project)
        result = self._validate("triage", "triage_cutoff: one-user\n")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_one_user_does_not_read_the_session_directory(self):
        self._one_user_file(self.session_dir)
        result = self._validate("triage", "triage_cutoff: one-user\n")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("'one-user' needs", result.stderr)

    def test_one_user_reads_the_gear_caller_cwd(self):
        self._one_user_file(self.project)
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        result = self._validate("triage", "triage_cutoff: one-user\n", cwd=elsewhere,
                                GEAR_CALLER_CWD=str(self.project))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_init_applies_the_one_user_check(self):
        settlement = self.tmp / "init-one-user.txt"
        settlement.write_text(self._settlement("triage", "triage_cutoff: one-user\n"))
        args = ("session", "init", "triage-run", "--dir", str(self.session_dir),
                "--settlement-file", str(settlement), "--prose")
        refused = self._task(*args)
        self.assertEqual(refused.returncode, 1, refused.stderr)
        self.assertIn("'one-user' needs", refused.stderr)
        self.assertFalse((self.session_dir / "triage-run.md").exists())
        self._one_user_file(self.project)
        accepted = self._task(*args)
        self.assertEqual(accepted.returncode, 0, accepted.stderr)


class WorkDirTest(SettlementCase):
    MISSING = ("  work_dir (1):\n"
               "    - is required for a design-doc run: an absolute path or a path that "
               "starts with '~'\n")

    def _init(self, run_id: str, task_type: str, extra: str = ""):
        settlement = self.tmp / f"init-{run_id}.txt"
        settlement.write_text(self._settlement(task_type, extra))
        return self._task("session", "init", run_id, "--dir", str(self.session_dir),
                          "--settlement-file", str(settlement), "--prose")

    def test_design_doc_refuses_a_missing_work_dir(self):
        result = self._validate("design-doc")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("1 problem(s)", result.stderr)
        self.assertIn(self.MISSING, result.stderr)

    def test_work_dir_accepts_an_absolute_or_home_path(self):
        for value in ("~/notes", str(self.tmp / "notes")):
            with self.subTest(value=value):
                result = self._validate("design-doc", f"work_dir: {json.dumps(value)}\n")
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_work_dir_refuses_a_value_that_is_not_an_absolute_path(self):
        for value in ('""', "notes/drafts", "[a, b]"):
            with self.subTest(value=value):
                result = self._validate("design-doc", f"work_dir: {value}\n")
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("  work_dir (1):\n"
                              "    - must be an absolute path or start with '~'", result.stderr)

    def test_init_refuses_a_design_doc_run_with_no_work_dir(self):
        result = self._init("design-run", "design-doc")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("1 problem(s)", result.stderr)
        self.assertIn(self.MISSING, result.stderr)
        self.assertFalse((self.session_dir / "design-run.md").exists())

    def test_init_keeps_a_settled_work_dir(self):
        result = self._init("design-own", "design-doc", "work_dir: ~/notes\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        ledger = (self.session_dir / "design-own.md").read_text()
        self.assertIn("\nwork_dir: ~/notes\n", ledger)
        self.assertEqual(ledger.count("work_dir:"), 1, ledger)

    def test_init_adds_no_work_dir_to_other_types(self):
        result = self._init("pr-run", "ticket-to-pr")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("work_dir:", (self.session_dir / "pr-run.md").read_text())


if __name__ == "__main__":
    unittest.main()
