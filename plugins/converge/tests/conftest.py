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

from converge import cli, ledger, model
from converge import config as config_mod

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

CUT_EVIDENCE = ("--evidence", "entry-points=POST /x reaches it",
                "--evidence", "blast-radius=one row per call",
                "--evidence", "evidence-tier=traced a.py:10-20",
                "--evidence", "files-touched=a.py")
CUT_EVIDENCE_MAP = {key: text for key, _, text in
                    (item.partition("=") for item in CUT_EVIDENCE[1::2])}
CUT_DEFAULTS = {"frequency": "common", "severity": "wrong-behavior", "confidence": "traced",
                "difficulty": "local"}


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
STEPS_OFF = {"escalate": False, "early_cut": False, "gap_hunt": False}


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

    def init(self, slate: str = "s1", mode: str = "full", lenses: str = "correctness,security",
             agent: str = "orch", *extra: str, config: dict[str, Any] | None = None,
             defaults: bool = False, legacy: bool = False) -> None:
        """Init with one task config: `config` plus every step off, so a test keeps the
        file → refute → cut flow; `defaults` keeps the steps as configured. `legacy` then
        drops `steps` and the batch caps from the snapshot, as a slate from before them."""
        task = copy.deepcopy(config or {})
        if not defaults:
            task["steps"] = {**STEPS_OFF, **task.get("steps", {})}
        args = ["--as", agent, "--mode", mode, "--project-root", str(self.project)]
        if lenses:
            args += ["--lenses", lenses]
        args += ["--angles", str(self.angles), *extra]
        if task:
            path = self.root / f"{slate}.task.yaml"
            path.write_text(yaml.safe_dump(task))
            args += ["--config", str(path)]
        self.ok("init", slate, *args)
        if legacy:
            events = self.events(slate)
            del events[0]["config"]["steps"]
            for key in ("angles_per_claim", "batch_items"):
                del events[0]["config"]["caps"][key]
            self.path(slate).write_text("".join(json.dumps(e) + "\n" for e in events))

    def file(self, slate: str = "s1", agent: str = FINDER, lens: str = "correctness",
             angle: str = "changed-contract", origin: str = "lens", claim: str = "x breaks y",
             extra: tuple[str, ...] = (), code: int = 0) -> str:
        args = ["--as", agent, "--loc", "src/a.py:10", "--claim", claim,
                "--trigger", "caller passes None", "--origin", origin]
        if lens:
            args += ["--lens", lens]
        if angle:
            args += ["--angle", angle]
        result = self.ok("file", slate, *args, *extra, code=code)
        return result.stdout.split()[-1] if code == 0 else result.stderr

    def refute(self, claim: str, rnd: int, angle: str, agent: str, outcome: str = "survived",
               *extra: str, slate: str = "s1", code: int = 0) -> subprocess.CompletedProcess[str]:
        return self.ok("refute", slate, "--as", agent, "--claim", claim, "--round", str(rnd),
                       "--angle", angle, "--tell", "tell applies", "--outcome", outcome,
                       "--evidence", "read a.py:10", "--searches", "rg foo",
                       "--positive-control", "rg bar finds bar", *extra, code=code)

    def quiet_round(self, claim: str, rnd: int, angles: tuple[str, str], slate: str = "s1",
                    outcome: str = "survived", agents: tuple[str, str] = (R1, R2)) -> None:
        for angle, agent in zip(angles, agents, strict=True):
            self.refute(claim, rnd, angle, agent, outcome, slate=slate)

    def cut(self, claim: str, rnd: int, agent: str, frequency: str = "common",
            severity: str = "wrong-behavior", confidence: str = "traced",
            difficulty: str = "local", *extra: str, slate: str = "s1",
            code: int = 0) -> subprocess.CompletedProcess[str]:
        return self.ok("cut", slate, "--as", agent, "--claim", claim, "--round", str(rnd),
                       "--frequency", frequency, "--severity", severity,
                       "--confidence", confidence, "--difficulty", difficulty,
                       *CUT_EVIDENCE, *extra, code=code)

    def accept(self, claim: str, rnd: int, agent: str = FINDER, slate: str = "s1",
               code: int = 0) -> subprocess.CompletedProcess[str]:
        return self.ok("accept", slate, "--as", agent, "--claim", claim, "--round", str(rnd), code=code)

    def rebut_cut(self, claim: str, evidence: str, agent: str = FINDER, slate: str = "s1",
                  code: int = 0) -> subprocess.CompletedProcess[str]:
        return self.ok("rebut", slate, "--as", agent, "--claim", claim, "--stage", "cut",
                       "--evidence", evidence, code=code)

    def cut_converge(self, claim: str, *values: str, slate: str = "s1", extra: tuple[str, ...] = (),
                     cutter: str = CUTTER, finder: str = FINDER) -> None:
        """One cut round, accepted by the claim's finder."""
        self.cut(claim, 1, cutter, *values, *extra, slate=slate)
        self.accept(claim, 1, finder, slate=slate)

    def cover(self, slate: str = "s1", lenses: tuple[str, ...] = ("correctness", "security")) -> None:
        for lens in lenses:
            for angle in ("changed-contract", "failure-path"):
                self.ok("angle-na", slate, "--as", FINDER, "--phase", "find",
                        "--angle", angle, "--lens", lens, "--reason", "no I/O in diff")

    def append(self, kind: str, agent: str, slate: str = "s1", **fields: Any) -> list[str]:
        """Append one event through the ledger, not the CLI; the problems, or [] when written."""
        event = {"event": kind, "as": agent, **fields}
        if kind == "cut":
            event = {**CUT_DEFAULTS, "evidence": dict(CUT_EVIDENCE_MAP), **event}
        if kind == "rebut":
            event["evidence_sha256"] = ledger.evidence_hash(fields["evidence"])
        try:
            ledger.append(self.path(slate), slate, event)
        except ledger.LedgerError as exc:
            return exc.problems
        return []

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


