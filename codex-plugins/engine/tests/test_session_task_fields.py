"""Settlement task fields and the ticket write verb, through the real `task`
wrapper: the five task types, `triage_cutoff`, `work_dir`, `ticket_path`,
`owned_artifacts`, and `session write-ticket`.

Each subprocess runs from a temporary project root with `GEAR_CALLER_CWD`
removed, so the caller's working directory is that project root.
"""
import json
import os
import shlex
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml
from settlement_fixture import valid_settlement

PLUGIN_DIR = Path(__file__).resolve().parents[1]
TASK_BIN = PLUGIN_DIR / "scripts" / "task"
TASK_TYPES = ("change-review", "design-doc", "ticket-to-pr", "ticket-writing", "triage")
UNKNOWN_TASK_TYPES = ("retired-review", "retired-triage", "pr-review", "bug-triage")

MACHINE = """\
name: fixture
nodes:
  clarify:
    next: [ticket]
  ticket:
    next: [ticket-review]
  ticket-review:
    next: [succeeded]
  succeeded:
    terminal: true
  failed:
    terminal: true
"""
LEAVE_MACHINE = MACHINE.replace(
    "  ticket:\n    next: [ticket-review]\n",
    "  ticket:\n    reminder:\n      leave: the body is written\n    next: [ticket-review]\n")
TICKET_WRITING = PLUGIN_DIR / "state-machines" / "ticket-writing.yaml"


def _env(**extra):
    env = {k: v for k, v in os.environ.items()
           if k not in ("BOOTGEAR_OUTPUT", "BOOTGEAR_PROG", "GEAR_CALLER_CWD",
                        "VIRTUAL_ENV")}
    env.update(extra)
    return env


class SettlementCase(unittest.TestCase):
    task_bin = TASK_BIN
    machine = MACHINE

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="engine-task-fields-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.project = self.tmp / "project"
        self.project.mkdir()
        self.session_dir = self.tmp / "session"

    def _task(self, *args, cwd=None, **env):
        return subprocess.run([str(self.task_bin), *args], capture_output=True, text=True,
                              check=False, cwd=cwd or self.project, env=_env(**env))

    def _settlement(self, task_type: str, extra: str = "") -> str:
        text = valid_settlement(self.machine, extra=extra)
        return text.replace("task_type: ticket-to-pr\n", f"task_type: {task_type}\n", 1)

    def _settlement_file(self, task_type: str, extra: str = "") -> Path:
        """A settlement for `validate --settlement-file`, which needs the
        `session_dir:` line that `init` adds."""
        path = self.tmp / f"settlement-{task_type}.txt"
        path.write_text(self._settlement(task_type, extra) + f"session_dir: {self.session_dir}\n")
        return path

    def _validate(self, task_type: str, extra: str = "", **kwargs):
        return self._task("session", "validate", "run-1", "--dir", str(self.session_dir),
                          "--settlement-file", str(self._settlement_file(task_type, extra)),
                          "--prose", **kwargs)


class TaskTypeTest(SettlementCase):
    def test_validator_accepts_the_five_task_types(self):
        extras = {"triage": "triage_cutoff: product\n", "design-doc": "work_dir: ~/notes\n"}
        for task_type in TASK_TYPES:
            with self.subTest(task_type=task_type):
                result = self._validate(task_type, extras.get(task_type, ""))
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_validator_refuses_unknown_labels_and_lists_the_five_values(self):
        for task_type in UNKNOWN_TASK_TYPES:
            with self.subTest(task_type=task_type):
                result = self._validate(task_type)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("  task_type (1):\n"
                              f"    - must be one of: {', '.join(TASK_TYPES)}\n", result.stderr)


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
        result = self._validate("ticket-to-pr", "triage_cutoff: strict\nspec_debate_mode: sometimes\n")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("3 problem(s)", result.stderr)
        self.assertIn("  triage_cutoff (2):\n", result.stderr)
        self.assertIn("only a triage run has one, not 'ticket-to-pr'", result.stderr)
        self.assertIn("must be one of: product, one-user", result.stderr)
        self.assertIn("  spec_debate_mode (1):\n", result.stderr)

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


