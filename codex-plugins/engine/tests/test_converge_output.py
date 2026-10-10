"""The bundled converge through the Codex `scripts/converge`: every slate command with its
printed lines and its `next:` step, role and budget refusals, and advisor seats."""
from __future__ import annotations

import json
import os
import shlex
import subprocess
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
TASK = PLUGIN_DIR / "scripts" / "converge"
ANGLES = PLUGIN_DIR / "skills" / "review" / "references" / "find-angles.yaml"

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
CUT_EVIDENCE = ("--evidence", "entry-points=POST /x reaches it",
                "--evidence", "blast-radius=one row per call",
                "--evidence", "evidence-tier=traced a.py:1",
                "--evidence", "files-touched=a.py")

MAIN, FINDER, R1, R2, CUTTER = "orch", "finder", "r1", "r2", "cutter"


def _run(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "HOME": str(root / "home")}
    # VIRTUAL_ENV makes uv print a mismatch warning on stderr.
    env.pop("VIRTUAL_ENV", None)
    env.pop("BOOTGEAR_OUTPUT", None)
    return subprocess.run(
        [str(TASK), *args],
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
    """One slate `s1` in `root/ledgers`, driven through `scripts/converge`."""

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
        return f"{TASK} {rest.format(dir=shlex.quote(str(self.dir)))}"

    def plan(self) -> str:
        return self.cmd("status s1 --dir {dir} --json")

    def init(self, *extra: str, config: str = STEPS) -> None:
        path = self.root / "task.yaml"
        path.write_text(config)
        self.ok("init", "--as", MAIN, "--lenses", "correctness", "--angles", str(self.angles),
                "--project-root", str(self.root), "--config", str(path), *extra)

    def file(self, claim: str = "x breaks y", agent: str = FINDER, *extra: str,
             code: int = 0) -> subprocess.CompletedProcess[str]:
        return self.ok("file", "--as", agent, "--lens", "correctness",
                       "--angle", "changed-contract", "--origin", "lens", "--loc", "a.py:1",
                       "--claim", claim, "--trigger", "caller passes None", *extra, code=code)

    def cover(self) -> None:
        for angle in ("changed-contract", "failure-path"):
            self.ok("angle-na", "--as", FINDER, "--phase", "find", "--lens", "correctness",
                    "--angle", angle, "--reason", "no I/O in diff")

    def escalate(self, claim: str) -> list[str]:
        return self.lines("escalate", "--as", FINDER, "--claim", claim)

    def cut(self, claim: str, when: str, frequency: str = "common",
            severity: str = "wrong-behavior", confidence: str = "traced",
            difficulty: str = "local", agent: str = CUTTER, rnd: int = 1,
            extra: tuple[str, ...] = (), code: int = 0) -> list[str]:
        return self.lines("cut", "--as", agent, "--claim", claim, "--when", when,
                          "--round", str(rnd), "--frequency", frequency, "--severity", severity,
                          "--confidence", confidence, "--difficulty", difficulty, *CUT_EVIDENCE,
                          *extra, code=code)

    def accept(self, claim: str, when: str) -> list[str]:
        return self.lines("accept", "--as", FINDER, "--claim", claim, "--when", when,
                          "--round", "1")

    def attack(self, angle: str, *extra: str, agent: str = R1, batch: str = "1",
               outcome: str = "clean", code: int = 0) -> list[str]:
        return self.lines("attack", "--as", agent, "--claim", "F001", "--batch", batch,
                          "--angle", angle, "--tell", "tell applies", "--outcome", outcome,
                          "--evidence", "read a.py:1", "--searches", "rg x",
                          "--positive-control", "rg y finds y", *extra, code=code)

    def batch_1(self, refuted: tuple[str, ...] = ()) -> None:
        for angle in BATCH_1:
            self.attack(angle, outcome="refuted" if angle in refuted else "clean")

    def status(self) -> dict:
        data = json.loads(self.ok("status", "--json").stdout)
        data["by_id"] = {row["id"]: row for row in data["claims"]}
        return data

    def to_attack(self) -> None:
        """Two claims, find coverage, escalate, and cut-before: F001 kept, F002 unverified."""
        self.init()
        self.file("None crashes the parser")
        self.file("log line typo")
        self.cover()
        for claim in ("F001", "F002"):
            self.escalate(claim)
        self.cut("F001", "before", "common", "wrong-behavior", "inferred", "local")
        self.accept("F001", "before")
        self.cut("F002", "before", "rare", "cosmetic", "inferred", "trivial")
        self.accept("F002", "before")

    def to_cut_after(self) -> None:
        self.to_attack()
        self.batch_1()
        self.attack("retry timing", "--last", agent=R2, batch="fresh-eye")


def _seq(lines: list[str]) -> str:
    return lines[0].split()[1].removeprefix("seq=")


# -- init, find, escalate, cut before ------------------------------------------------


def test_bundled_init_with_shipped_angles_needs_find_coverage(tmp_path: Path) -> None:
    ledger = tmp_path / "ledgers"
    init = _ok(tmp_path, "init", "s1", "--dir", str(ledger), "--as", MAIN,
               "--lenses", "correctness,security", "--angles", str(ANGLES),
               "--project-root", str(tmp_path))
    assert init.stdout.startswith("INIT s1 lenses=correctness,security angles=")
    status = json.loads(_ok(tmp_path, "status", "s1", "--dir", str(ledger), "--json").stdout)
    assert (status["phase"], status["claims"]) == ("find", [])
    cutoff = _ok(tmp_path, "cutoff", "s1", "--dir", str(ledger), code=2)
    assert "missing find angles" in cutoff.stderr
    rendered = json.loads(_ok(tmp_path, "render", "s1", "--dir", str(ledger), "--json").stdout)
    assert rendered["choices"] == []


def test_bundled_init_refuses_the_removed_mode_flag(tmp_path: Path) -> None:
    slate = Slate(tmp_path)
    err = _ok(tmp_path, "init", "s1", "--dir", str(slate.dir), "--as", MAIN, "--mode", "full",
              "--angles", str(slate.angles), code=2).stderr
    assert "--mode" in err
    assert not (slate.dir / "s1.jsonl").exists()


def test_bundled_find_commands_print_the_finder_step(tmp_path: Path) -> None:
    slate = Slate(tmp_path)
    slate.init()
    find = "next: continue the finder with the missing angles, then " + slate.cmd(
        "coverage s1 --dir {dir}")
    assert slate.file("c").stdout.splitlines() == ["FILED F001", find]
    out = slate.lines("find-run", "--as", FINDER, "--lens", "correctness",
                      "--angle", "changed-contract", "--tell", "t", "--searches", "s",
                      "--positive-control", "p", "--result", "F001")
    assert out == ["FIND-RUN seq=3 lens=correctness angle=changed-contract", find]
    out = slate.lines("angle-na", "--as", FINDER, "--phase", "find", "--angle", "failure-path",
                      "--lens", "correctness", "--reason", "no I/O")
    assert out[0] == "ANGLE-NA seq=4 phase=find angle=failure-path"


def test_bundled_gap_hunt_files_after_find_coverage(tmp_path: Path) -> None:
    slate = Slate(tmp_path)
    slate.init(config=STEPS.replace("gap_hunt: false", "gap_hunt: true"))
    slate.file()
    gap = ("--origin", "gap-hunt")
    err = slate.lines("file", "--as", R2, "--lens", "correctness", "--angle", "changed-contract",
                      "--loc", "a.py:1", "--claim", "ticket asks for retries",
                      "--trigger", "caller retries", *gap, code=2)
    assert "  - file: gap-hunt claims are filed after find coverage is complete" in err
    assert err[-1] == ("next: continue the finder with the missing angles, then "
                       + slate.cmd("coverage s1 --dir {dir}"))
    slate.cover()
    out = slate.lines("file", "--as", R2, "--lens", "correctness", "--angle", "changed-contract",
                      "--loc", "a.py:1", "--claim", "ticket asks for retries",
                      "--trigger", "caller retries", *gap)
    assert out[0] == "FILED F002"


def test_bundled_escalate_and_cut_before_print_the_plan_step(tmp_path: Path) -> None:
    slate = Slate(tmp_path)
    slate.init()
    slate.file()
    slate.file()
    slate.cover()
    out = slate.escalate("F001")
    assert out[1] == f"next: escalate: finder escalate F002; plan: {slate.plan()}"
    assert "file: claims are filed before the first escalate, cut or attack event" in slate.file(
        code=2).stderr
    out = slate.escalate("F002")
    assert out[0].endswith(" F002 wider=no")
    assert out[1] == f"next: cut-before: cutter cut-before F001, F002; plan: {slate.plan()}"
    out = slate.cut("F001", "before", confidence="inferred")
    assert out == [f"CUT seq={_seq(out)} F001 when=before round=1",
                   (f"next: cut-before: finder accept F001; cutter cut-before F002; "
                    f"plan: {slate.plan()}")]
    out = slate.lines("rebut", "--as", FINDER, "--claim", "F001", "--when", "before",
                      "--evidence", "prod shows every call")
    assert out == [f"REBUT seq={_seq(out)} F001 when=before",
                   f"next: cut-before: cutter cut-before F001, F002; plan: {slate.plan()}"]


def test_bundled_cut_round_waits_for_the_finder_answer(tmp_path: Path) -> None:
    slate = Slate(tmp_path)
    slate.init()
    slate.file()
    slate.cover()
    slate.escalate("F001")
    slate.cut("F001", "before", confidence="inferred")
    err = slate.cut("F001", "before", confidence="inferred", rnd=2, code=2)
    assert ("  - cut: F001 before round 1 awaits its finder; the finder must accept or rebut "
            "it first") in err
    assert err[-1] == f"next: cut-before: finder accept F001; plan: {slate.plan()}"
    slate.ok("rebut", "--as", FINDER, "--claim", "F001", "--when", "before",
             "--evidence", "the retry path is guarded")
    out = slate.cut("F001", "before", confidence="inferred", rnd=2)
    assert out[0] == f"CUT seq={_seq(out)} F001 when=before round=2"


def test_bundled_cut_before_leads_to_the_attack(tmp_path: Path) -> None:
    slate = Slate(tmp_path)
    slate.init()
    slate.file()
    slate.cover()
    slate.escalate("F001")
    slate.cut("F001", "before", confidence="inferred")
    out = slate.accept("F001", "before")
    assert out == [f"ACCEPT seq={_seq(out)} F001 when=before round=1",
                   f"next: attack: r1 attack F001 batch 1; plan: {slate.plan()}"]


# -- attack, reply, verdict -----------------------------------------------------------


def test_bundled_attack_reply_verdict_walk_the_dispute(tmp_path: Path) -> None:
    slate = Slate(tmp_path)
    slate.to_attack()
    out = slate.attack(BATCH_1[0], outcome="refuted")
    assert out == [f"ATTACK seq={_seq(out)} F001 batch=1 angle={BATCH_1[0]} outcome=refuted",
                   f"next: attack: r1 attack F001 batch 1; plan: {slate.plan()}"]
    for angle in BATCH_1[1:4]:
        slate.attack(angle)
    out = slate.lines("angle-na", "--as", R1, "--phase", "attack", "--claim", "F001",
                      "--angle", BATCH_1[4], "--reason", "no default in the diff")
    assert out[1] == f"next: attack: finder reply F001 batch 1; plan: {slate.plan()}"
    out = slate.lines("reply", "--as", FINDER, "--claim", "F001", "--batch", "1",
                      "--stance", "rebut", "--evidence", "the caller in b.py:4 passes None",
                      "--text", "None from b.py:4 crashes the parser")
    assert out == [f"REPLY seq={_seq(out)} F001 batch=1 stance=rebut",
                   f"next: attack: r1 verdict F001 batch 1; plan: {slate.plan()}"]
    out = slate.lines("verdict", "--as", R1, "--claim", "F001", "--batch", "1",
                      "--verdict", "agree")
    assert out == [f"VERDICT seq={_seq(out)} F001 batch=1 verdict=agree",
                   f"next: attack: r2 attack F001 batch fresh-eye; plan: {slate.plan()}"]
    out = slate.attack("retry timing", "--last", agent=R2, batch="fresh-eye")
    assert out == [f"ATTACK seq={_seq(out)} F001 batch=fresh-eye angle=retry timing outcome=clean",
                   f"next: cut-after: cutter cut-after F001; plan: {slate.plan()}"]
    assert slate.status()["by_id"]["F001"]["claim"] == "None from b.py:4 crashes the parser"


def test_bundled_attack_refusals_name_the_role_and_the_next_step(tmp_path: Path) -> None:
    slate = Slate(tmp_path)
    slate.to_attack()
    err = slate.attack(BATCH_1[0], agent=FINDER, code=2)
    assert err[:2] == ["converge: refused:", "  - attack: finder filed F001 and may not attack it"]
    assert err[-1] == f"next: attack: r1 attack F001 batch 1; plan: {slate.plan()}"
    err = slate.attack(BATCH_1[0], agent=MAIN, code=2)
    assert "  - attack: orch wrote init; the orchestrator never writes attack" in err
    err = slate.attack(BATCH_1[0], agent=CUTTER, code=2)
    assert "  - attack: cutter cut F001; refuters and cutters are disjoint" in err
    err = slate.attack(BATCH_1[0], batch="2", code=2)
    assert "  - attack: F001's open batch is 1 (open); got batch 2" in err


def _example(lines: list[str]) -> str:
    return next(line for line in lines if line.startswith("example: "))


def test_bundled_angle_na_refusal_shows_the_form_for_its_phase(tmp_path: Path) -> None:
    slate = Slate(tmp_path)
    slate.to_attack()
    attack_step = f"next: attack: r1 attack F001 batch 1; plan: {slate.plan()}"
    err = slate.lines("angle-na", "--as", FINDER, "--phase", "find", "--angle", "failure-path",
                      "--reason", "no I/O", code=2)
    assert _example(err).startswith(f"example: {TASK} angle-na ")
    assert "--phase find --lens" in _example(err)
    assert err[-1] == attack_step
    err = slate.lines("angle-na", "--as", R1, "--phase", "attack", "--angle", BATCH_1[0],
                      "--reason", "no boundary in a constant", code=2)
    assert _example(err).startswith(f"example: {TASK} angle-na ")
    assert "--phase attack --claim" in _example(err)
    assert err[-1] == attack_step


def test_bundled_angle_na_usage_refusal_follows_the_phase(tmp_path: Path) -> None:
    slate = Slate(tmp_path)
    slate.to_attack()
    err = slate.lines("angle-na", "--as", FINDER, "--phase", "find", "--lens", "correctness",
                      "--angle", "failure-path", code=2)
    assert any("--reason" in line for line in err if not line.startswith("example: ")), err
    assert "--phase find --lens" in _example(err)
    err = slate.lines("angle-na", "--as", R1, "--phase", "attack", "--claim", "F001",
                      "--angle", BATCH_1[0], code=2)
    assert any("--reason" in line for line in err if not line.startswith("example: ")), err
    assert "--phase attack --claim" in _example(err)


def test_bundled_decline_kills_the_claim(tmp_path: Path) -> None:
    slate = Slate(tmp_path)
    slate.to_attack()
    slate.batch_1(refuted=(BATCH_1[0],))
    out = slate.lines("reply", "--as", FINDER, "--claim", "F001", "--batch", "1",
                      "--stance", "decline")
    assert out == [f"REPLY seq={_seq(out)} F001 batch=1 stance=decline",
                   "next: " + slate.cmd("cutoff s1 --dir {dir}")]
    claim = slate.status()["by_id"]["F001"]
    assert (claim["status"], claim["cut"]) == ("killed", "no")


# -- cut after, cutoff, render, gate, converged -----------------------------------------


def test_bundled_cutoff_gate_render_converged(tmp_path: Path) -> None:
    slate = Slate(tmp_path)
    slate.to_cut_after()
    slate.cut("F001", "after")
    cutoff_step = "next: " + slate.cmd("cutoff s1 --dir {dir}")
    err = slate.lines("cutoff", code=2)
    assert err[:2] == ["converge: refused:", "  - F001 is open in cut-after"]
    assert err[-1] == f"next: cut-after: finder accept F001; plan: {slate.plan()}"
    assert slate.lines("gate", code=1) == [
        "GATE fail s1", "F001 is open in cut-after",
        "no current cutoff (run `converge cutoff` after the last state change)",
        f"next: cut-after: finder accept F001; plan: {slate.plan()}"]
    out = slate.accept("F001", "after")
    assert out == [f"ACCEPT seq={_seq(out)} F001 when=after round=1", cutoff_step]
    assert slate.lines("converged", code=1) == ["OPEN phase=cutoff claims=0", cutoff_step]
    out = slate.lines("cutoff")
    seq = _seq(out)
    assert out == [f"CUTOFF seq={seq} findings=1 follow-up=1 killed=0",
                   "F001 finding status=survived cut=no rank=1 reason=report_if[1]",
                   "F002 follow-up status=unverified cut=yes rank=2 reason=unverified",
                   "next: " + slate.cmd("render s1 --dir {dir}")]
    render = slate.ok("render").stdout
    assert "findings=1 follow-up=1 killed=0 converged=yes" in render
    assert slate.lines("gate") == [f"GATE ok s1 cutoff_seq={seq}",
                                   "next: " + slate.cmd("converged s1 --dir {dir}")]
    assert slate.lines("converged") == ["CONVERGED", "next: end the slate with outcome converged"]


def test_bundled_render_choices_hold_findings_only(tmp_path: Path) -> None:
    """F001 a finding and F002 unverified, each rated redesign with a choice."""
    slate = Slate(tmp_path)
    slate.init()
    slate.file("None crashes the parser")
    slate.file("log line typo")
    slate.cover()
    for claim in ("F001", "F002"):
        slate.escalate(claim)
    slate.cut("F001", "before", confidence="inferred", difficulty="redesign",
              extra=("--choice", "split or patch"))
    slate.accept("F001", "before")
    slate.cut("F002", "before", "rare", confidence="inferred", difficulty="redesign",
              extra=("--choice", "drop or keep"))
    slate.accept("F002", "before")
    slate.batch_1()
    slate.attack("retry timing", "--last", agent=R2, batch="fresh-eye")
    slate.cut("F001", "after", difficulty="redesign", extra=("--choice", "split or patch"))
    slate.accept("F001", "after")
    slate.ok("cutoff")
    render = slate.ok("render").stdout
    choices = render.split("## Choices\n\n", 1)[1].split("\n\n", 1)[0]
    assert choices == "- **F001** (finding) — split or patch"
    follow_up = render.split("## Follow-up\n\n", 1)[1].split("\n\n", 1)[0]
    assert "| F002 |" in follow_up and "| unverified | drop or keep | unverified |" in follow_up
    data = json.loads(slate.ok("render", "--json").stdout)
    assert data["choices"] == [{"claim": "F001", "result": "finding", "choice": "split or patch"}]


def test_bundled_converged_lists_the_disputed_findings(tmp_path: Path) -> None:
    slate = Slate(tmp_path)
    slate.to_attack()
    slate.batch_1(refuted=(BATCH_1[0],))
    slate.ok("reply", "--as", FINDER, "--claim", "F001", "--batch", "1", "--stance", "rebut",
             "--evidence", "b.py:4 passes None")
    slate.ok("verdict", "--as", R1, "--claim", "F001", "--batch", "1",
             "--verdict", "disagree", "--evidence", "b.py:4 is dead code")
    slate.ok("reply", "--as", FINDER, "--claim", "F001", "--batch", "1", "--stance", "rebut",
             "--evidence", "the router reaches b.py:4")
    slate.attack("retry timing", "--last", agent=R2, batch="fresh-eye")
    slate.cut("F001", "after", severity="security")
    slate.accept("F001", "after")
    slate.ok("cutoff")
    assert slate.lines("converged", code=1) == [
        "OPEN phase=done claims=1", "F001 disputed cut=no",
        "next: end the slate with outcome unconverged; disputed findings: F001"]
    assert slate.ok("gate").stdout.startswith("GATE ok s1 ")


# -- budget and reserved ids -------------------------------------------------------------


def test_bundled_converge_refuses_a_sixth_agent(tmp_path: Path) -> None:
    slate = Slate(tmp_path)
    slate.to_cut_after()
    path = slate.dir / "s1.jsonl"
    before = path.read_bytes()
    err = slate.cut("F001", "after", agent="cutter-2", code=2)
    assert any("agent budget: cutter-2 would be agent 6 on this slate; caps.agents is 5" in line
               for line in err), err
    assert path.read_bytes() == before


def test_bundled_converge_reserves_the_converge_agent_id(tmp_path: Path) -> None:
    slate = Slate(tmp_path)
    slate.init()
    err = slate.file("z", "converge", code=2).stderr
    assert "agent id 'converge' is reserved for computed cutoff events" in err


def test_bundled_status_prints_claims_plan_and_next(tmp_path: Path) -> None:
    slate = Slate(tmp_path)
    slate.to_attack()
    slate.attack(BATCH_1[0])
    out = slate.lines("status")
    assert out[0] == ("SLATE s1 lenses=correctness phase=attack cutoff=none claims=2 "
                      "agents=4/5 advisor=-")
    assert out[-2] == f"PLAN 1 F001 attack r1 batch=1 angles={','.join(BATCH_1[1:])}"
    assert out[-1] == f"next: attack: r1 attack F001 batch 1; plan: {slate.plan()}"
    data = slate.status()
    assert data["caps"] == {"cut_rounds": 5, "per_lens": {"default": 50}, "agents": 5,
                            "angles_per_claim": 5, "batch_items": 30}


# -- advisor seats: init --settlement / --refuters and status ---------------------------

ADVISOR_SETTLEMENT = ("converge_seats:\n  r2: advisor\n"
                      "advisor_roles:\n  roles: [refuter, gap-hunter]\n  brief: Act only as r2.\n")
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


def test_bundled_init_prints_advisor_driver(tmp_path: Path) -> None:
    ledger = tmp_path / "ledgers"
    settlement = _settlement(tmp_path, ADVISOR_SETTLEMENT)
    lines = _seat_init(tmp_path, ledger, "--settlement", str(settlement)).stdout.splitlines()
    assert lines[1] == ("SEATS main=native_subagent finder=native_subagent r1=native_subagent "
                        "r2=advisor cutter=native_subagent")
    step = _one(lines, "DRIVER r2 step (one background step per turn): ")
    assert f"--body-file {ledger}/s1.r2.request.txt && " in step
    assert step.endswith(' receive --channel "$CHANNEL" --for asker --timeout 300')
    assert step.count(" receive ") == 1 and "while" not in step
    placeholders = _one(lines, "DRIVER r2 placeholders: ")
    assert "literal channel.py path and channel number" in placeholders
    assert '"$CHANNEL_SCRIPT"' in placeholders and '"$CHANNEL"' in placeholders
    then = _one(lines, "DRIVER r2 then: ")
    assert "5 receives in total, the one in the step included" in then
    assert "after the 5th receive" in then and "at most 5 times" not in then
    other = _one(lines, "DRIVER r2 other messages: ")
    assert "is a late reply" in other and "without counting it toward the 5" in other
    assert "any other kind is a protocol error: stop the slate blocked naming r2" in other
    check = _one(lines, "DRIVER r2 check: ")
    assert "WRITE-DENIED" in check and "never redo the turn with a native subagent" in check
    scope = _one(lines, "SCOPE: ")
    assert scope.startswith('SCOPE: write events only with: UV_CACHE_DIR="${TMPDIR:-/tmp}/converge-uv-cache" ')
    converge = Path(scope.split('converge-uv-cache" ', 1)[1].split(" ", 1)[0])
    assert converge == TASK.resolve()
    assert converge.is_file() and os.access(converge, os.X_OK)
    for fragment in (f"--dir {ledger} --as r2", "require_escalated",
                     'reply "WRITE-DENIED r2: <the error text>"',
                     "<attack|reply|verdict|file|rebut|accept|escalate|angle-na>"):
        assert fragment in scope, scope
    nxt = lines[-1]
    assert nxt.startswith("next: reclaim the advisor channel for r2 "), nxt
    assert "prints the channel.py path and the channel number" in nxt
    assert "keep the channel open after this slate" in nxt


def test_bundled_init_refuses_seat_mismatch(tmp_path: Path) -> None:
    ledger = tmp_path / "ledgers"
    settlement = _settlement(tmp_path, "converge_seats: {r2: native_subagent}\n"
                                       "advisor_roles: {roles: [refuter], brief: Act only as r2.}\n")
    lines = _seat_init(tmp_path, ledger, "--settlement", str(settlement), code=2).stderr.splitlines()
    assert lines[0] == "converge: settlement seats do not match its advisor roles:"
    assert any("set converge_seats.r2: advisor, or remove refuter" in line for line in lines)
    assert any(line.startswith("example: ") and line.endswith("--settlement <file>")
               for line in lines), lines
    assert lines[-1] == FIX_NEXT.format(path=settlement)
    error = json.loads(_seat_init(tmp_path, ledger, "--settlement", str(settlement), "--json",
                                  code=2).stderr)["error"]
    assert error["example"].endswith("--settlement <file>")
    assert error["next"] == FIX_NEXT.format(path=settlement)[len("next: "):]
    assert not (ledger / "s1.jsonl").exists()


def test_bundled_init_refuses_non_r2_advisor_seat(tmp_path: Path) -> None:
    ledger = tmp_path / "ledgers"
    settlement = _settlement(tmp_path, "converge_seats: {finder: advisor, r2: advisor}\n")
    lines = _seat_init(tmp_path, ledger, "--settlement", str(settlement), code=2).stderr.splitlines()
    assert lines[0] == "converge: invalid settlement seats:"
    assert any(line.startswith("  - converge_seats.finder: only r2 may be advisor")
               for line in lines), lines
    assert lines[-1] == FIX_NEXT.format(path=settlement)
    assert not (ledger / "s1.jsonl").exists()


def test_bundled_r2_advisor_without_roles_uses_defaults(tmp_path: Path) -> None:
    ledger = tmp_path / "ledgers"
    settlement = _settlement(tmp_path, "converge_seats: {r2: advisor}\n")
    lines = _seat_init(tmp_path, ledger, "--settlement", str(settlement)).stdout.splitlines()
    assert ("NOTE r2 is advisor with no advisor role in the settlement; it takes refuter, "
            "gap-hunter and the stock brief") in lines
    assert _one(lines, "USER_REQUEST: ").startswith(
        "USER_REQUEST: You are seat r2 (refuter, gap-hunter) on converge slate s1. "
        "Act only as this seat on this slate; do not extend the role.")
    init = json.loads((ledger / "s1.jsonl").read_text().splitlines()[0])
    assert init["advisor"]["roles"] == ["refuter", "gap-hunter"]


def test_bundled_refuters_one_notes_unseated_advisor(tmp_path: Path) -> None:
    ledger = tmp_path / "ledgers"
    settlement = _settlement(tmp_path, ADVISOR_SETTLEMENT)
    lines = _seat_init(tmp_path, ledger, "--settlement", str(settlement),
                       "--refuters", "1").stdout.splitlines()
    assert ("NOTE r2 is advisor in the settlement, but this slate has no r2; the advisor holds "
            "no seat on this slate") in lines
    assert not any(line.startswith(("DRIVER", "REQUEST")) for line in lines), lines
    init = json.loads((ledger / "s1.jsonl").read_text().splitlines()[0])
    assert "r2" not in init["seats"] and "advisor" not in init
    assert init["refuters"] == 1


def test_bundled_status_reprints_drivers(tmp_path: Path) -> None:
    ledger = tmp_path / "ledgers"
    settlement = _settlement(tmp_path, ADVISOR_SETTLEMENT)
    _seat_init(tmp_path, ledger, "--settlement", str(settlement))
    data = json.loads(_ok(tmp_path, "status", "s1", "--dir", str(ledger), "--json").stdout)
    assert data["seats"]["r2"] == "advisor"
    assert [d["seat"] for d in data["drivers"]] == ["r2"]
    assert data["drivers"][0]["step"].endswith("--timeout 300")
    head = _ok(tmp_path, "status", "s1", "--dir", str(ledger)).stdout.splitlines()[0]
    assert " advisor=r2" in head


def test_bundled_slate_without_seats_is_all_native(tmp_path: Path) -> None:
    ledger = tmp_path / "ledgers"
    _seat_init(tmp_path, ledger)
    init = json.loads((ledger / "s1.jsonl").read_text().splitlines()[0])
    assert "seats" not in init and "advisor" not in init
    data = json.loads(_ok(tmp_path, "status", "s1", "--dir", str(ledger), "--json").stdout)
    assert data["seats"] == {} and data["drivers"] == []
    head = _ok(tmp_path, "status", "s1", "--dir", str(ledger)).stdout.splitlines()[0]
    assert " advisor=-" in head
