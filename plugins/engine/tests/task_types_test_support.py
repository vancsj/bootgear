"""C30a checks for the six engine task types, on each host.

Host paths use registered Gear commands for task and Converge, and
the bootgear overrides in `.bootgear/config/`. Shared configuration is read from the repo root. Subprocesses run in scratch dirs, never in the repo.
"""
import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml
from bootgear_cli import runtime
from gear_commands import CONVERGE as CONVERGE_COMMAND
from gear_commands import HOST
from gear_commands import TASK as TASK_COMMAND
from settlement_fixture import valid_settlement

PLUGIN_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
HOST_ROOT_VAR = "CLAUDE_PLUGIN_ROOT" if HOST == "claude" else "PLUGIN_ROOT"
ENGINE_SRC = PLUGIN_DIR / "src"
MACHINES = PLUGIN_DIR / "state-machines"
REFERENCES = PLUGIN_DIR / "references"
OVERRIDES = REPO_ROOT / ".bootgear" / "config"
TASK_TYPES = ("ticket-writing", "ticket-to-pr", "triage", "change-review", "design-doc", "artefact-review")
# Static project override node sets.
OVERRIDE_NODES = {
    "change-review": {"clarify", "disposition", "failed", "fix", "inspect", "review",
                      "review-debate", "spec", "spec-review", "spec-debate", "succeeded"},
    "triage": {"clarify", "disposition", "failed", "inspect", "succeeded", "triage", "triage-debate",
               "triage-review"},
    "ticket-writing": {"clarify", "failed", "inspect", "succeeded", "ticket", "ticket-debate",
                       "ticket-review"},
}
# D3 profiles, with each reach and impact set sorted.
PRODUCT_RULE = {"reach": ["crafted", "normal"],
                "impact": ["clarity", "data-loss", "security", "wrong-output"]}
UNREACHABLE_RULE = {"reach": ["unreachable"], "impact": ["data-loss", "security", "wrong-output"]}
# Every cause claim is attacked, so each surviving claim can carry a reproduction-rerun attack.
EVERY_CLAIM_RULE = {"reach": ["crafted", "normal", "unreachable"]}
TRIAGE_PROFILES = {"product": REFERENCES / "cutoff-product.yaml",
                   "one-user": OVERRIDES / "cutoff-one-user.yaml"}
TRIAGE_MACHINES = {"built-in": MACHINES / "triage.yaml",
                   "override": OVERRIDES / "state-machine-triage.yaml"}
# The triage nodes after clarify, in walk order.
TRIAGE_WALK = ("inspect", "triage", "triage-review")
GATE_CHECK = ["converge", "gate", "{slate}", "--dir", "{converge_dir}", "--kind", "triage",
              "--base-slate", "{base_slate}", "--report", "{report}"]
# A task layer that leaves `reproduction-rerun` as the only attack angle and skips cuts.
RERUN_ONLY = """\
steps: {cut: none, gap_hunt: false, escalate: false}
angles:
  disable: [cited-but-unread, point-in-time, provenance, reachability, absent-vs-default,
            downstream-consumer, inverse-reading, carve-out, boundary, dependents,
            positive-control, inherited-bounds, guarded-elsewhere, deliberate, real-referent]
"""
CUT_EVIDENCE = ("--evidence", "entry-points=no caller reaches it",
                "--evidence", "blast-radius=one row per call",
                "--evidence", "affected-count=one record",
                "--evidence", "files-touched=a.py")
# The docs/engine.md overview writes the types in prose.
PROSE_NAMES = {
    "ticket writing": "ticket-writing",
    "ticket-to-pr": "ticket-to-pr",
    "triage": "triage",
    "change review": "change-review",
    "design docs": "design-doc",
    "artefact review": "artefact-review",
}
# A reminder that names `spec` as the skill to draft with. A "does not: call `spec`" clause
# does not match.
DRAFT_WITH_SPEC = re.compile(r"\b(?:with|using|via|by)\s+(?:the\s+)?`?(?:/|\$)?spec`?(?![\w-])")
SCRUBBED = ("BOOTGEAR_OUTPUT", "BOOTGEAR_PROG", "GEAR_CALLER_CWD", "VIRTUAL_ENV",
            "BOOTGEAR_HOST", "CLAUDE_PLUGIN_ROOT", "PLUGIN_ROOT")