class LedgerCase(SettlementCase):
    def _init(self, run_id: str, task_type: str, extra: str = "", *flags: str):
        settlement = self.tmp / f"init-{run_id}.txt"
        settlement.write_text(self._settlement(task_type, extra))
        return self._task("session", "init", run_id, "--dir", str(self.session_dir),
                          "--settlement-file", str(settlement), "--prose", *flags)

    def _ledger(self, run_id: str, task_type: str, stored: str = "") -> Path:
        """An initialized ledger whose stored settlement also holds `stored`."""
        result = self._init(run_id, task_type)
        self.assertEqual(result.returncode, 0, result.stderr)
        path = self.session_dir / f"{run_id}.md"
        if stored:
            text = path.read_text()
            path.write_text(text.replace("\n\n## decisions\n",
                                         f"\n{stored.rstrip()}\n\n## decisions\n", 1))
        return path

    def _validate_ledger(self, run_id: str):
        return self._task("session", "validate", run_id, "--dir", str(self.session_dir),
                          "--prose")

    def _ticket(self, run_id: str) -> Path:
        return self.session_dir / f"{run_id}.artifacts" / "issue.md"


class TicketPathTest(LedgerCase):
    def test_ticket_writing_accepts_no_ticket_path(self):
        self._ledger("tw-run", "ticket-writing")
        result = self._validate_ledger("tw-run")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_ticket_writing_accepts_the_canonical_ticket_path(self):
        self._ledger("tw-run", "ticket-writing",
                     f"ticket_path: {json.dumps(str(self._ticket('tw-run')))}")
        result = self._validate_ledger("tw-run")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_stored_ticket_path_refusals(self):
        canonical = self._ticket("tw-run")
        cases = {
            '""': "must not be empty",
            '"-issue.md"': "must not start with '-'",
            json.dumps(f"{canonical}\nmore"): "must not contain a line break",
            "drafts/issue.md": "must be an absolute path",
            json.dumps(str(self.tmp / "elsewhere" / "issue.md")): f"must equal {canonical}",
        }
        for value, message in cases.items():
            with self.subTest(value=value):
                (self.session_dir / "tw-run.md").unlink(missing_ok=True)
                self._ledger("tw-run", "ticket-writing", f"ticket_path: {value}")
                result = self._validate_ledger("tw-run")
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("  ticket_path (", result.stderr)
                self.assertIn(f"    - {message}\n", result.stderr)

    def test_other_types_refuse_a_ticket_path_with_every_problem_in_one_message(self):
        self._ledger("pr-run", "ticket-to-pr", "ticket_path: drafts/issue.md")
        result = self._validate_ledger("pr-run")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("  ticket_path (3):\n", result.stderr)
        self.assertIn("only a ticket-writing run has one, not 'ticket-to-pr'", result.stderr)
        self.assertIn("must be an absolute path", result.stderr)
        self.assertIn(f"must equal {self._ticket('pr-run')}", result.stderr)

    def test_init_and_validate_refuse_a_ticket_path_in_the_settlement(self):
        stored = f"ticket_path: {json.dumps(str(self._ticket('tw-run')))}\n"
        result = self._init("tw-run", "ticket-writing", stored)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("is written only by `session write-ticket`", result.stderr)
        self.assertFalse((self.session_dir / "tw-run.md").exists())
        result = self._validate("ticket-writing", stored)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("is written only by `session write-ticket`", result.stderr)


BODY = """\
## Problem
The export drops rows.

## Outcome
Every row exports.

## Acceptance criteria
- An export of 3 rows has 3 rows.

## Scope
The export command only.

## Verification notes
Run the export on the fixture.
"""


