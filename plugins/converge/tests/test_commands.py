"""Every slate command through the CLI, with its printed lines and its `next:` step."""
from __future__ import annotations

import json
import shlex
from typing import Any

from conftest import (
    BATCH_1,
    CHOICE,
    CUT_EVIDENCE,
    CUTTER,
    DISABLED,
    FILE_ARGS,
    FILE_EVIDENCE,
    FINDER,
    MAIN,
    R1,
    R2,
    Converge,
)

TASK = {"steps": {"cut": "both", "gap_hunt": False, "escalate": True},
        "angles": {"disable": DISABLED}}


def _cmd(cv: Converge, rest: str) -> str:
    return f"converge {rest.format(dir=shlex.quote(str(cv.dir)))}"


def _plan(cv: Converge) -> str:
    return _cmd(cv, "status s1 --dir {dir} --json")


def _lines(cv: Converge, *args: str, code: int = 0) -> list[str]:
    return cv.ok(*args, code=code).stdout.splitlines()


def _attack(cv: Converge, angle: str, *extra: str, agent: str = R1, batch: Any = 1,
            outcome: str = "clean", code: int = 0) -> Any:
    return cv.attack_cli("F001", angle, *extra, agent=agent, batch=batch, outcome=outcome,
                         code=code)


def _cut(cv: Converge, claim: str, when: str, impact: str) -> list[str]:
    after = ("--difficulty", "cross-cutting", "--choice", CHOICE) if when == "after" else ()
    return _lines(cv, "cut", "s1", "--as", CUTTER, "--claim", claim, "--when", when,
                  "--round", "1", "--impact", impact, "--size", "one", "--reach", "normal",
                  *after, *CUT_EVIDENCE)


def _accept(cv: Converge, claim: str, when: str) -> list[str]:
    return _lines(cv, "accept", "s1", "--as", FINDER, "--claim", claim, "--when", when,
                  "--round", "1")


def _seq(lines: list[str]) -> str:
    return lines[0].split()[1].removeprefix("seq=")


def _to_attack(cv: Converge) -> None:
    """Two claims, find coverage, escalate, and cut-before: F001 kept, F002 unverified."""
    cv.init(config=TASK)
    cv.file(claim="None crashes the parser")
    cv.file(claim="log line typo")
    cv.cover()
    for claim in ("F001", "F002"):
        cv.ok("escalate", "s1", "--as", FINDER, "--claim", claim)
    _cut(cv, "F001", "before", "wrong-output")
    _accept(cv, "F001", "before")
    _cut(cv, "F002", "before", "cosmetic")
    _accept(cv, "F002", "before")


# -- find, escalate, cut before ----------------------------------------------------


def test_find_commands_print_the_finder_step(cv: Converge) -> None:
    cv.init(config=TASK)
    find = "next: continue the finder with the missing angles, then " + _cmd(
        cv, "coverage s1 --dir {dir}")
    out = _lines(cv, "file", "s1", "--as", FINDER, "--lens", "correctness",
                 "--angle", "changed-contract", "--origin", "lens", "--loc", "a.py:1",
                 "--claim", "c", "--trigger", "t", *FILE_ARGS)
    assert out == ["FILED F001", find]
    out = _lines(cv, "find-run", "s1", "--as", FINDER, "--lens", "correctness",
                 "--angle", "changed-contract", "--tell", "t", "--searches", "s",
                 "--positive-control", "p", "--result", "F001")
    assert out == ["FIND-RUN seq=3 lens=correctness angle=changed-contract", find]
    out = _lines(cv, "angle-na", "s1", "--as", FINDER, "--phase", "find",
                 "--angle", "failure-path", "--lens", "correctness", "--reason", "no I/O")
    assert out == ["ANGLE-NA seq=4 phase=find angle=failure-path", find]


