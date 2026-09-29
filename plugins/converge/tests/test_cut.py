"""Cut rounds: stage order, evidence per field, accept/rebut convergence, cap, choice."""
from __future__ import annotations

from conftest import CUTTER, FINDER, Converge


def _survived(cv: Converge, claim: str = "F001") -> None:
    cv.quiet_round(claim, 1, ("boundary", "reachability"))


def test_cut_needs_refute_done(cv: Converge) -> None:
    cv.init()
    cv.file()
    assert "refute state is open" in cv.cut("F001", 1, CUTTER, code=2).stderr
    cv.refute("F001", 1, "boundary", "r1")
    assert "refute state is open" in cv.cut("F001", 1, CUTTER, code=2).stderr


def test_accept_converges_the_latest_round(cv: Converge) -> None:
    cv.init()
    cv.file()
    _survived(cv)
    cv.cut("F001", 1, CUTTER)
    status = cv.status()["by_id"]["F001"]
    assert status["stage"] == "cut" and status["cut"] == "open"
    assert status["cut_note"] == "awaiting accept or rebut, round 1"
    assert "F001 cut=open" in cv.ok("converged", "s1", "--phase", "cut", code=1).stdout
    cv.accept("F001", 1)
    status = cv.status()["by_id"]["F001"]
    assert status["cut"] == "converged" and status["accepted_round"] == 1
    assert status["cut_note"] == "accepted round 1"
    assert "accepted=1" in cv.ok("status", "s1").stdout
    cv.ok("converged", "s1", "--phase", "cut")


def test_two_equal_rounds_without_rebut_do_not_converge(cv: Converge) -> None:
    cv.init()
    cv.file()
    _survived(cv)
    cv.cut("F001", 1, CUTTER)
    cv.cut("F001", 2, CUTTER)
    assert cv.status()["by_id"]["F001"]["cut"] == "open"


def test_rebut_then_identical_round_converges(cv: Converge) -> None:
    cv.init()
    cv.file()
    _survived(cv)
    cv.cut("F001", 1, CUTTER, "common")
    cv.rebut_cut("F001", "prod query shows every call")
    assert cv.status()["by_id"]["F001"]["cut_note"] == "rebutted round 1"
    cv.cut("F001", 2, CUTTER, "common")
    status = cv.status()["by_id"]["F001"]
    assert status["cut"] == "converged" and status["cut_note"] == "held after rebut, round 2"


def test_rebut_then_changed_round_needs_an_answer(cv: Converge) -> None:
    cv.init()
    cv.file()
    _survived(cv)
    cv.cut("F001", 1, CUTTER, "common")
    cv.rebut_cut("F001", "prod query shows every call")
    cv.cut("F001", 2, CUTTER, "every-call")
    assert cv.status()["by_id"]["F001"]["cut"] == "open"
    cv.accept("F001", 2)
    assert cv.status()["by_id"]["F001"]["cut"] == "converged"


def test_rebut_after_accept_reopens(cv: Converge) -> None:
    cv.init()
    cv.file()
    _survived(cv)
    cv.cut_converge("F001")
    assert cv.status()["by_id"]["F001"]["cut"] == "converged"
    cv.rebut_cut("F001", "new prod numbers")
    assert cv.status()["by_id"]["F001"]["cut"] == "open"
    cv.cut("F001", 2, CUTTER, "every-call")
    assert cv.status()["by_id"]["F001"]["cut"] == "open"
    cv.accept("F001", 2)
    assert cv.status()["by_id"]["F001"]["cut"] == "converged"


def test_accept_rules(cv: Converge) -> None:
    cv.init()
    cv.file()
    _survived(cv)
    assert "has no cut round to accept" in cv.accept("F001", 1, code=2).stderr
    cv.cut("F001", 1, CUTTER)
    assert "only F001's finder finder may accept" in cv.accept("F001", 1, "r1", code=2).stderr
    assert "latest cut round is 1, got 2" in cv.accept("F001", 2, code=2).stderr
    cv.rebut_cut("F001", "e1")
    assert "was rebutted; answer the next cut round" in cv.accept("F001", 1, code=2).stderr
    cv.cut("F001", 2, CUTTER, "rare")
    cv.accept("F001", 2)
    assert "already accepted" in cv.accept("F001", 2, code=2).stderr


def test_accept_refused_on_refute_only(cv: Converge) -> None:
    cv.init(mode="refute-only", lenses="")
    cv.file(agent="slate", lens="", angle="", origin="slate")
    assert "refute-only slate has no cut stage" in cv.accept("F001", 1, "slate", code=2).stderr


def test_cap_three_rounds(cv: Converge) -> None:
    cv.init()
    cv.file()
    _survived(cv)
    for rnd, freq in ((1, "common"), (2, "rare"), (3, "every-call")):
        cv.cut("F001", rnd, CUTTER, freq)
        if rnd < 3:
            cv.rebut_cut("F001", f"rebut {rnd}")
    status = cv.status()["by_id"]["F001"]
    assert status["cut"] == "capped" and status["cut_note"] == "capped at round 3"
    assert "exceeds caps.cut_rounds 3" in cv.cut("F001", 4, CUTTER, code=2).stderr
    cv.ok("converged", "s1", "--phase", "cut")


def test_round_sequence_and_same_cutter_every_round(cv: Converge) -> None:
    cv.init()
    cv.file()
    _survived(cv)
    assert "next cut round is 1, got 2" in cv.cut("F001", 2, CUTTER, code=2).stderr
    cv.cut("F001", 1, CUTTER)
    cv.rebut_cut("F001", "e1")
    cv.cut("F001", 2, CUTTER)
    cv.rebut_cut("F001", "e2")
    cv.cut("F001", 3, CUTTER)
    assert {e["as"] for e in cv.events() if e["event"] == "cut"} == {CUTTER}


def test_evidence_per_field_and_known_angles(cv: Converge) -> None:
    cv.init()
    cv.file()
    _survived(cv)
    err = cv.refused("cut", "s1", "--as", CUTTER, "--claim", "F001", "--round", "1",
                     "--frequency", "often", "--severity", "wrong-behavior", "--confidence", "traced",
                     "--difficulty", "local", "--evidence", "entry-points=x",
                     "--evidence", "boundary=y", "--evidence", "blast-radius=")
    for fragment in ("`frequency` must be one of", "unknown evaluate angle 'boundary'",
                     "evidence for 'blast-radius' must be non-empty",
                     "no evidence for `confidence`", "no evidence for `difficulty`"):
        assert fragment in err


def test_choice_required_for_survived_cross_cutting(cv: Converge) -> None:
    cv.init()
    cv.file()
    _survived(cv)
    err = cv.cut("F001", 1, CUTTER, "common", "wrong-behavior", "traced", "redesign", code=2).stderr
    assert "a non-empty `choice` is required" in err
    cv.cut("F001", 1, CUTTER, "common", "wrong-behavior", "traced", "cross-cutting",
           "--choice", "fix in the gateway or in every caller")
    assert cv.events()[-1]["choice"] == "fix in the gateway or in every caller"


def test_choice_not_required_when_inconclusive(cv: Converge) -> None:
    cv.init()
    cv.file()
    cv.refute("F001", 1, "boundary", "r1", "inconclusive")
    cv.refute("F001", 1, "reachability", "r2")
    cv.cut("F001", 1, CUTTER, "common", "wrong-behavior", "traced", "redesign")


def test_rebut_cut_needs_a_cut_round(cv: Converge) -> None:
    cv.init()
    cv.file(agent=FINDER)
    assert "has no cut round to rebut" in cv.rebut_cut("F001", "e", code=2).stderr