class WriteTicketTest(LedgerCase):
    def _ticket_run(self, run_id: str = "tw-run") -> Path:
        ledger = self._ledger(run_id, "ticket-writing")
        moved = self._task("state", "transition", run_id, "--dir", str(self.session_dir),
                           "--to", "ticket", "--reason", "draft the body", "--prose")
        self.assertEqual(moved.returncode, 0, moved.stderr)
        return ledger

    def _write(self, run_id: str, body: str, *flags: str):
        body_file = self.tmp / f"body-{run_id}.md"
        body_file.write_text(body)
        return self._task("session", "write-ticket", run_id, "--dir", str(self.session_dir),
                          "--body-file", str(body_file), "--prose", *flags)

    def _stored(self, run_id: str) -> dict:
        text = (self.session_dir / f"{run_id}.md").read_text()
        return yaml.safe_load(text.split("## settlement\n", 1)[1].split("\n## decisions\n", 1)[0])

    def _last_line(self, stream: str) -> str:
        return stream.strip().splitlines()[-1].strip()

    def test_write_creates_the_body_and_records_ownership(self):
        self._ticket_run()
        result = self._write("tw-run", BODY)
        self.assertEqual(result.returncode, 0, result.stderr)
        ticket = self._ticket("tw-run")
        self.assertEqual(ticket.read_text(), BODY)
        stored = self._stored("tw-run")
        self.assertEqual(stored["ticket_path"], str(ticket))
        self.assertEqual(stored["owned_artifacts"], [str(ticket)])
        lines = result.stdout.strip().splitlines()
        self.assertEqual(lines[0], f"TICKET   created {ticket}")
        self.assertTrue(lines[-1].startswith("next: "), result.stdout)
        self.assertTrue(lines[-1].endswith(
            f"state transition tw-run --dir {self.session_dir} --to ticket-review "
            '--reason "<why>"'), result.stdout)
        validated = self._validate_ledger("tw-run")
        self.assertEqual(validated.returncode, 0, validated.stderr)

    def test_redraft_of_an_owned_body_is_allowed(self):
        self._ticket_run()
        self.assertEqual(self._write("tw-run", BODY).returncode, 0)
        redraft = BODY.replace("drops rows", "drops the last row")
        result = self._write("tw-run", redraft)
        self.assertEqual(result.returncode, 0, result.stderr)
        ticket = self._ticket("tw-run")
        self.assertEqual(ticket.read_text(), redraft)
        self.assertEqual(self._stored("tw-run")["owned_artifacts"], [str(ticket)])
        self.assertEqual(result.stdout.splitlines()[0], f"TICKET   rewritten {ticket}")

    def test_unowned_body_is_refused_and_left_unchanged(self):
        ledger = self._ticket_run()
        ticket = self._ticket("tw-run")
        ticket.parent.mkdir()
        ticket.write_text("written by a host tool\n")
        before = ledger.read_text()
        result = self._write("tw-run", BODY)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("this run does not own it", self._last_line(result.stderr))
        self.assertEqual(ticket.read_text(), "written by a host tool\n")
        self.assertEqual(ledger.read_text(), before)

    def test_body_missing_a_heading_is_refused_and_not_written(self):
        ledger = self._ticket_run()
        before = ledger.read_text()
        body = BODY.replace("## Scope\n", "## Scope of work\n").replace(
            "## Verification notes\n", "Verification notes\n")
        result = self._write("tw-run", body)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("  missing heading (2):\n"
                      "    - no 'Scope' heading\n"
                      "    - no 'Verification notes' heading", result.stderr)
        self.assertEqual(self._last_line(result.stderr), "- no 'Verification notes' heading")
        self.assertFalse(self._ticket("tw-run").exists())
        self.assertEqual(ledger.read_text(), before)

    def test_headings_match_any_level_ignoring_case(self):
        self._ticket_run()
        body = (BODY.replace("## Problem", "# problem").replace("## Outcome", "### OUTCOME")
                .replace("## Acceptance criteria", "###### Acceptance Criteria"))
        result = self._write("tw-run", body)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_other_task_types_are_refused(self):
        self._ledger("pr-run", "ticket-to-pr")
        result = self._write("pr-run", BODY)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("only a ticket-writing run has one, not 'ticket-to-pr'",
                      self._last_line(result.stderr))
        self.assertFalse(self._ticket("pr-run").parent.exists())

    def test_init_force_refuses_a_ledger_after_a_write(self):
        ledger = self._ticket_run()
        self.assertEqual(self._write("tw-run", BODY).returncode, 0)
        before = ledger.read_text()
        result = self._init("tw-run", "ticket-writing", "", "--force")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("lists owned artifacts", self._last_line(result.stderr))
        self.assertEqual(ledger.read_text(), before)

    def test_unreadable_body_file_is_refused(self):
        self._ticket_run()
        missing = self.tmp / "no-such-body.md"
        result = self._task("session", "write-ticket", "tw-run", "--dir", str(self.session_dir),
                            "--body-file", str(missing), "--prose")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn(f"cannot read --body-file {missing}", self._last_line(result.stderr))
        self.assertFalse(self._ticket("tw-run").exists())

    def test_missing_body_file_option_prints_the_example(self):
        self._ticket_run()
        result = self._task("session", "write-ticket", "tw-run", "--dir", str(self.session_dir),
                            "--prose")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertTrue(result.stderr.splitlines()[0].endswith(
            "session write-ticket <run-id> --dir <session-dir> --body-file <file>"),
            result.stderr)
        self.assertIn("--body-file", self._last_line(result.stderr))


