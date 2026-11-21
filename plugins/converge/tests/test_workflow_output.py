from __future__ import annotations

import json
from pathlib import Path

from workflow_output_test_support import (
    ANGLES,
    BATCH_1,
    CUTTER,
    FILE_ARGS,
    FIND_ANGLES,
    FINDER,
    MAIN,
    PROGRAM,
    R1,
    R2,
    STEPS,
    Slate,
    _example,
    _ok,
    _seq,
)

# -- init, find, escalate, cut before ------------------------------------------------


def test_shared_init_with_shipped_angles_needs_find_coverage(tmp_path: Path) -> None:
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


def test_shared_angles_find_refuses_empty_results(tmp_path: Path) -> None:
    err = _ok(tmp_path, "angles", "--project-root", str(tmp_path), "--tag", "find", code=2).stderr
    assert "no find angles" in err
    assert "--angles <file>" in err


def test_shared_angles_find_uses_caller_and_config_files(tmp_path: Path) -> None:
    caller_angles = tmp_path / "caller-angles.yaml"
    caller_angles.write_text(FIND_ANGLES)
    caller = _ok(tmp_path, "angles", "--project-root", str(tmp_path), "--tag", "find",
                 "--angles", str(caller_angles))
    assert "find changed-contract" in caller.stdout

    config_angles = tmp_path / "config-angles.yaml"
    config_angles.write_text(FIND_ANGLES)
    config = tmp_path / "converge.yaml"
    config.write_text("angles: {files: [config-angles.yaml]}\n")
    configured = _ok(tmp_path, "angles", "--project-root", str(tmp_path), "--config", str(config),
                      "--tag", "find")
    assert "find changed-contract" in configured.stdout


def test_shared_init_refuses_the_removed_mode_flag(tmp_path: Path) -> None:
    slate = Slate(tmp_path)
    err = _ok(tmp_path, "init", "s1", "--dir", str(slate.dir), "--as", MAIN, "--mode", "full",
              "--angles", str(slate.angles), code=2).stderr
    assert "--mode" in err
    assert not (slate.dir / "s1.jsonl").exists()


def test_shared_find_commands_print_the_finder_step(tmp_path: Path) -> None:
    slate = Slate(tmp_path)
    slate.init()
    assert slate.file("c").stdout.splitlines() == ["FILED F001", slate.role_next(FINDER, structured=False)]
    out = slate.lines("find-run", "--as", FINDER, "--lens", "correctness",
                      "--angle", "changed-contract", "--tell", "t", "--searches", "s",
                      "--positive-control", "p", "--result", "F001")
    assert out == ["FIND-RUN seq=3 lens=correctness angle=changed-contract", slate.role_next(FINDER, structured=False)]
    out = slate.lines("angle-na", "--as", FINDER, "--phase", "find", "--angle", "failure-path",
                      "--lens", "correctness", "--reason", "no I/O")
    assert out[0] == "ANGLE-NA seq=4 phase=find angle=failure-path"


def test_shared_gap_hunt_files_after_find_coverage(tmp_path: Path) -> None:
    slate = Slate(tmp_path)
    slate.init(config=STEPS.replace("gap_hunt: false", "gap_hunt: true"))
    slate.file()
    gap = ("--origin", "gap-hunt")
    err = slate.lines("file", "--as", R2, "--lens", "correctness", "--angle", "changed-contract",
                      "--loc", "a.py:1", "--claim", "ticket asks for retries",
                      "--trigger", "caller retries", *FILE_ARGS, *gap, code=2)
    assert "  - file: gap-hunt claims are filed after find coverage is complete" in err
    assert err[-1] == (slate.role_next(R2, structured=False))
    slate.cover()
    out = slate.lines("file", "--as", R2, "--lens", "correctness", "--angle", "changed-contract",
                      "--loc", "a.py:1", "--claim", "ticket asks for retries",
                      "--trigger", "caller retries", *FILE_ARGS, *gap)
    assert out[0] == "FILED F002"


