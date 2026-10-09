"""Early cut: `cut` right after file or escalate and after any complete refute round (R2);
a refute round starts only from a converged or capped cut (R3)."""
from __future__ import annotations

from conftest import CUTTER, FINDER, R1, R2, Converge


def _escalated(cv: Converge, slate: str = "s1", **steps: bool) -> None:
    cv.init(slate, defaults=True, config={"steps": steps} if steps else None)
    cv.file(slate)
    assert cv.append("escalate", FINDER, slate=slate, claim="F001") == []


def test_cut_right_after_escalate_then_refute(cv: Converge) -> None:
    _escalated(cv)
    cv.cut("F001", 1, CUTTER)
    cv.accept("F001", 1)
    cv.quiet_round("F001", 1, ("boundary", "reachability"))
    claim = cv.status()["by_id"]["F001"]
    assert claim["refute"] == "converged" and claim["cut"] == "converged"


def test_cut_right_after_file_when_escalate_is_off(cv: Converge) -> None:
    cv.init(defaults=True, config={"steps": {"escalate": False}})
    cv.file()
    cv.cut("F001", 1, CUTTER)


def test_refute_round_needs_a_converged_cut(cv: Converge) -> None:
    _escalated(cv)
    err = cv.refute("F001", 1, "boundary", R1, code=2).stderr
    assert "refute: F001 needs a converged cut first" in err
    cv.cut("F001", 1, CUTTER)
    assert "needs a converged cut first" in cv.refute("F001", 1, "boundary", R1, code=2).stderr
    cv.accept("F001", 1)
    cv.refute("F001", 1, "boundary", R1)


def test_downgrade_makes_the_cut_stale(cv: Converge) -> None:
    _escalated(cv)
    cv.cut_converge("F001")
    cv.refute("F001", 1, "boundary", R1, "downgraded", "--narrowed", "only on retry")
    # The started round may still be finished; the next one needs a new cut round.
    cv.refute("F001", 1, "reachability", R2)
    err = cv.refute("F001", 2, "provenance", R1, code=2).stderr
    assert "refute: F001 needs a converged cut first" in err
    cv.cut("F001", 2, CUTTER)
    cv.accept("F001", 2)
    cv.refute("F001", 2, "provenance", R1)


def test_cut_waits_for_a_complete_refute_round(cv: Converge) -> None:
    _escalated(cv)
    cv.cut_converge("F001")
    cv.refute("F001", 1, "boundary", R1, "downgraded", "--narrowed", "only on retry")
    err = cv.cut("F001", 2, CUTTER, code=2).stderr
    assert "cut: F001 refute round 1 has 1 refute event(s); cut comes after a complete round" in err
    cv.refute("F001", 1, "reachability", R2)
    cv.cut("F001", 2, CUTTER)


def test_early_cut_off_keeps_refute_first(cv: Converge) -> None:
    _escalated(cv, early_cut=False)
    err = cv.cut("F001", 1, CUTTER, code=2).stderr
    assert "cut: F001 refute state is open; cut needs refute converged" in err
    cv.quiet_round("F001", 1, ("boundary", "reachability"))
    cv.cut_converge("F001")


def test_refute_only_slates_are_unaffected(cv: Converge) -> None:
    cv.init("s1", "refute-only", "", defaults=True)
    cv.file(agent="slate", lens="", angle="", origin="slate")
    cv.quiet_round("F001", 1, ("boundary", "reachability"))
    assert cv.status()["by_id"]["F001"]["refute"] == "converged"


def test_next_cut_round_waits_for_the_finder_answer(cv: Converge) -> None:
    _escalated(cv)
    cv.cut("F001", 1, CUTTER, "common")
    err = cv.cut("F001", 2, CUTTER, "common", code=2).stderr
    assert "cut: F001 round 1 awaits its finder; the finder must accept or rebut it first" in err
    cv.rebut_cut("F001", "prod query shows every call")
    cv.cut("F001", 2, CUTTER, "every-call")
    assert "cut: F001 round 2 awaits its finder" in cv.cut("F001", 3, CUTTER, code=2).stderr
    cv.accept("F001", 2)
    assert cv.status()["by_id"]["F001"]["cut"] == "converged"



def test_stale_unanswered_cut_takes_the_next_round(cv: Converge) -> None:
    cv.init(defaults=True)
    cv.file()
    cv.file(extra=("--depends", "F001"))
    for cid in ("F001", "F002"):
        assert cv.append("escalate", FINDER, claim=cid) == []
    cv.cut_converge("F001")
    cv.cut("F002", 1, CUTTER)
    cv.refute("F001", 1, "boundary", R1, "downgraded", "--narrowed", "only on retry")
    cv.refute("F001", 1, "reachability", R2)
    cv.cut("F002", 2, CUTTER)
