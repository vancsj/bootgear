"""Settlement task fields and the ticket write verb, through the real `task`
wrapper: the six task types, `triage_cutoff`, `work_dir`, `ticket_path`,
`owned_artifacts`, and `session write-ticket`.

Each subprocess runs from a temporary project root with `GEAR_CALLER_CWD`
removed, so the caller's working directory is that project root.
"""
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from gear_commands import TASK as TASK_COMMAND
from settlement_fixture import valid_settlement

PLUGIN_DIR = Path(__file__).resolve().parents[1]
TASK_TYPES = ("artefact-review", "change-review", "design-doc", "ticket-to-pr", "ticket-writing", "triage")
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
    task_command = TASK_COMMAND
    machine = MACHINE

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="engine-task-fields-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.project = self.tmp / "project"
        self.project.mkdir()
        self.session_dir = self.tmp / "session"

    def _task(self, *args, cwd=None, **env):
        return subprocess.run([*self.task_command, *args], capture_output=True, text=True,
                              check=False, cwd=cwd or self.project, env=_env(**env))

    def _settlement(self, task_type: str, extra: str = "") -> str:
        task_folder = self.tmp / "artefact-task"
        if task_type == "artefact-review":
            input_path = self.tmp / "artefact-review-input.md"
            input_path.write_text("A supplied review input.\n")
            task_folder.mkdir(exist_ok=True)
            extra = ("artefact_review:\n"
                     "  request: Review this supplied input.\n"
                     f"  inputs: [{json.dumps(str(input_path))}]\n" + extra)
        text = valid_settlement(self.machine, extra=extra)
        if task_type == "artefact-review":
            default_folder = json.dumps(str(Path(tempfile.gettempdir()).resolve()))
            task_folder_value = json.dumps(str(task_folder))
            text = text.replace(f"task_folder: {default_folder}\n",
                                f"task_folder: {task_folder_value}\n", 1)
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
