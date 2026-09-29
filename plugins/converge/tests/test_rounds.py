"""Refute rounds: unused angles, ≥2 per round, sequencing, cap, downgrade and dependents."""
from __future__ import annotations

from conftest import Converge

ATTACK = ("cited-but-unread", "point-in-time", "provenance", "reachability", "absent-vs-default",
          "downstream-consumer", "inverse-reading", "carve-out", "boundary", "dependents",
          "positive-control", "inherited-bounds", "guarded-elsewhere", "deliberate", "real-referent")


def test_unused_angle_rule(cv: Converge) -> None:
    cv.init()
    cv.file()
    cv.refute("F001", 1, "reachability", "r1")
    err = cv.refute("F001", 1, "reachability", "r2", code=2).stderr
    assert "angle 'reachability' was already used on F001" in err
    cv.refute("F001", 1, "boundary", "r2")
    assert "already used" in cv.refute("F001", 2, "boundary", "r3", code=2).stderr


def test_unknown_or_wrong_tag_angle_rejected(cv: Converge) -> None:
    cv.init()
    cv.file()
    assert "unknown attack angle 'changed-contract'" in cv.refute("F001", 1, "changed-contract", "r1", code=2).stderr
    assert "unknown attack angle 'precedent'" in cv.refute("F001", 1, "precedent", "r1", code=2).stderr


def test_round_needs_two_refutes_before_the_next(cv: Converge) -> None:
    cv.init()
    cv.file()
    assert "round must be 1" in cv.refute("F001", 2, "boundary", "r1", code=2).stderr
    cv.refute("F001", 1, "boundary", "r1")
    assert cv.status()["by_id"]["F001"]["refute"] == "open"
    err = cv.refute("F001", 2, "reachability", "r2", code=2).stderr
    assert "round 1 of F001 has 1 refute event(s); a round needs ≥2" in err
    cv.refute("F001", 1, "reachability", "r2")
    assert cv.status()["by_id"]["F001"]["refute"] == "converged"
    assert "next round is 2" in cv.refute("F001", 3, "provenance", "r3", code=2).stderr
    cv.refute("F001", 2, "provenance", "r3")
    assert "rounds never decrease" in cv.refute("F001", 1, "carve-out", "r4", code=2).stderr


def test_inconclusive_state(cv: Converge) -> None:
    cv.init()
    cv.file()
    cv.refute("F001", 1, "boundary", "r1", "inconclusive")
    cv.refute("F001", 1, "reachability", "r2")
    assert cv.status()["by_id"]["F001"]["refute"] == "inconclusive"


def test_downgrade_narrows_text_and_needs_another_round(cv: Converge) -> None:
    cv.init()
    cv.file(claim="always breaks")
    cv.refute("F001", 1, "boundary", "r1", "downgraded", "--narrowed", "breaks only on empty input")
    err = cv.refute("F001", 1, "reachability", "r2", "survived", "--narrowed", "x", code=2).stderr
    assert "`narrowed` is given only with outcome downgraded" in err
    err = cv.refute("F001", 1, "reachability", "r2", "downgraded", code=2).stderr
    assert "`narrowed` must be a non-empty string" in err
    cv.refute("F001", 1, "reachability", "r2")
    status = cv.status()["by_id"]["F001"]
    assert status["claim"] == "breaks only on empty input"
    assert status["refute"] == "open"
    cv.quiet_round("F001", 2, ("provenance", "carve-out"))
    assert cv.status()["by_id"]["F001"]["refute"] == "converged"


def test_cap_five_rounds_unconverged(cv: Converge) -> None:
    cv.init()
    cv.file()
    angles = iter(ATTACK)
    for rnd in range(1, 6):
        cv.refute("F001", rnd, next(angles), "r1", "downgraded", "--narrowed", f"narrow {rnd}")
        cv.refute("F001", rnd, next(angles), "r2")
    status = cv.status()["by_id"]["F001"]
    assert status["refute"] == "unconverged"
    assert status["round"] == 5
    err = cv.refute("F001", 6, next(angles), "r1", code=2).stderr
    assert "exceeds caps.refute_rounds 5" in err
    cv.ok("converged", "s1", "--phase", "refute")


def test_killed_claim_accepts_nothing(cv: Converge) -> None:
    cv.init()
    cv.file()
    cv.refute("F001", 1, "real-referent", "r1", "killed")
    assert cv.status()["by_id"]["F001"]["stage"] == "dead"
    assert "F001 is killed; it accepts nothing" in cv.refute("F001", 1, "boundary", "r2", code=2).stderr
    cv.ok("converged", "s1", "--phase", "refute")


