"""Role rules: finder never refutes/cuts its claim, refuters ∩ cutters = ∅, rebut, reserved ids."""
from __future__ import annotations

from conftest import CUT_EVIDENCE, Converge


def test_finder_cannot_refute_own_claim(cv: Converge) -> None:
    cv.init()
    cv.file(agent="finder")
    err = cv.refute("F001", 1, "reachability", "finder", code=2).stderr
    assert "finder filed F001 and may not refute it" in err


def test_finder_cannot_cut_own_claim(cv: Converge) -> None:
    cv.init()
    cv.file(agent="finder")
    cv.quiet_round("F001", 1, ("reachability", "boundary"))
    err = cv.cut("F001", 1, "finder", code=2).stderr
    assert "may not cut it" in err


def test_same_refuter_may_refute_same_claim_in_a_later_round_with_a_new_angle(cv: Converge) -> None:
    cv.init()
    cv.file()
    cv.refute("F001", 1, "reachability", "r1")
    cv.refute("F001", 1, "boundary", "r1")
    assert cv.status()["by_id"]["F001"]["refute"] == "converged"
    cv.ok("rebut", "s1", "--as", "finder", "--claim", "F001", "--stage", "refute",
          "--evidence", "b.py:4 passes None")
    assert "already used on F001" in cv.refute("F001", 2, "reachability", "r1", code=2).stderr
    cv.refute("F001", 2, "provenance", "r1")
    cv.refute("F001", 2, "carve-out", "r1")
    assert cv.status()["by_id"]["F001"]["refute"] == "converged"


def test_same_refuter_may_refute_different_claims(cv: Converge) -> None:
    cv.init()
    cv.file()
    cv.file(claim="other")
    cv.refute("F001", 1, "reachability", "refute-1")
    cv.refute("F002", 1, "reachability", "refute-1")


def test_refuter_cannot_cut_and_cutter_cannot_refute(cv: Converge) -> None:
    cv.init()
    cv.file()
    cv.refute("F001", 1, "reachability", "refute-1")
    cv.refute("F001", 1, "boundary", "refute-2")
    err = cv.cut("F001", 1, "refute-1", code=2).stderr
    assert "refuters and cutters are disjoint" in err
    cv.cut("F001", 1, "cut-1")
    # finder's rebut on refute sends the claim back to refute; the cutter still may not refute
    cv.ok("rebut", "s1", "--as", "finder", "--claim", "F001", "--stage", "refute",
          "--evidence", "new trace: b.py:4 calls it with None")
    err = cv.refute("F001", 2, "provenance", "cut-1", code=2).stderr
    assert "refuters and cutters are disjoint" in err


def test_refuter_of_one_claim_may_cut_another(cv: Converge) -> None:
    cv.init()
    cv.file()
    cv.file(claim="other")
    cv.quiet_round("F001", 1, ("boundary", "reachability"), agents=("r1", "r2"))
    cv.refute("F002", 1, "boundary", "r1")
    cv.refute("F002", 1, "reachability", "r1")
    cv.cut("F001", 1, "cutter")
    assert "refuters and cutters are disjoint" in cv.cut("F002", 1, "r1", code=2).stderr
    cv.cut("F002", 1, "r2")


def test_rebut_only_by_finder(cv: Converge) -> None:
    cv.init()
    cv.file(agent="finder")
    cv.refute("F001", 1, "reachability", "refute-1", "downgraded", "--narrowed", "narrower")
    err = cv.refused("rebut", "s1", "--as", "refute-9", "--claim", "F001", "--stage", "refute",
                     "--evidence", "e")
    assert "only F001's finder finder may rebut" in err
    cv.ok("rebut", "s1", "--as", "finder", "--claim", "F001", "--stage", "refute",
          "--evidence", "e")


def test_orchestrator_never_refutes_or_cuts(cv: Converge) -> None:
    cv.init(agent="orch")
    cv.file()
    assert "the orchestrator never writes refute" in cv.refute("F001", 1, "boundary", "orch", code=2).stderr
    cv.quiet_round("F001", 1, ("reachability", "boundary"))
    assert "the orchestrator never writes cut" in cv.cut("F001", 1, "orch", code=2).stderr


def test_reserved_agent_ids(cv: Converge) -> None:
    cv.init()
    err = cv.file(agent="converge", code=2)
    assert "reserved for computed cutoff events" in err
    err = cv.file(agent="slate", origin="lens", code=2)
    assert "'slate' is reserved for refute-only" in err
    err = cv.file(origin="slate", code=2)
    assert "origin slate is only for refute-only" in err


def test_refute_only_roles(cv: Converge) -> None:
    cv.init(mode="refute-only", lenses="")
    err = cv.file(agent="find-1", lens="", angle="", origin="slate", code=2)
    assert "refute-only: file is written only with --as slate" in err
    assert cv.file(agent="slate", lens="", angle="", origin="slate") == "F001"
    assert "may not refute it" in cv.refute("F001", 1, "boundary", "slate", code=2).stderr
    err = cv.refused("rebut", "s1", "--as", "slate", "--claim", "F001", "--stage", "refute",
                     "--evidence", "e")
    assert "there is no finder, so rebut is refused" in err
    err = cv.refused("find-run", "s1", "--as", "slate", "--lens", "x", "--angle", "changed-contract",
                     "--tell", "t", "--searches", "s", "--positive-control", "p", "--result", "none")
    assert "'slate' may not write find-run" in err
    cv.refute("F001", 1, "boundary", "refute-1")
    err = cv.file(agent="slate", lens="", angle="", origin="slate", code=2)
    assert "filed before the first refute" in err
    cv.refute("F001", 1, "reachability", "refute-2")
    err = cv.refused("cut", "s1", "--as", "cut-1", "--claim", "F001", "--round", "1",
                     "--frequency", "common", "--severity", "degraded", "--confidence", "traced",
                     "--difficulty", "local", *CUT_EVIDENCE)
    assert "refute-only slate has no cut stage" in err