class WriteTicketNextStepTest(LedgerCase):
    """The `next:` line that `session write-ticket` prints runs as printed once
    the node's leave condition holds."""

    def _next_after_write(self, *nodes: str) -> str:
        self._ledger("tw-run", "ticket-writing")
        for node in nodes:
            moved = self._task("state", "transition", "tw-run", "--dir", str(self.session_dir),
                               "--to", node, "--reason", f"enter {node}", "--confirm-leave",
                               "--prose")
            self.assertEqual(moved.returncode, 0, moved.stderr)
        body_file = self.tmp / "body.md"
        body_file.write_text(BODY + "\n## Open interpretations\nNone.\n")
        written = self._task("session", "write-ticket", "tw-run", "--dir", str(self.session_dir),
                             "--body-file", str(body_file), "--prose")
        self.assertEqual(written.returncode, 0, written.stderr)
        last = written.stdout.strip().splitlines()[-1]
        self.assertTrue(last.startswith("next: "), written.stdout)
        return last.removeprefix("next: ")

    def _run_printed(self, command: str):
        argv = shlex.split(command)[1:]
        return self._task(*("the body is written" if arg == "<why>" else arg for arg in argv))

    def test_next_step_runs_on_the_ticket_writing_machine(self):
        self.machine = TICKET_WRITING.read_text()
        command = self._next_after_write("inspect", "ticket")
        followed = self._run_printed(command)
        self.assertEqual(followed.returncode, 0, f"{command}\n{followed.stderr}")

    def test_next_step_confirms_the_leave_condition(self):
        self.machine = LEAVE_MACHINE
        command = self._next_after_write("ticket")
        self.assertTrue(command.endswith(
            '--to ticket-review --reason "<why>" --confirm-leave'), command)
        followed = self._run_printed(command)
        self.assertEqual(followed.returncode, 0, followed.stderr)
        self.assertIn("STATE    ticket -> ticket-review", followed.stdout)


class OwnedArtifactsTest(LedgerCase):
    def test_stored_owned_artifacts_must_be_a_list_of_absolute_paths(self):
        for value in ("drafts/issue.md", "[drafts/issue.md]"):
            with self.subTest(value=value):
                (self.session_dir / "tw-run.md").unlink(missing_ok=True)
                self._ledger("tw-run", "ticket-writing", f"owned_artifacts: {value}")
                result = self._validate_ledger("tw-run")
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("  owned_artifacts (1):\n"
                              "    - must be a list of absolute paths", result.stderr)

    def test_stored_owned_artifacts_accepts_an_empty_or_absolute_list(self):
        for value in ("[]", json.dumps([str(self._ticket("tw-run"))])):
            with self.subTest(value=value):
                (self.session_dir / "tw-run.md").unlink(missing_ok=True)
                self._ledger("tw-run", "ticket-writing", f"owned_artifacts: {value}")
                result = self._validate_ledger("tw-run")
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_init_force_refuses_a_ledger_that_owns_artifacts(self):
        owned = str(self._ticket("tw-run"))
        ledger = self._ledger("tw-run", "ticket-writing", f"owned_artifacts: {json.dumps([owned])}")
        before = ledger.read_text()
        result = self._init("tw-run", "ticket-writing", "", "--force")
        self.assertEqual(result.returncode, 1, result.stderr)
        last = result.stderr.strip().splitlines()[-1]
        self.assertIn(f"lists owned artifacts ({owned})", last)
        self.assertIn("refused", last)
        self.assertEqual(ledger.read_text(), before)

    def test_init_force_overwrites_a_ledger_that_owns_nothing(self):
        for stored in ("", "owned_artifacts: []"):
            with self.subTest(stored=stored):
                (self.session_dir / "tw-run.md").unlink(missing_ok=True)
                self._ledger("tw-run", "ticket-writing", stored)
                result = self._init("tw-run", "ticket-writing", "", "--force")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn("owned_artifacts", (self.session_dir / "tw-run.md").read_text())

    def test_init_and_validate_refuse_owned_artifacts_in_the_settlement(self):
        stored = f"owned_artifacts: {json.dumps([str(self._ticket('tw-run'))])}\n"
        result = self._init("tw-run", "ticket-writing", stored)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("  owned_artifacts (1):\n"
                      "    - is written only by `session write-ticket`", result.stderr)
        self.assertFalse((self.session_dir / "tw-run.md").exists())
        result = self._validate("ticket-writing", stored)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("is written only by `session write-ticket`", result.stderr)


if __name__ == "__main__":
    unittest.main()
