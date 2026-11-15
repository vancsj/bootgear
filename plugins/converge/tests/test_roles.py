"""Role rules: the finder never attacks or cuts its claim, refuters and cutters are disjoint
per claim, the orchestrator writes neither."""
from __future__ import annotations

from conftest import BATCH_1, CUTTER, FINDER, MAIN, R1, R2, Converge


def test_finder_cannot_cut_own_claim(cv: Converge) -> None:
    cv.ready(cut="before")
    err = cv.cut("F001", 1, FINDER, when="before", code=2).stderr
    assert "cut: finder filed F001 and may not cut it" in err


def test_orchestrator_never_attacks_or_cuts(cv: Converge) -> None:
    cv.ready(cut="before")
    assert (any(("attack: orch wrote init; the orchestrator never writes attack") in problem for problem in cv.check("F001", BATCH_1[0], agent=MAIN)))
    err = cv.cut("F001", 1, MAIN, when="before", code=2).stderr
    assert "the orchestrator never writes cut" in err


def test_same_refuter_may_attack_different_claims(cv: Converge) -> None:
    cv.ready(claims=2)
    assert cv.check("F001", BATCH_1[0], agent=R1) == []
    assert cv.check("F002", BATCH_1[0], agent=R1) == []


def test_refuter_of_one_claim_may_cut_another(cv: Converge) -> None:
    cv.ready(cut="after", claims=2)
    cv.batch_1("F001", agent=R1)
    cv.fresh_eye("F001", agent=R2)
    cv.batch_1("F002", agent=R1)
    cv.fresh_eye("F002", agent=R2)
    cv.cut("F001", 1, CUTTER)
    assert "refuters and cutters are disjoint" in cv.cut("F002", 1, R1, code=2).stderr
    assert "refuters and cutters are disjoint" in cv.cut("F002", 1, R2, code=2).stderr
    cv.cut("F002", 1, CUTTER)


def test_gap_hunt_finder_may_not_attack_its_claim(cv: Converge) -> None:
    cv.init(config={"steps": {"cut": "none", "escalate": False}})
    cv.cover()
    gap = cv.file(agent=R2, lens="gap-hunt", origin="gap-hunt", claim="ticket asks for retries")
    assert any(("attack: r2 filed F001 and may not attack it") in problem for problem in cv.check(gap, BATCH_1[0], agent=R2))
    assert cv.check(gap, BATCH_1[0], agent=R1) == []