def test_escalate_and_cut_before_print_the_plan_step(cv: Converge) -> None:
    cv.init(config=TASK)
    cv.file()
    cv.file()
    cv.cover()
    out = _lines(cv, "escalate", "s1", "--as", FINDER, "--claim", "F001")
    assert out[1] == f"next: escalate: finder escalate F002; plan: {_plan(cv)}"
    out = _lines(cv, "escalate", "s1", "--as", FINDER, "--claim", "F002")
    assert out[0].endswith(" F002 wider=no")
    assert out[1] == f"next: cut-before: cutter cut-before F001, F002; plan: {_plan(cv)}"
    out = _cut(cv, "F001", "before", "wrong-output")
    assert out == [f"CUT seq={_seq(out)} F001 when=before round=1",
                   (f"next: cut-before: finder accept F001; cutter cut-before F002; "
                   f"plan: {_plan(cv)}")]
    out = _lines(cv, "rebut", "s1", "--as", FINDER, "--claim", "F001", "--when", "before",
                 "--evidence", "prod shows every call")
    assert out == [f"REBUT seq={_seq(out)} F001 when=before",
                   f"next: cut-before: cutter cut-before F001, F002; plan: {_plan(cv)}"]


def test_cut_before_leads_to_the_attack(cv: Converge) -> None:
    cv.init(config=TASK)
    cv.file()
    cv.cover()
    cv.ok("escalate", "s1", "--as", FINDER, "--claim", "F001")
    _cut(cv, "F001", "before", "wrong-output")
    out = _accept(cv, "F001", "before")
    assert out == [f"ACCEPT seq={_seq(out)} F001 when=before round=1",
                   f"next: attack: r1 attack F001 batch 1; plan: {_plan(cv)}"]


# -- attack, reply, verdict ---------------------------------------------------------


def test_attack_reply_verdict_walk_the_dispute(cv: Converge) -> None:
    _to_attack(cv)
    out = _attack(cv, BATCH_1[0], outcome="refuted").stdout.splitlines()
    assert out == [f"ATTACK seq={_seq(out)} F001 batch=1 angle={BATCH_1[0]} outcome=refuted",
                   f"next: attack: r1 attack F001 batch 1; plan: {_plan(cv)}"]
    for angle in BATCH_1[1:4]:
        _attack(cv, angle)
    out = _lines(cv, "angle-na", "s1", "--as", R1, "--phase", "attack", "--claim", "F001",
                 "--angle", BATCH_1[4], "--reason", "no default in the diff")
    assert out[1] == f"next: attack: finder reply F001 batch 1; plan: {_plan(cv)}"
    out = _lines(cv, "reply", "s1", "--as", FINDER, "--claim", "F001", "--batch", "1",
                 "--stance", "rebut", "--evidence", "the caller in b.py:4 passes None",
                 "--text", "None from b.py:4 crashes the parser")
    assert out == [f"REPLY seq={_seq(out)} F001 batch=1 stance=rebut",
                   f"next: attack: r1 verdict F001 batch 1; plan: {_plan(cv)}"]
    out = _lines(cv, "verdict", "s1", "--as", R1, "--claim", "F001", "--batch", "1",
                 "--verdict", "agree")
    assert out == [f"VERDICT seq={_seq(out)} F001 batch=1 verdict=agree",
                   f"next: attack: r2 attack F001 batch fresh-eye; plan: {_plan(cv)}"]
    out = _attack(cv, "retry timing", "--last", agent=R2, batch="fresh-eye").stdout.splitlines()
    assert out == [(f"ATTACK seq={_seq(out)} F001 batch=fresh-eye angle=retry timing "
                   f"outcome=clean"),
                   f"next: cut-after: cutter cut-after F001; plan: {_plan(cv)}"]
    assert cv.status()["by_id"]["F001"]["claim"] == "None from b.py:4 crashes the parser"