SETTLEMENT_MACHINE = """\
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


def _uv_dirs() -> dict[str, str]:
    """The real uv cache and Python dirs, so a scratch HOME does not force a download."""
    env: dict[str, str] = {}
    for var, cmd in (("UV_CACHE_DIR", ["uv", "cache", "dir"]),
                     ("UV_PYTHON_INSTALL_DIR", ["uv", "python", "dir"])):
        if var in os.environ:
            env[var] = os.environ[var]
            continue
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, check=False)
        except OSError:
            continue
        if out.returncode == 0 and out.stdout.strip():
            env[var] = out.stdout.strip()
    return env


UV_DIRS = _uv_dirs()


def _env(home: Path | None = None, data: Path | None = None) -> dict[str, str]:
    """This host's wrapper environment: prose output, this host's root, no caller or other host."""
    env = {key: value for key, value in os.environ.items() if key not in SCRUBBED}
    env["BOOTGEAR_OUTPUT"] = "prose"
    env[HOST_ROOT_VAR] = str(PLUGIN_DIR)
    if home is not None:
        env.update(UV_DIRS)
        env["HOME"] = str(home)
    if data is not None:
        env["XDG_DATA_HOME"] = str(data)
    return env


def _load_yaml(path: Path):
    return yaml.safe_load(path.read_text())


def _session_module():
    if str(ENGINE_SRC) not in sys.path:
        sys.path.insert(0, str(ENGINE_SRC))
    return importlib.import_module("engine.session")


def _rule(rule: dict) -> dict:
    """A cutoff rule's sorted reach and impact sets. `status` is a report filter, not a D3 criterion."""
    return {key: sorted(value) for key, value in rule.items() if key != "status"}


