"""Drive the converge CLI against a scratch ledger dir.

`Converge.run` calls `converge.cli.main` in-process by default. In-process runs
see the test interpreter's packages, not only the plugin's declared ones, so
tests that must exercise the shipped wrapper set `use_bin` or run `BIN`
directly. HOME is pointed at a scratch dir so the user config layer is empty;
uv's cache and managed-python dirs stay on the real ones so no download happens.
"""
from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

PLUGIN_DIR = Path(__file__).resolve().parents[1]
BIN = PLUGIN_DIR / "bin" / "converge"
sys.path.insert(0, str(PLUGIN_DIR / "src"))

from converge import cli, ledger

FIND_ANGLES = """\
- id: changed-contract
  tag: find
  tell: signature or semantics changed
  asks: which callers assume the old contract?
- id: failure-path
  tag: find
  tell: I/O or multi-step write
  asks: timeout, partial write?
- id: god-object
  tag: find
  lens: architecture
  tell: one class gains unrelated duties
  asks: what change now touches it?
  cost: every feature edits one file
"""

# The finder's `file --evidence` in the helpers.
FILE_EVIDENCE = "a.py:10 reads x.y with x None"
FILE_ARGS = ("--evidence", FILE_EVIDENCE, "--tier", "traced")

CUT_EVIDENCE = ("--evidence", "entry-points=POST /x reaches it",
                "--evidence", "blast-radius=one row per call",
                "--evidence", "affected-count=one record",
                "--evidence", "files-touched=a.py")
CUT_EVIDENCE_MAP = {key: text for key, _, text in
                    (item.partition("=") for item in CUT_EVIDENCE[1::2])}
# A cut the built-in `default` lens attacks and reports; an after cut adds a fix that is
# not cheap, so gate 2 reports it as a finding with a choice.
CUT_DEFAULTS = {"impact": "wrong-output", "size": "one", "reach": "normal"}
CHOICE = "patch the caller or move the check"
AFTER_DEFAULTS = {"difficulty": "cross-cutting", "choice": CHOICE}

# The attack angles a `ready` slate keeps, in snapshot order: exactly one table batch.
BATCH_1 = ("cited-but-unread", "point-in-time", "provenance", "reachability", "absent-vs-default")
DISABLED = ["downstream-consumer", "inverse-reading", "carve-out", "boundary", "dependents",
            "positive-control", "inherited-bounds", "guarded-elsewhere", "deliberate",
            "real-referent"]


def _uv_dirs() -> dict[str, str]:
    env: dict[str, str] = {}
    for var, cmd in (("UV_CACHE_DIR", ("uv", "cache", "dir")),
                     ("UV_PYTHON_INSTALL_DIR", ("uv", "python", "dir"))):
        if var in os.environ:
            env[var] = os.environ[var]
            continue
        out = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if out.returncode == 0 and out.stdout.strip():
            env[var] = out.stdout.strip()
    return env


UV_DIRS = _uv_dirs()

# The full-depth allocation: five agent ids per slate, main included.
MAIN, FINDER, R1, R2, CUTTER = "orch", "finder", "r1", "r2", "cutter"