def test_retracted(cv: Converge) -> None:
    cv.init()
    cv.file()
    cv.refute("F001", 1, "real-referent", "r1", "retracted")
    assert cv.status()["by_id"]["F001"]["refute"] == "retracted"


def test_downgrade_reopens_dependents(cv: Converge) -> None:
    cv.init()
    cv.file(claim="root cause")
    cv.file(claim="consequence", extra=("--depends", "F001"))
    cv.quiet_round("F002", 1, ("boundary", "reachability"))
    assert cv.status()["by_id"]["F002"]["refute"] == "converged"
    cv.refute("F001", 1, "boundary", "r1", "downgraded", "--narrowed", "narrower root")
    status = cv.status()["by_id"]["F002"]
    assert status["refute"] == "open" and status["reopened"] is True
    cv.quiet_round("F002", 2, ("provenance", "carve-out"))
    status = cv.status()["by_id"]["F002"]
    assert status["refute"] == "converged" and status["reopened"] is False


def test_kill_reopens_dependent_already_in_cut(cv: Converge) -> None:
    cv.init()
    cv.file(claim="root cause")
    cv.file(claim="consequence", extra=("--depends", "F001"))
    cv.quiet_round("F002", 1, ("boundary", "reachability"))
    cv.cut("F002", 1, "cut-1")
    assert cv.status()["by_id"]["F002"]["stage"] == "cut"
    cv.refute("F001", 1, "real-referent", "r1", "killed")
    status = cv.status()["by_id"]["F002"]
    assert status["stage"] == "refute" and status["refute"] == "open"
    assert "refute state is open" in cv.cut("F002", 1, "cut-2", code=2).stderr


def test_depends_must_name_known_claims(cv: Converge) -> None:
    cv.init()
    assert "unknown claim 'F009'" in cv.file(extra=("--depends", "F009"), code=2)


def test_rebut_forces_another_round_and_rejects_duplicate_evidence(cv: Converge) -> None:
    cv.init()
    cv.file(agent="finder")
    cv.quiet_round("F001", 1, ("boundary", "reachability"))
    rebut = ("rebut", "s1", "--as", "finder", "--claim", "F001", "--stage", "refute",
             "--evidence", "b.py:4 passes None")
    cv.ok(*rebut)
    assert cv.status()["by_id"]["F001"]["refute"] == "open"
    err = cv.ok(*rebut, code=2).stderr
    assert "this evidence was already given for F001 stage refute" in err
    cv.quiet_round("F001", 2, ("provenance", "carve-out"))
    assert cv.status()["by_id"]["F001"]["refute"] == "converged"


def test_ledger_source_fields(cv: Converge) -> None:
    cv.init()
    cv.file()
    err = cv.refute("F001", 1, "deliberate", "r1", "survived", "--source", "ledger:tech/x", code=2).stderr
    assert "`source` and `ledger_evidence` are given together" in err
    err = cv.refute("F001", 1, "deliberate", "r1", "survived", "--source", "tech/x",
                    "--ledger-evidence", "maybe", code=2).stderr
    assert "`source` must be ledger:<slug>" in err and "`ledger_evidence` must be one of" in err
    cv.refute("F001", 1, "deliberate", "r1", "survived", "--source", "ledger:tech/x",
              "--ledger-evidence", "fail")
    assert cv.events()[-1]["source"] == "ledger:tech/x"


def test_status_lists_unused_attack_angles(cv: Converge) -> None:
    cv.init()
    cv.file()
    cv.refute("F001", 1, "boundary", "r1")
    unused = cv.status()["by_id"]["F001"]["unused_attack_angles"]
    assert "boundary" not in unused and len(unused) == len(ATTACK) - 1
    text = cv.ok("status", "s1").stdout
    assert "F001 stage=refute refute=open round=1" in text


def test_converged_refute_exit_codes(cv: Converge) -> None:
    cv.init()
    cv.file()
    out = cv.ok("converged", "s1", "--phase", "refute", code=1).stdout
    assert "OPEN phase=refute" in out and "F001 refute=open" in out
    cv.quiet_round("F001", 1, ("boundary", "reachability"))
    assert "CONVERGED phase=refute" in cv.ok("converged", "s1", "--phase", "refute").stdout