# -- in-memory slates for model tests ------------------------------------

ATTACK_IDS = ("boundary", "reachability", "provenance", "carve-out", "dependents",
              "deliberate", "inverse-reading", "point-in-time")


def make_slate(attack: int = len(ATTACK_IDS), steps: dict[str, bool] | None = None,
               legacy: bool = False, mode: str = "full", **caps: int) -> model.Slate:
    """A replayed slate without a ledger: `attack` attack angles, the default config
    with `steps` and `caps` overridden, or no `steps` section at all when `legacy`."""
    cfg = copy.deepcopy(config_mod.DEFAULTS)
    cfg["caps"].update(caps)
    if legacy:
        del cfg["steps"]
    elif steps:
        cfg["steps"].update(steps)
    angles = [{"id": a, "tag": "attack", "tell": "t", "asks": "a"} for a in ATTACK_IDS[:attack]]
    slate = model.Slate("m1", mode=mode, lenses=["correctness"], angles=angles, config=cfg)
    slate.events.append({"seq": 1, "event": "init", "as": MAIN})
    return slate


def add_claim(slate: model.Slate, finder: str = FINDER, **fields: Any) -> model.Claim:
    n = len(slate.claims) + 1
    claim = model.Claim(id=model.claim_id(n), finder=finder, lens="correctness",
                        angle="changed-contract", loc="a.py:1", original=f"claim {n}",
                        trigger="t", origin="lens", depends=[], rule=None, filed_seq=n + 1,
                        text=f"claim {n}", **fields)
    slate.claims[claim.id] = claim
    return claim


def next_seq(slate: model.Slate) -> int:
    seq = len(slate.events) + 1
    slate.events.append({"seq": seq})
    return seq


def add_refute(slate: model.Slate, claim: model.Claim, rnd: int, angle: str,
               outcome: str = "survived") -> dict[str, Any]:
    event = {"seq": next_seq(slate), "event": "refute", "as": R1, "claim": claim.id,
             "round": rnd, "angle": angle, "outcome": outcome}
    claim.refute_rounds.setdefault(rnd, []).append(event)
    claim.used_angles.add(angle)
    if outcome == "downgraded":
        claim.downgrades.append(event)
    elif outcome in model.DEAD_OUTCOMES:
        claim.dead = outcome
    return event


def add_cut(slate: model.Slate, claim: model.Claim, severity: str = "wrong-behavior",
            frequency: str = "common", accept: bool = True, **extra: str) -> dict[str, Any]:
    rnd = claim.cut_round + 1
    event = {"seq": next_seq(slate), "event": "cut", "as": CUTTER, "claim": claim.id,
             "round": rnd, "frequency": frequency, "severity": severity,
             "confidence": "traced", "difficulty": "local", **extra}
    claim.cut_rounds[rnd] = event
    claim.stage = "cut"
    if accept:
        claim.accepted_round = rnd
    return event