class Scratch(unittest.TestCase):
    """Each test gets its own project, session dir, converge ledgers and HOME."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="engine-task-types-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.project = self.tmp / "project"
        self.project.mkdir()
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.data = self.tmp / "data"
        runtimes = self.data / "bootgear" / "runtimes"
        runtimes.parent.mkdir(parents=True)
        (runtimes.parent / "python").write_text(f"{sys.executable}\n")
        runtimes.symlink_to(runtime.environment_path().parent, target_is_directory=True)
        self.session_dir = self.tmp / "session"
        self.ledgers = self.tmp / "ledgers"
        self.ledgers.mkdir()
        self.report = self.tmp / "report.md"

    def _task(self, *args):
        return subprocess.run([*TASK_COMMAND, *args], capture_output=True, text=True,
                              check=False, cwd=self.project, env=_env(self.home, self.data))

    def _converge(self, *args):
        return subprocess.run([*CONVERGE_COMMAND, *args], capture_output=True, text=True,
                              check=False, cwd=self.project, env=_env(self.home, self.data))

    # -- settlements and ledgers -------------------------------------------------------

    def _settlement(self, task_type, extra=""):
        text = valid_settlement(SETTLEMENT_MACHINE, extra=extra)
        return text.replace("task_type: ticket-to-pr\n", f"task_type: {task_type}\n", 1)

    def _validate(self, task_type, extra=""):
        path = self.tmp / f"settlement-{task_type}.txt"
        path.write_text(self._settlement(task_type, extra) + f"session_dir: {self.session_dir}\n")
        return self._task("session", "validate", "run-1", "--dir", str(self.session_dir),
                          "--settlement-file", str(path), "--prose")

    def _init(self, run_id, task_type, extra="", *flags):
        path = self.tmp / f"init-{run_id}.txt"
        path.write_text(self._settlement(task_type, extra))
        return self._task("session", "init", run_id, "--dir", str(self.session_dir),
                          "--settlement-file", str(path), "--prose", *flags)

    def _ledger(self, run_id, task_type, stored=""):
        """An initialized ledger; `stored` lines are added to its stored settlement."""
        result = self._init(run_id, task_type)
        self.assertEqual(result.returncode, 0, result.stderr)
        path = self.session_dir / f"{run_id}.md"
        if stored:
            text = path.read_text()
            path.write_text(text.replace("\n\n## decisions\n",
                                         f"\n{stored.rstrip()}\n\n## decisions\n", 1))
        return path

    def _ticket(self, run_id):
        return self.session_dir / f"{run_id}.artifacts" / "issue.md"

    def _ticket_run(self, run_id="tw-run"):
        ledger = self._ledger(run_id, "ticket-writing")
        moved = self._task("state", "transition", run_id, "--dir", str(self.session_dir),
                           "--to", "ticket", "--reason", "draft the body", "--prose")
        self.assertEqual(moved.returncode, 0, moved.stderr)
        return ledger

    def _write(self, run_id, body):
        body_file = self.tmp / f"body-{run_id}.md"
        body_file.write_text(body)
        return self._task("session", "write-ticket", run_id, "--dir", str(self.session_dir),
                          "--body-file", str(body_file), "--prose")

    # -- converge slates ---------------------------------------------------------------

    def _slate(self, slate, defaults=REFERENCES / "cutoff-product.yaml", *extra):
        return self._converge("init", slate, "--dir", str(self.ledgers), "--as", "orch",
                              "--project-root", str(self.project), "--lenses", "default",
                              "--defaults", str(defaults),
                              "--angles", str(REFERENCES / "angles-triage.yaml"), *extra)

    def _file(self, slate, claim):
        return self._converge("file", slate, "--dir", str(self.ledgers), "--as", "finder",
                              "--loc", "src/a.py:10", "--claim", claim,
                              "--trigger", "caller passes None", "--origin", "lens",
                              "--evidence", "a.py:10 reads x.y with x None",
                              "--tier", "reproduced", "--lens", "default",
                              "--angle", "report-claim")

    def _filed_and_covered(self, slate, defaults=REFERENCES / "cutoff-product.yaml", *extra):
        """A slate with claim F001 and complete find coverage; the find-run output."""
        self.assertEqual(self._slate(slate, defaults, *extra).returncode, 0)
        filed = self._file(slate, "x is None at a.py:10")
        self.assertEqual(filed.returncode, 0, filed.stderr)
        covered = self._converge("find-run", slate, "--dir", str(self.ledgers), "--as", "finder",
                                 "--lens", "default", "--angle", "report-claim",
                                 "--tell", "the report has one row",
                                 "--searches", "the ## Claims table",
                                 "--positive-control", "row F001 is found", "--result", "F001")
        self.assertEqual(covered.returncode, 0, covered.stderr)
        return covered

    def _attack(self, slate, agent, batch, angle, *extra):
        action = {
            "slate": slate,
            "source_seq": len((self.ledgers / f"{slate}.jsonl").read_text().splitlines()),
            "role": agent, "action": "clean", "claim": "F001",
            "batch": batch if batch == "fresh-eye" else int(batch),
            "checks": [{"angle": angle, "tell": "tell applies",
                        "evidence": "re-ran it: 1 failed", "searches": "uv run pytest -q",
                        "positive_control": "the output names x"}],
        }
        if "--last" in extra:
            action["last"] = True
        path = self.tmp / "clean-action.json"
        path.write_text(json.dumps(action))
        return self._converge("clean", slate, "--dir", str(self.ledgers), "--as", agent,
                              "--input", str(path))

    def _report(self, rows=(), headings=("Cause", "Impact", "Confidence", "Next action",
                                             "Solutions")):
        lines = ["# Triage report", "", "## Claims", "",
                 "| id | claim | tier | command | output |", "|---|---|---|---|---|", *rows]
        for heading in headings:
            body = "- no-fact: fixture reason." if heading == "Solutions" else f"{heading} text."
            lines += ["", f"## {heading}", "", body]
        self.report.write_text("\n".join(lines) + "\n")

    # -- triage runs -------------------------------------------------------------------

    def _move(self, run_id, dest, *extra):
        """`task state transition`, with this host's converge first on PATH for leave checks."""
        env = _env(self.home, self.data)
        return subprocess.run([*TASK_COMMAND, "state", "transition", run_id, "--dir",
                               str(self.session_dir), "--to", dest, "--reason", f"to {dest}",
                               "--confirm-leave", *extra, "--prose"],
                              capture_output=True, text=True, check=False, cwd=self.project,
                              env=env)

    def _triage_run(self, run_id, machine, node):
        """A triage run on the `machine` file, walked from clarify to `node`."""
        path = self.tmp / f"init-{run_id}.txt"
        text = valid_settlement(machine.read_text(), extra="triage_cutoff: product\n")
        path.write_text(text.replace("task_type: ticket-to-pr\n", "task_type: triage\n", 1))
        result = self._task("session", "init", run_id, "--dir", str(self.session_dir),
                            "--settlement-file", str(path), "--prose")
        self.assertEqual(result.returncode, 0, result.stderr)
        for dest in TRIAGE_WALK[:TRIAGE_WALK.index(node) + 1]:
            moved = self._move(run_id, dest)
            self.assertEqual(moved.returncode, 0, moved.stderr)
        return self.session_dir / f"{run_id}.md"

    def _gate(self, slate):
        return self._converge("gate", slate, "--dir", str(self.ledgers), "--kind", "triage",
                              "--report", str(self.report))