def test_attack_reply_verdict_refusals_print_the_next_step(cv: Converge) -> None:
    _to_attack(cv)
    err = _attack(cv, BATCH_1[0], agent=FINDER, code=2).stderr.splitlines()
    assert err[:2] == ["converge: refused:", "  - attack: finder filed F001 and may not attack it"]
    assert err[2] == f"example: converge {_example('attack')}"
    assert err[-1] == f"next: attack: r1 attack F001 batch 1; plan: {_plan(cv)}"
    err = _attack(cv, BATCH_1[0], batch=2, code=2).stderr
    assert "attack: F001's open batch is 1 (open); got batch 2" in err
    for angle in BATCH_1:
        _attack(cv, angle, outcome="refuted" if angle == BATCH_1[0] else "clean")
    err = cv.ok("verdict", "s1", "--as", R1, "--claim", "F001", "--batch", "1",
                "--verdict", "agree", code=2).stderr.splitlines()
    assert ("  - verdict: F001 batch 1 is awaiting-reply-1; verdict needs awaiting-verdict"
            in err)
    assert err[-1] == f"next: attack: finder reply F001 batch 1; plan: {_plan(cv)}"
    err = cv.ok("reply", "s1", "--as", FINDER, "--claim", "F001", "--batch", "1",
                "--stance", "rebut", code=2).stderr
    assert "`evidence` must be a non-empty string" in err
    err = cv.ok("reply", "s1", "--as", R1, "--claim", "F001", "--batch", "1",
                "--stance", "decline", code=2).stderr
    assert "reply: only F001's finder finder may reply" in err
    cv.ok("reply", "s1", "--as", FINDER, "--claim", "F001", "--batch", "1",
          "--stance", "rebut", "--evidence", "b.py:4 passes None")
    err = cv.ok("verdict", "s1", "--as", R1, "--claim", "F001", "--batch", "1",
                "--verdict", "disagree", code=2).stderr
    assert "verdict: disagree needs `evidence`" in err


def test_decline_kills_the_claim(cv: Converge) -> None:
    _to_attack(cv)
    for angle in BATCH_1:
        _attack(cv, angle, outcome="refuted" if angle == BATCH_1[0] else "clean")
    out = _lines(cv, "reply", "s1", "--as", FINDER, "--claim", "F001", "--batch", "1",
                 "--stance", "decline")
    assert out == [f"REPLY seq={_seq(out)} F001 batch=1 stance=decline",
                   "next: " + _cmd(cv, "cutoff s1 --dir {dir}")]
    claim = cv.status()["by_id"]["F001"]
    assert (claim["status"], claim["cut"], claim["batch"], claim["batch_state"]) == (
        "killed", "no", None, None)


# -- status ------------------------------------------------------------------------


def test_status_emits_trigger_evidence_tier(cv: Converge) -> None:
    cv.init(config=TASK)
    cv.file(claim="None crashes the parser", evidence="pytest -k parse: TypeError at a.py:10",
            tier="reproduced")
    cv.file(claim="log line typo", tier="inferred")
    claims = cv.status()["by_id"]
    assert {key: claims["F001"][key] for key in ("loc", "trigger", "evidence", "tier")} == {
        "loc": "src/a.py:10", "trigger": "caller passes None",
        "evidence": "pytest -k parse: TypeError at a.py:10", "tier": "reproduced"}
    assert (claims["F002"]["evidence"], claims["F002"]["tier"]) == (FILE_EVIDENCE, "inferred")
    out = _lines(cv, "status", "s1")
    assert " tier=reproduced " in out[1] and out[1].startswith("F001 ")
    assert " tier=inferred " in out[2] and out[2].startswith("F002 ")
    rendered = json.loads(cv.ok("render", "s1", "--json").stdout)
    assert rendered["claims"] == [
        {"id": "F001", "trigger": "caller passes None",
         "evidence": "pytest -k parse: TypeError at a.py:10", "tier": "reproduced"},
        {"id": "F002", "trigger": "caller passes None", "evidence": FILE_EVIDENCE,
         "tier": "inferred"}]


def test_status_prints_claims_plan_and_next(cv: Converge) -> None:
    _to_attack(cv)
    _attack(cv, BATCH_1[0])
    out = _lines(cv, "status", "s1")
    assert out[0] == ("SLATE s1 lenses=correctness,security phase=attack cutoff=none claims=2 "
                      "agents=4/5 advisor=-")
    assert out[1:] == [
        (f"F001 status=survived cut=no tier=traced batch=1 batch_state=open escalated=yes "
        f"fixed_remaining={','.join(BATCH_1[1:])}"),
        ("F002 status=unverified cut=yes tier=traced batch=- batch_state=- escalated=yes "
        f"fixed_remaining={','.join(BATCH_1)}"),
        "ADHOC -",
        f"PLAN 1 F001 attack r1 batch=1 angles={','.join(BATCH_1[1:])}",
        f"next: attack: r1 attack F001 batch 1; plan: {_plan(cv)}"]
    data = cv.status()
    assert data["phase"] == "attack"
    assert data["steps"] == TASK["steps"]
    assert data["caps"] == {"cut_rounds": 5, "per_lens": {"default": 50}, "agents": 5,
                            "angles_per_claim": 5, "batch_items": 30}
    assert data["plan"] == [[{"claim": "F001", "action": "attack", "agent_role": "r1",
                              "batch": 1, "angles": list(BATCH_1[1:])}]]
    assert {key: data["by_id"]["F001"][key]
            for key in ("status", "cut", "batch", "batch_state", "fixed_remaining")} == {
        "status": "survived", "cut": "no", "batch": 1, "batch_state": "open",
        "fixed_remaining": list(BATCH_1[1:])}
    assert data["adhoc_angles"] == []
    assert data["by_id"]["F002"]["status"] == "unverified"
    assert data["next"] == f"attack: r1 attack F001 batch 1; plan: {_plan(cv)}"


