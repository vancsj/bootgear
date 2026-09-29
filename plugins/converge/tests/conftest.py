"""Drive `bin/converge` as a subprocess against a scratch ledger dir.

HOME is pointed at a scratch dir so the user config layer is empty; uv's
cache and managed-python dirs stay on the real ones so no download happens.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

PLUGIN_DIR = Path(__file__).resolve().parents[1]
BIN = PLUGIN_DIR / "bin" / "converge"

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

    def run(self, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run([str(BIN), *args], capture_output=True, text=True,
                              env={**self.env, **(env or {})}, cwd=self.project, check=False)

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
             agent: str = "orch", *extra: str) -> None:
        args = ["--as", agent, "--mode", mode, "--project-root", str(self.project)]
        if lenses:
            args += ["--lenses", lenses]
        args += ["--angles", str(self.angles), *extra]
        self.ok("init", slate, *args)

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
