"""The shared Converge command through Gear: every slate command with its
printed lines and its `next:` step, role and budget refusals, and advisor seats."""
from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path

from conftest import GEAR_COMMAND, gear_args

CONVERGE_COMMAND = gear_args()

PLUGIN_DIR = Path(__file__).resolve().parents[1]
PROGRAM = GEAR_COMMAND
ANGLES = PLUGIN_DIR.parent / "review" / "skills" / "review" / "references" / "find-angles.yaml"

FIND_ANGLES = """\
- id: changed-contract
  tag: find
  tell: signature or semantics changed
  asks: which callers assume the old contract?
- id: failure-path
  tag: find
  tell: I/O or multi-step write
  asks: timeout, partial write?
"""

# The attack angles left enabled, in snapshot order: exactly one table batch.
BATCH_1 = ("cited-but-unread", "point-in-time", "provenance", "reachability", "absent-vs-default")
DISABLED = ("downstream-consumer, inverse-reading, carve-out, boundary, dependents, "
            "positive-control, inherited-bounds, guarded-elsewhere, deliberate, real-referent")
STEPS = f"steps: {{cut: both, gap_hunt: false, escalate: true}}\nangles: {{disable: [{DISABLED}]}}\n"
FILE_ARGS = ("--evidence", "a.py:1 reads x.y with x None", "--tier", "traced")
CUT_EVIDENCE = ("--evidence", "entry-points=POST /x reaches it",
                "--evidence", "blast-radius=one row per call",
                "--evidence", "affected-count=one record",
                "--evidence", "files-touched=a.py")

MAIN, FINDER, R1, R2, CUTTER = "orch", "finder", "r1", "r2", "cutter"


