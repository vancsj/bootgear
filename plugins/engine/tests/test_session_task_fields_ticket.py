import json
import shlex
from pathlib import Path

import yaml
from session_task_fields_test_support import (
    BODY,
    LEAVE_MACHINE,
    TICKET_WRITING,
    LedgerCase,
)


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
            "session write-ticket --dir <session-dir> --body-file <file>"),
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
        argv = shlex.split(command)
        self.assertEqual(argv[:len(self.task_command)], self.task_command)
        args = argv[len(self.task_command):]
        return self._task(*("the body is written" if arg == "<why>" else arg for arg in args))

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