def test_status_prints_phase_cutoff_when_no_plan_row_is_left(cv: Converge) -> None:
    cv.ready(cut="none")
    cv.clean()
    out = _lines(cv, "status", "s1")
    assert " phase=cutoff " in out[0]
    assert not [line for line in out if line.startswith("PLAN")]
    assert out[-1] == "next: " + _cmd(cv, "cutoff s1 --dir {dir}")
    data = cv.status()
    assert (data["phase"], data["plan"]) == ("cutoff", [])


def test_status_names_the_gap_hunt_until_the_first_escalate(cv: Converge) -> None:
    cv.init(config={**TASK, "steps": {"cut": "both", "gap_hunt": True, "escalate": True}})
    cv.file()
    cv.cover()
    gap = _cmd(cv, "file s1 --dir {dir} --as r2 --origin gap-hunt")
    assert _lines(cv, "status", "s1")[-1] == (
        f"next: gap hunt: r2 files the claims the lenses missed ({gap} ...) before the first "
        f"escalate, cut or attack; then escalate: finder escalate F001; plan: {_plan(cv)}")
    cv.ok("escalate", "s1", "--as", FINDER, "--claim", "F001")
    assert _lines(cv, "status", "s1")[-1] == (
        f"next: cut-before: cutter cut-before F001; plan: {_plan(cv)}")


def test_gap_hunt_files_only_between_coverage_and_the_first_escalate(cv: Converge) -> None:
    cv.init(config={**TASK, "steps": {"cut": "both", "gap_hunt": True, "escalate": True}})
    cv.file()
    err = cv.file(agent=R2, origin="gap-hunt", claim="ticket asks for retries", code=2)
    assert "file: gap-hunt claims are filed after find coverage is complete" in err
    assert err.splitlines()[-1] == (
        "next: continue the finder with the missing angles, then "
        + _cmd(cv, "coverage s1 --dir {dir}"))
    cv.cover()
    cv.ok("escalate", "s1", "--as", FINDER, "--claim", "F001")
    err = cv.file(agent=R2, origin="gap-hunt", claim="ticket asks for retries", code=2)
    assert "file: claims are filed before the first escalate, cut or attack event" in err
    assert err.splitlines()[-1] == f"next: cut-before: cutter cut-before F001; plan: {_plan(cv)}"


def test_one_refuter_slate_has_no_gap_hunt(cv: Converge) -> None:
    cv.init("s1", "correctness,security", MAIN, "--refuters", "1",
            config={**TASK, "steps": {"cut": "both", "gap_hunt": True, "escalate": True}})
    cv.file()
    cv.cover()
    assert _lines(cv, "status", "s1")[-1] == (
        f"next: escalate: finder escalate F001; plan: {_plan(cv)}")
    assert "a one-refuter slate has no gap hunt" in cv.file(
        agent=R2, origin="gap-hunt", claim="ticket asks for retries", code=2)


# -- cut after, cutoff, render, gate, converged -------------------------------------


def _to_cutoff(cv: Converge) -> None:
    _to_attack(cv)
    for angle in BATCH_1:
        _attack(cv, angle)
    _attack(cv, "retry timing", "--last", agent=R2, batch="fresh-eye")
    _cut(cv, "F001", "after", "wrong-output")


def test_cut_after_accept_names_the_cutoff(cv: Converge) -> None:
    _to_cutoff(cv)
    out = _accept(cv, "F001", "after")
    assert out == [f"ACCEPT seq={_seq(out)} F001 when=after round=1",
                   "next: " + _cmd(cv, "cutoff s1 --dir {dir}")]