def test_shared_escalate_and_cut_before_print_the_plan_step(tmp_path: Path) -> None:
    slate = Slate(tmp_path)
    slate.init()
    slate.file()
    slate.file(claim="another supported claim")
    slate.cover()
    out = slate.escalate("F001")
    assert out[1] == slate.role_next(FINDER, structured=False)
    assert "file: claims are filed before the first escalate, cut or attack event" in slate.file(
        code=2).stderr
    out = slate.escalate("F002")
    assert out[0].endswith(" F002 wider=no")
    assert out[1] == slate.role_next(FINDER, structured=False)
    out = slate.cut("F001", "before")
    assert out == [f"CUT seq={_seq(out)} F001 when=before round=1",
                   (slate.role_next(CUTTER, structured=False))]
    out = slate.lines("rebut", "--as", FINDER, "--claim", "F001", "--when", "before",
                      "--evidence", "prod shows every call")
    assert out == [f"REBUT seq={_seq(out)} F001 when=before",
                   slate.role_next(FINDER, structured=False)]


def test_shared_cut_round_waits_for_the_finder_answer(tmp_path: Path) -> None:
    slate = Slate(tmp_path)
    slate.init()
    slate.file()
    slate.cover()
    slate.escalate("F001")
    slate.cut("F001", "before")
    err = slate.cut("F001", "before", rnd=2, code=2)
    assert ("  - cut: F001 before round 1 awaits its finder; the finder must accept or rebut "
            "it first") in err
    assert err[-1] == slate.role_next(CUTTER, structured=False)
    slate.ok("rebut", "--as", FINDER, "--claim", "F001", "--when", "before",
             "--evidence", "the retry path is guarded")
    out = slate.cut("F001", "before", rnd=2)
    assert out[0] == f"CUT seq={_seq(out)} F001 when=before round=2"


def test_shared_cut_before_leads_to_the_attack(tmp_path: Path) -> None:
    slate = Slate(tmp_path)
    slate.init()
    slate.file()
    slate.cover()
    slate.escalate("F001")
    slate.cut("F001", "before")
    out = slate.accept("F001", "before")
    assert out == [f"ACCEPT seq={_seq(out)} F001 when=before round=1",
                   slate.role_next(FINDER, structured=False)]


# -- attack, reply, verdict -----------------------------------------------------------


def test_shared_attack_reply_verdict_walk_the_dispute(tmp_path: Path) -> None:
    slate = Slate(tmp_path)
    slate.to_attack()
    out = slate.check(BATCH_1[0], outcome="refuted")
    assert out == [f"ATTACK seq={_seq(out)} F001 batch=1 angle={BATCH_1[0]} outcome=refuted",
                   slate.role_next(R1, structured=False)]
    for angle in BATCH_1[1:4]:
        slate.check(angle)
    out = slate.lines("angle-na", "--as", R1, "--phase", "attack", "--claim", "F001",
                      "--angle", BATCH_1[4], "--reason", "no default in the diff")
    assert out[1] == slate.role_next(R1, structured=False)
    out = slate.lines("reply", "--as", FINDER, "--claim", "F001", "--batch", "1",
                      "--stance", "rebut", "--evidence", "the caller in b.py:4 passes None",
                      "--text", "None from b.py:4 crashes the parser")
    assert out == [f"REPLY seq={_seq(out)} F001 batch=1 stance=rebut",
                   slate.role_next(FINDER, structured=False)]
    out = slate.lines("verdict", "--as", R1, "--claim", "F001", "--batch", "1",
                      "--verdict", "agree")
    assert out == [f"VERDICT seq={_seq(out)} F001 batch=1 verdict=agree",
                   slate.role_next(R1, structured=False)]
    out = slate.check("retry timing", "--last", agent=R2, batch="fresh-eye")
    assert out == [f"CLEAN seq={_seq(out)} F001",
                   slate.role_next(R2, structured=True)]
    assert slate.status()["by_id"]["F001"]["claim"] == "None from b.py:4 crashes the parser"


def test_shared_attack_refusals_name_the_role_and_the_next_step(tmp_path: Path) -> None:
    slate = Slate(tmp_path)
    slate.to_attack()
    err = slate.check(BATCH_1[0], agent=FINDER, code=2)
    assert err[0].startswith("example: ") and " clean <slate> " in err[0]
    assert any("finder filed F001 and may not attack it" in line for line in err)
    assert err[-1] == slate.role_next(FINDER, structured=True)
    err = slate.check(BATCH_1[0], agent=MAIN, code=2)
    assert any("orch wrote init; the orchestrator never writes attack" in line for line in err)
    err = slate.check(BATCH_1[0], agent=CUTTER, code=2)
    assert any("cutter cut F001; refuters and cutters are disjoint" in line for line in err)
    err = slate.check(BATCH_1[0], batch="2", code=2)
    assert any("F001's open batch is 1 (open); got batch 2" in line for line in err)