class Converge:
    def __init__(self, root: Path):
        self.root = root
        self.dir = root / "ledgers"
        self.home = root / "home"
        self.project = root / "project"
        for path in (self.home, self.project):
            path.mkdir(parents=True, exist_ok=True)
        self.angles = root / "find-angles.yaml"
        self.angles.write_text(FIND_ANGLES)
        # Prose is the CLI default; JSON tests pass --json explicitly.
        self.env = {**os.environ, **UV_DIRS, "HOME": str(self.home), "BOOTGEAR_OUTPUT": "prose"}
        # VIRTUAL_ENV makes uv print a mismatch warning on stderr.
        for var in ("CONVERGE_HOST", "BOOTGEAR_PROG", "GEAR_CALLER_CWD", "VIRTUAL_ENV"):
            self.env.pop(var, None)
        # False: call `cli.main` in-process. True: run the real `bin/converge`,
        # which resolves the plugin's own declared dependencies through uv.
        self.use_bin = False

    def run(self, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        if self.use_bin:
            return subprocess.run([str(BIN), *args], capture_output=True, text=True,
                                  env={**self.env, **(env or {})}, cwd=self.project, check=False)
        return self._run_in_process(*args, env=env)

    def _run_in_process(self, *args: str, env: dict[str, str] | None = None
                        ) -> subprocess.CompletedProcess[str]:
        """Call `converge.cli.main` with `bin/converge`'s env and cwd, but on the
        test interpreter: packages the plugin does not declare are importable here."""
        saved_env, saved_cwd = dict(os.environ), os.getcwd()
        out, err = io.StringIO(), io.StringIO()
        code = 0
        try:
            os.environ.clear()
            os.environ.update({**self.env, **(env or {})})
            os.chdir(self.project)
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    cli.main(list(args))
                except SystemExit as exc:
                    # `clikit.run` turns every `sys.exit(str)` into an int exit.
                    code = int(exc.code or 0)
        finally:
            os.chdir(saved_cwd)
            os.environ.clear()
            os.environ.update(saved_env)
        return subprocess.CompletedProcess([str(BIN), *args], code, out.getvalue(), err.getvalue())

    def __call__(self, *args: str, code: int = 0, env: dict[str, str] | None = None
                 ) -> subprocess.CompletedProcess[str]:
        result = self.run(*args, env=env)
        assert result.returncode == code, (
            f"exit {result.returncode} != {code} for {args}\nstdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}")
        return result

    def with_dir(self, *args: str) -> list[str]:
        return [*args, "--dir", str(self.dir)]

    def ok(self, command: str, slate: str, *args: str, code: int = 0) -> subprocess.CompletedProcess[str]:
        return self(command, slate, "--dir", str(self.dir), *args, code=code)

    def refused(self, command: str, slate: str, *args: str) -> str:
        return self.ok(command, slate, *args, code=2).stderr

    # -- event helpers ---------------------------------------------------

    def init(self, slate: str = "s1", lenses: str = "correctness,security", agent: str = MAIN,
             *extra: str, config: dict[str, Any] | None = None) -> None:
        """Init a slate with `config` as its task config layer."""
        args = ["--as", agent, "--project-root", str(self.project)]
        if lenses:
            args += ["--lenses", lenses]
        args += ["--angles", str(self.angles), *extra]
        if config:
            path = self.root / f"{slate}.task.yaml"
            path.write_text(yaml.safe_dump(copy.deepcopy(config)))
            args += ["--config", str(path)]
        self.ok("init", slate, *args)

    def ready(self, cut: str = "none", claims: int = 1, escalate: bool = True,
              config: dict[str, Any] | None = None, refuters: int = 2, **caps: Any) -> list[str]:
        """A slate whose attack angles are `BATCH_1`, with `claims` claims filed by FINDER,
        find coverage complete and, with `escalate`, every claim escalated."""
        task: dict[str, Any] = {"steps": {"cut": cut, "gap_hunt": False, "escalate": escalate},
                                "angles": {"disable": DISABLED}, **(config or {})}
        if caps:
            task["caps"] = caps
        self.init("s1", "correctness,security", MAIN, "--refuters", str(refuters), config=task)
        ids = [self.file(claim=f"claim {n}") for n in range(1, claims + 1)]
        self.cover()
        if escalate:
            for cid in ids:
                assert self.append("escalate", FINDER, claim=cid) == []
        return ids

    def file(self, slate: str = "s1", agent: str = FINDER, lens: str = "correctness",
             angle: str = "changed-contract", origin: str = "lens", claim: str = "x breaks y",
             extra: tuple[str, ...] = (), code: int = 0, evidence: str = FILE_EVIDENCE,
             tier: str = "traced") -> str:
        args = ["--as", agent, "--loc", "src/a.py:10", "--claim", claim,
                "--trigger", "caller passes None", "--origin", origin,
                "--evidence", evidence, "--tier", tier]
        if lens:
            args += ["--lens", lens]
        if angle:
            args += ["--angle", angle]
        result = self.ok("file", slate, *args, *extra, code=code)
        return result.stdout.split()[1] if code == 0 else result.stderr

    def cut(self, claim: str, rnd: int, agent: str = CUTTER, when: str = "after",
            impact: str = "wrong-output", size: str = "one", reach: str = "normal",
            difficulty: str = "cross-cutting", *extra: str,
            slate: str = "s1", code: int = 0) -> subprocess.CompletedProcess[str]:
        """One `cut` through the CLI; `difficulty` is passed at an after cut only, with
        `CHOICE` when it is cross-cutting or redesign and `extra` names no choice."""
        after: tuple[str, ...] = ()
        if when == "after":
            after = ("--difficulty", difficulty)
            if difficulty in ("cross-cutting", "redesign") and "--choice" not in extra:
                after += ("--choice", CHOICE)
        return self.ok("cut", slate, "--as", agent, "--claim", claim, "--round", str(rnd),
                       "--when", when, "--impact", impact, "--size", size, "--reach", reach,
                       *after, *CUT_EVIDENCE, *extra, code=code)

    def accept(self, claim: str, rnd: int, agent: str = FINDER, when: str = "after",
               slate: str = "s1", code: int = 0) -> subprocess.CompletedProcess[str]:
        return self.ok("accept", slate, "--as", agent, "--claim", claim, "--round", str(rnd),
                       "--when", when, code=code)

    def rebut_cut(self, claim: str, evidence: str, agent: str = FINDER, when: str = "after",
                  slate: str = "s1", code: int = 0) -> subprocess.CompletedProcess[str]:
        return self.ok("rebut", slate, "--as", agent, "--claim", claim, "--when", when,
                       "--evidence", evidence, code=code)

    def cover(self, slate: str = "s1", lenses: tuple[str, ...] = ("correctness", "security")) -> None:
        for lens in lenses:
            for angle in ("changed-contract", "failure-path"):
                self.ok("angle-na", slate, "--as", FINDER, "--phase", "find",
                        "--angle", angle, "--lens", lens, "--reason", "no I/O in diff")

    def append(self, kind: str, agent: str, slate: str = "s1", **fields: Any) -> list[str]:
        """Append one event through the ledger, not the CLI; the problems, or [] when written.
        A field given as None is left out."""
        event = {"event": kind, "as": agent, **fields}
        if kind == "cut":
            after = AFTER_DEFAULTS if fields.get("when") == "after" else {}
            event = {**CUT_DEFAULTS, **after, "evidence": dict(CUT_EVIDENCE_MAP), **event}
        event = {key: value for key, value in event.items() if value is not None}
        if kind == "rebut" and "evidence" in fields:
            event["evidence_sha256"] = ledger.evidence_hash(fields["evidence"])
        try:
            ledger.append(self.path(slate), slate, event)
        except ledger.LedgerError as exc:
            return exc.problems
        return []

    def attack(self, cid: str, angle: str, agent: str = R1, batch: Any = 1,
               outcome: str = "clean", slate: str = "s1", **extra: Any) -> list[str]:
        return self.append("attack", agent, slate=slate, claim=cid, batch=batch, angle=angle,
                           tell="tell applies", outcome=outcome, evidence="read a.py:10",
                           searches="rg foo", positive_control="rg bar finds bar", **extra)

    def attack_cli(self, cid: str, angle: str, *extra: str, agent: str = R1, batch: Any = 1,
                   outcome: str = "clean", slate: str = "s1",
                   code: int = 0) -> subprocess.CompletedProcess[str]:
        """One `attack` through the CLI."""
        return self.ok("attack", slate, "--as", agent, "--claim", cid, "--batch", str(batch),
                       "--angle", angle, "--tell", "tell applies", "--outcome", outcome,
                       "--evidence", "read a.py:10", "--searches", "rg foo",
                       "--positive-control", "rg bar finds bar", *extra, code=code)

    def batch_1(self, cid: str = "F001", refuted: tuple[str, ...] = (), agent: str = R1) -> None:
        for angle in BATCH_1:
            outcome = "refuted" if angle in refuted else "clean"
            assert self.attack(cid, angle, agent=agent, outcome=outcome) == []

    def fresh_eye(self, cid: str = "F001", agent: str = R2) -> None:
        assert self.attack(cid, "retry timing", agent=agent, batch="fresh-eye", last=True) == []

    def clean(self, cid: str = "F001", fresh_eye_agent: str = R2) -> None:
        """Every batch of a `ready` slate's claim, all clean."""
        self.batch_1(cid)
        self.fresh_eye(cid, agent=fresh_eye_agent)

    def rate(self, cid: str = "F001", when: str = "after", finder: str = FINDER,
             **values: Any) -> None:
        """Cut round 1 of `cid` at `when` with `values`, accepted by its finder."""
        assert self.append("cut", CUTTER, claim=cid, round=1, when=when, **values) == []
        assert self.append("accept", finder, claim=cid, round=1, when=when) == []

    # -- inspection ------------------------------------------------------

    def path(self, slate: str = "s1") -> Path:
        return self.dir / f"{slate}.jsonl"

    def events(self, slate: str = "s1") -> list[dict[str, Any]]:
        return [json.loads(line) for line in self.path(slate).read_text().splitlines()]

    def status(self, slate: str = "s1") -> dict[str, Any]:
        data = json.loads(self.ok("status", slate, "--json").stdout)
        data["by_id"] = {c["id"]: c for c in data["claims"]}
        return data


@pytest.fixture
def cv(tmp_path: Path) -> Converge:
    return Converge(tmp_path)