def test_cutoff_gate_render_converged(cv: Converge) -> None:
    _to_cutoff(cv)
    cutoff_step = "next: " + _cmd(cv, "cutoff s1 --dir {dir}")
    err = cv.ok("cutoff", "s1", code=2).stderr.splitlines()
    assert err[:2] == ["converge: refused:", "  - F001 is open in cut-after"]
    assert err[-1] == f"next: cut-after: finder accept F001; plan: {_plan(cv)}"
    out = _lines(cv, "gate", "s1", code=1)
    assert out == ["GATE fail s1", "F001 is open in cut-after",
                   "no current cutoff (run `converge cutoff` after the last state change)",
                   f"next: cut-after: finder accept F001; plan: {_plan(cv)}"]
    _accept(cv, "F001", "after")
    assert _lines(cv, "converged", "s1", code=1) == ["OPEN phase=cutoff claims=0", cutoff_step]
    assert _lines(cv, "gate", "s1", code=1) == [
        "GATE fail s1", "no current cutoff (run `converge cutoff` after the last state change)",
        cutoff_step]
    out = _lines(cv, "cutoff", "s1")
    seq = out[0].split()[1].removeprefix("seq=")
    assert out == [f"CUTOFF seq={seq} fix-now=0 fixed=0 findings=1 follow-up=1 killed=0",
                   "F001 finding status=survived cut=no rank=1 reason=report_if[0]",
                   "F002 follow-up status=unverified cut=yes rank=2 reason=unverified",
                   "next: " + _cmd(cv, "render s1 --dir {dir}")]
    assert _lines(cv, "cutoff", "s1") == out
    render = cv.ok("render", "s1").stdout
    assert "findings=1 follow-up=1 killed=0 converged=yes" in render
    assert _lines(cv, "gate", "s1") == [f"GATE ok s1 cutoff_seq={seq}",
                                        "next: " + _cmd(cv, "converged s1 --dir {dir}")]
    assert _lines(cv, "status", "s1")[-1] == "next: " + _cmd(cv, "render s1 --dir {dir}")
    assert _lines(cv, "converged", "s1") == ["CONVERGED",
                                             "next: end the slate with outcome converged"]


def test_converged_lists_the_disputed_findings(cv: Converge) -> None:
    cv.ready(cut="after")
    cv.batch_1(refuted=(BATCH_1[0],))
    cv.ok("reply", "s1", "--as", FINDER, "--claim", "F001", "--batch", "1", "--stance", "rebut",
          "--evidence", "b.py:4 passes None")
    cv.ok("verdict", "s1", "--as", R1, "--claim", "F001", "--batch", "1",
          "--verdict", "disagree", "--evidence", "b.py:4 is dead code")
    out = _lines(cv, "reply", "s1", "--as", FINDER, "--claim", "F001", "--batch", "1",
                 "--stance", "rebut", "--evidence", "the router reaches b.py:4")
    assert out[1] == f"next: attack: r2 attack F001 batch fresh-eye; plan: {_plan(cv)}"
    assert _lines(cv, "converged", "s1", code=1) == [
        "OPEN phase=attack claims=1", "F001 open in attack",
        f"next: attack: r2 attack F001 batch fresh-eye; plan: {_plan(cv)}"]
    cv.fresh_eye()
    cv.rate(impact="security")
    cv.ok("cutoff", "s1")
    assert _lines(cv, "converged", "s1", code=1) == [
        "OPEN phase=done claims=1", "F001 disputed cut=no",
        "next: end the slate with outcome unconverged; disputed findings: F001"]
    assert cv("gate", "s1", "--dir", str(cv.dir)).stdout.startswith("GATE ok s1 ")


def test_examples_and_frequent_list_the_attack_commands() -> None:
    from converge import cli

    for name in ("attack", "reply", "verdict"):
        assert name in cli.EXAMPLES and name in cli.FREQUENT


def _example(name: str) -> str:
    from converge import cli

    return cli.EXAMPLES[name]


def test_init_prints_its_head(cv: Converge) -> None:
    out = _lines(cv, "init", "s1", "--as", MAIN, "--lenses", "correctness",
                 "--angles", str(cv.angles), "--project-root", str(cv.project))
    assert out[0].startswith("INIT s1 lenses=correctness angles=")
    assert out[0].endswith(f"path={cv.path()}")