def _run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "HOME": str(root / "home")}
    # VIRTUAL_ENV makes uv print a mismatch warning on stderr.
    env.pop("VIRTUAL_ENV", None)
    env.pop("BOOTGEAR_OUTPUT", None)
    return subprocess.run(
        [*CONVERGE_COMMAND, *args],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _ok(root: Path, *args: str, code: int = 0) -> subprocess.CompletedProcess[str]:
    result = _run(root, *args)
    assert result.returncode == code, (
        f"exit {result.returncode} for {args}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}")
    return result


class Slate:
    """One slate `s1` in `root/ledgers`, driven through the registered Gear command."""

    def __init__(self, root: Path):
        self.root = root
        self.dir = root / "ledgers"
        self.angles = root / "find-angles.yaml"
        self.angles.write_text(FIND_ANGLES)

    def ok(self, command: str, *args: str, code: int = 0) -> subprocess.CompletedProcess[str]:
        return _ok(self.root, command, "s1", "--dir", str(self.dir), *args, code=code)

    def lines(self, command: str, *args: str, code: int = 0) -> list[str]:
        result = self.ok(command, *args, code=code)
        return (result.stdout if code in (0, 1) else result.stderr).splitlines()

    def cmd(self, rest: str) -> str:
        return f"{PROGRAM} {rest.format(dir=shlex.quote(str(self.dir)))}"

    def plan(self) -> str:
        return self.cmd("status s1 --dir {dir} --json")

    def role_next(self, actor: str, *, structured: bool = False) -> str:
        prefix = "refresh your work: " if structured else "report the result to main; refresh your work: "
        return "next: " + prefix + PROGRAM.removesuffix(" converge converge") + " cli coordination poll"

    def init(self, *extra: str, config: str = STEPS) -> None:
        path = self.root / "task.yaml"
        path.write_text(config)
        self.ok("init", "--as", MAIN, "--lenses", "correctness", "--angles", str(self.angles),
                "--project-root", str(self.root), "--config", str(path), *extra)

    def file(self, claim: str = "x breaks y", agent: str = FINDER, *extra: str,
             code: int = 0) -> subprocess.CompletedProcess[str]:
        return self.ok("file", "--as", agent, "--lens", "correctness",
                       "--angle", "changed-contract", "--origin", "lens", "--loc", "a.py:1",
                       "--claim", claim, "--trigger", "caller passes None", *FILE_ARGS, *extra,
                       code=code)

    def cover(self) -> None:
        for angle in ("changed-contract", "failure-path"):
            self.ok("angle-na", "--as", FINDER, "--phase", "find", "--lens", "correctness",
                    "--angle", angle, "--reason", "no I/O in diff")

    def escalate(self, claim: str) -> list[str]:
        return self.lines("escalate", "--as", FINDER, "--claim", claim)

    def cut(self, claim: str, when: str, impact: str = "wrong-output", reach: str = "normal",
            difficulty: str = "cross-cutting", agent: str = CUTTER, rnd: int = 1,
            extra: tuple[str, ...] = (), code: int = 0) -> list[str]:
        """One `cut`; `difficulty` is passed at an after cut only, with a choice when it is
        cross-cutting or redesign and `extra` names none."""
        after: tuple[str, ...] = ()
        if when == "after":
            after = ("--difficulty", difficulty)
            if difficulty in ("cross-cutting", "redesign") and "--choice" not in extra:
                after += ("--choice", "patch the caller or move the check")
        return self.lines("cut", "--as", agent, "--claim", claim, "--when", when,
                          "--round", str(rnd), "--impact", impact, "--size", "one",
                          "--reach", reach, *after, *CUT_EVIDENCE, *extra, code=code)

    def accept(self, claim: str, when: str) -> list[str]:
        return self.lines("accept", "--as", FINDER, "--claim", claim, "--when", when,
                          "--round", "1")

    def check(self, angle: str, *extra: str, agent: str = R1, batch: str = "1",
               outcome: str = "clean", code: int = 0, claim: str = "F001") -> list[str]:
        if outcome == "clean":
            value = {"slate": "s1", "source_seq": len((self.dir / "s1.jsonl").read_text().splitlines()),
                     "role": agent, "action": "clean", "claim": claim,
                     "batch": int(batch) if batch.isdigit() else batch,
                     "checks": [{"angle": angle, "tell": "tell applies", "evidence": "read a.py:1",
                                 "searches": "rg x", "positive_control": "rg y finds y"}]}
            if "--last" in extra:
                value["last"] = True
                extra = tuple(item for item in extra if item != "--last")
            path = self.root / "check.json"
            path.write_text(json.dumps(value))
            return self.lines("clean", "--as", agent, "--input", str(path), *extra, code=code)
        return self.lines("attack", "--as", agent, "--claim", claim, "--batch", batch,
                          "--angle", angle, "--tell", "tell applies",
                          "--evidence", "read a.py:1", "--searches", "rg x",
                          "--positive-control", "rg y finds y", *extra, code=code)

    def batch_1(self, refuted: tuple[str, ...] = ()) -> None:
        for angle in BATCH_1:
            self.check(angle, outcome="refuted" if angle in refuted else "clean")

    def status(self) -> dict:
        data = json.loads(self.ok("status", "--json").stdout)
        data["by_id"] = {row["id"]: row for row in data["claims"]}
        return data

    def to_attack(self, config: str = STEPS) -> None:
        """Two claims, find coverage, escalate, and cut-before: F001 kept, F002 unverified."""
        self.init(config=config)
        self.file("None crashes the parser")
        self.file("log line typo")
        self.cover()
        for claim in ("F001", "F002"):
            self.escalate(claim)
        self.cut("F001", "before")
        self.accept("F001", "before")
        self.cut("F002", "before", "cosmetic")
        self.accept("F002", "before")

    def to_cut_after(self) -> None:
        self.to_attack()
        self.batch_1()
        self.check("retry timing", "--last", agent=R2, batch="fresh-eye")


def _seq(lines: list[str]) -> str:
    return lines[0].split()[1].removeprefix("seq=")


def _example(lines: list[str]) -> str:
    return next(line for line in lines if line.startswith("example: "))


# -- advisor seats: init --settlement / --refuters and status ---------------------------

ADVISOR_SETTLEMENT = ("converge_seats:\n  r2: advisor\n"
                      "advisor_roles:\n  roles: [refuter, gap-hunter]\n  brief: Act only as r2.\n  startup: direct\n")
FIX_NEXT = ("next: correct converge_seats or advisor_roles in {path} so they agree, then rerun "
            "init; in an engine run the settlement is fixed: stop blocked and report this refusal")


def _settlement(root: Path, text: str) -> Path:
    path = root / "settlement.yaml"
    path.write_text(text)
    return path


def _seat_init(root: Path, ledger: Path, *extra: str, code: int = 0
               ) -> subprocess.CompletedProcess[str]:
    return _ok(root, "init", "s1", "--dir", str(ledger), "--as", MAIN,
               "--lenses", "correctness", "--angles", str(ANGLES), "--project-root", str(root),
               *extra, code=code)


def _one(lines: list[str], prefix: str) -> str:
    found = [line for line in lines if line.startswith(prefix)]
    assert len(found) == 1, (prefix, lines)
    return found[0]


# -- fix-now and fix-check ------------------------------------------------------------


AFTER_ONLY = (f"steps: {{cut: after, gap_hunt: false, escalate: false}}\n"
              f"angles: {{disable: [{DISABLED}]}}\n")
PATCH = ("diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1,1 +1,3 @@\n"
         "-x = y.z\n+if y is None:\n+    raise ValueError\n+x = y.z\n")


def _stamp(ledger: Path, after: int, ts: str) -> int:
    """Set `ts` on every event after seq `after`; the ledger's last seq."""
    events = [json.loads(line) for line in ledger.read_text().splitlines()]
    for event in events:
        if event["seq"] > after:
            event["ts"] = ts
    ledger.write_text("".join(json.dumps(event) + "\n" for event in events))
    return events[-1]["seq"]


def _patch_review(root: Path, slate: Slate, name: str, ts: str) -> None:
    """A clean patch-only re-review slate `name` with its cutoff stamped `ts`."""
    task = root / f"{name}.yaml"
    task.write_text(AFTER_ONLY)
    review = (name, "--dir", str(slate.dir))
    _ok(root, "init", *review, "--as", MAIN, "--lenses", "correctness",
        "--angles", str(slate.angles), "--project-root", str(root), "--config", str(task))
    for angle in ("changed-contract", "failure-path"):
        _ok(root, "angle-na", *review, "--as", FINDER, "--phase", "find",
            "--lens", "correctness", "--angle", angle, "--reason", "the patch has no I/O")
    _ok(root, "cutoff", *review)
    _stamp(slate.dir / f"{name}.jsonl", 0, ts)