def test_shared_fresh_eye_reuse_refusal_explains_angle_choice(tmp_path: Path) -> None:
    slate = Slate(tmp_path)
    slate.to_attack()
    slate.batch_1()
    slate.check("retry timing", agent=R2, batch="fresh-eye")
    err = slate.check("retry timing", agent=R2, batch="fresh-eye", code=2)
    assert any((
        "attack: angle 'retry timing' was already used on F001; choose a new angle name not listed in `used`, "
        "including names outside the fixed list; "
        "the fixed list is not a menu for this batch") in line for line in err)


def test_shared_fresh_eye_plan_explains_angle_choice(tmp_path: Path) -> None:
    slate = Slate(tmp_path)
    slate.to_attack()
    slate.batch_1()
    [[row]] = slate.status()["plan"]
    assert row["angles"] == []
    assert row["rule"] == (
        "choose a new angle name not listed in `used`, including names outside the fixed list; "
        "the fixed list is not a menu for this batch. "
        "For example, use `retry after timeout`.")


def test_shared_fresh_eye_closes_at_cap_twenty_without_last(tmp_path: Path) -> None:
    slate = Slate(tmp_path)
    slate.to_attack(config=STEPS + "caps: {angles_per_claim: 20}\n")
    slate.batch_1()
    for n in range(1, 21):
        slate.check(f"angle {n}", agent=R2, batch="fresh-eye")
    status = slate.status()
    assert status["phase"] == "cut-after"
    assert status["by_id"]["F001"]["fresh_eye"] == [f"angle {n}" for n in range(1, 21)]


def test_shared_angle_na_refusal_shows_the_form_for_its_phase(tmp_path: Path) -> None:
    slate = Slate(tmp_path)
    slate.to_attack()
    err = slate.lines("angle-na", "--as", FINDER, "--phase", "find", "--angle", "failure-path",
                      "--reason", "no I/O", code=2)
    assert _example(err).startswith(f"example: {PROGRAM} angle-na ")
    assert "--phase find --lens" in _example(err)
    assert err[-1] == slate.role_next(FINDER, structured=False)
    err = slate.lines("angle-na", "--as", R1, "--phase", "attack", "--angle", BATCH_1[0],
                      "--reason", "no boundary in a constant", code=2)
    assert _example(err).startswith(f"example: {PROGRAM} angle-na ")
    assert "--phase attack --claim" in _example(err)
    assert err[-1] == slate.role_next(R1, structured=False)


def test_shared_angle_na_usage_refusal_follows_the_phase(tmp_path: Path) -> None:
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


def test_shared_decline_kills_the_claim(tmp_path: Path) -> None:
    slate = Slate(tmp_path)
    slate.to_attack()
    slate.batch_1(refuted=(BATCH_1[0],))
    out = slate.lines("reply", "--as", FINDER, "--claim", "F001", "--batch", "1",
                      "--stance", "decline")
    assert out == [f"REPLY seq={_seq(out)} F001 batch=1 stance=decline",
                   slate.role_next(FINDER, structured=False)]
    claim = slate.status()["by_id"]["F001"]
    assert (claim["status"], claim["cut"]) == ("killed", "no")


# -- cut after, cutoff, render, gate, converged -----------------------------------------


def test_shared_cutoff_gate_render_converged(tmp_path: Path) -> None:
    slate = Slate(tmp_path)
    slate.to_cut_after()
    slate.cut("F001", "after")
    cutoff_step = "next: " + slate.cmd("cutoff s1 --dir {dir}")
    err = slate.lines("cutoff", code=2)
    assert err[0].startswith("example: ") and " cutoff <slate> " in err[0]
    assert err[-3:] == ["converge: refused:", "  - F001 is open in cut-after",
                        f"next: cut-after: finder accept F001; plan: {slate.plan()}"]
    assert slate.lines("gate", code=1) == [
        "GATE fail s1", "F001 is open in cut-after",
        f"no current cutoff (run `{PROGRAM} cutoff` after the last state change)",
        f"next: cut-after: finder accept F001; plan: {slate.plan()}"]
    out = slate.accept("F001", "after")
    assert out == [f"ACCEPT seq={_seq(out)} F001 when=after round=1", slate.role_next(FINDER, structured=False)]
    assert slate.lines("converged", code=1) == ["OPEN phase=cutoff claims=0", cutoff_step]
    out = slate.lines("cutoff")
    seq = _seq(out)
    assert out == [f"CUTOFF seq={seq} fix-now=0 fixed=0 findings=1 follow-up=1 killed=0",
                   "F001 finding status=survived cut=no rank=1 reason=report_if[0]",
                   "F002 follow-up status=unverified cut=yes rank=2 reason=unverified",
                   "next: " + slate.cmd("render s1 --dir {dir}")]
    render = slate.ok("render").stdout
    assert "findings=1 follow-up=1 killed=0 converged=yes" in render
    assert slate.lines("gate") == [f"GATE ok s1 cutoff_seq={seq}",
                                   "next: " + slate.cmd("converged s1 --dir {dir}")]
    assert slate.lines("converged") == ["CONVERGED", "next: end the slate with outcome converged"]


def test_shared_render_choices_hold_findings_only(tmp_path: Path) -> None:
    """F001 a finding and F002 unverified, each rated redesign with a choice."""
    slate = Slate(tmp_path)
    slate.init()
    slate.file("None crashes the parser")
    slate.file("log line typo")
    slate.cover()
    for claim in ("F001", "F002"):
        slate.escalate(claim)
    slate.cut("F001", "before", extra=("--choice", "split or patch"))
    slate.accept("F001", "before")
    slate.cut("F002", "before", "cosmetic", extra=("--choice", "drop or keep"))
    slate.accept("F002", "before")
    slate.batch_1()
    slate.check("retry timing", "--last", agent=R2, batch="fresh-eye")
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


def test_shared_converged_lists_the_disputed_findings(tmp_path: Path) -> None:
    slate = Slate(tmp_path)
    slate.to_attack()
    slate.batch_1(refuted=(BATCH_1[0],))
    slate.ok("reply", "--as", FINDER, "--claim", "F001", "--batch", "1", "--stance", "rebut",
             "--evidence", "b.py:4 passes None")
    slate.ok("verdict", "--as", R1, "--claim", "F001", "--batch", "1",
             "--verdict", "disagree", "--evidence", "b.py:4 is dead code")
    slate.ok("reply", "--as", FINDER, "--claim", "F001", "--batch", "1", "--stance", "rebut",
             "--evidence", "the router reaches b.py:4")
    slate.check("retry timing", "--last", agent=R2, batch="fresh-eye")
    slate.cut("F001", "after", "security")
    slate.accept("F001", "after")
    slate.ok("cutoff")
    assert slate.lines("converged", code=1) == [
        "OPEN phase=done claims=1", "F001 disputed cut=no",
        "next: end the slate with outcome unconverged; disputed findings: F001"]
    assert slate.ok("gate").stdout.startswith("GATE ok s1 ")


# -- budget and reserved ids -------------------------------------------------------------


def test_shared_converge_refuses_a_sixth_agent(tmp_path: Path) -> None:
    slate = Slate(tmp_path)
    slate.to_cut_after()
    path = slate.dir / "s1.jsonl"
    before = path.read_bytes()
    err = slate.cut("F001", "after", agent="cutter-2", code=2)
    assert any("agent budget: cutter-2 would be agent 6 on this slate; caps.agents is 5" in line
               for line in err), err
    assert path.read_bytes() == before


def test_shared_converge_reserves_the_converge_agent_id(tmp_path: Path) -> None:
    slate = Slate(tmp_path)
    slate.init()
    err = slate.file("z", "converge", code=2).stderr
    assert "agent id 'converge' is reserved for computed cutoff events" in err


def test_shared_status_prints_claims_plan_and_next(tmp_path: Path) -> None:
    slate = Slate(tmp_path)
    slate.to_attack()
    slate.check(BATCH_1[0])
    out = slate.lines("status")
    assert out[0] == ("SLATE s1 lenses=correctness phase=attack cutoff=none claims=2 "
                      "difficulty_basis=artifact agents=4/5 advisor=-")
    assert out[-2] == f"PLAN 1 F001 attack r1 batch=1 angles={','.join(BATCH_1[1:])}"
    assert out[-1] == f"next: attack: r1 attack F001 batch 1; plan: {slate.plan()}"
    data = slate.status()
    assert data["difficulty_basis"] == "artifact"
    assert all(row["artifact_patch_eligible"] is False for row in data["claims"])
    assert data["caps"] == {"cut_rounds": 5, "per_lens": {"default": 50}, "agents": 5,
                            "angles_per_claim": 5, "batch_items": 30}
