"""The dispute round trip of a refuted batch and the status ratchet
`survived` < `disputed` < `killed`."""
from __future__ import annotations

from typing import Any

import pytest
from conftest import BATCH_1, DISABLED, FINDER, R1, R2, Converge
from converge import ledger, model, protocol

# Two table batches: BATCH_1, then BATCH_2.
BATCH_2 = tuple(DISABLED[:5])
TWO_BATCHES = {"angles": {"disable": DISABLED[5:]}}


def _slate(cv: Converge) -> model.Slate:
    return ledger.read(cv.path(), "s1")


def _state(cv: Converge, batch: Any = 1, cid: str = "F001") -> tuple[str, str]:
    """The batch state of `batch` and the claim's status."""
    slate = _slate(cv)
    claim = slate.claims[cid]
    return protocol.batch_state(slate, claim, batch), protocol.status(slate, claim)


def _step(cv: Converge, step: str, batch: Any = 1, cid: str = "F001", refuter: str = R1) -> None:
    """One finder reply (`rebut`, `decline`) or refuter verdict (`agree`, `disagree`)."""
    if step in ("agree", "disagree"):
        fields: dict[str, Any] = {"evidence": f"{step} {batch} b.py:3"} if step == "disagree" else {}
        problems = cv.append("verdict", refuter, claim=cid, batch=batch, verdict=step, **fields)
    elif step == "rebut":
        text = f"rebut {batch} {len(_slate(cv).claims[cid].state.replies.get(batch, []))}"
        problems = cv.append("reply", FINDER, claim=cid, batch=batch, stance="rebut",
                             evidence=text, evidence_sha256=ledger.evidence_hash(text))
    else:
        problems = cv.append("reply", FINDER, claim=cid, batch=batch, stance="decline")
    assert problems == [], problems


def _batch_2(cv: Converge, refuted: bool = False) -> None:
    for index, angle in enumerate(BATCH_2):
        outcome = "refuted" if refuted and index == 0 else "clean"
        assert cv.attack("F001", angle, batch=2, outcome=outcome) == []


def test_clean_batch_is_done_and_leaves_the_status(cv: Converge) -> None:
    cv.ready()
    cv.batch_1()
    assert _state(cv) == ("done", "survived")
    cv.fresh_eye()
    assert _state(cv, "fresh-eye") == ("done", "survived")


@pytest.mark.parametrize(("steps", "batch_state", "status"), [
    ((), "awaiting-reply-1", "survived"),
    (("decline",), "killed", "killed"),
    (("rebut",), "awaiting-verdict", "survived"),
    (("rebut", "agree"), "done", "survived"),
    (("rebut", "disagree"), "awaiting-reply-2", "survived"),
    (("rebut", "disagree", "decline"), "killed", "killed"),
    (("rebut", "disagree", "rebut"), "done", "disputed"),
])
def test_round_trip(cv: Converge, steps: tuple[str, ...], batch_state: str, status: str) -> None:
    cv.ready()
    cv.batch_1(refuted=(BATCH_1[2],))
    for step in steps:
        _step(cv, step)
    assert _state(cv) == (batch_state, status)


def test_the_fresh_eye_batch_takes_the_same_round_trip(cv: Converge) -> None:
    cv.ready()
    cv.batch_1()
    assert cv.attack("F001", "retry timing", agent=R2, batch="fresh-eye", outcome="refuted",
                     last=True) == []
    assert _state(cv, "fresh-eye") == ("awaiting-reply-1", "survived")
    _step(cv, "rebut", "fresh-eye")
    _step(cv, "disagree", "fresh-eye", refuter=R2)
    _step(cv, "rebut", "fresh-eye")
    assert _state(cv, "fresh-eye") == ("done", "disputed")


def test_disputed_is_never_cleared(cv: Converge) -> None:
    cv.ready(config=TWO_BATCHES)
    cv.batch_1(refuted=(BATCH_1[0],))
    for step in ("rebut", "disagree", "rebut"):
        _step(cv, step)
    _batch_2(cv, refuted=True)
    _step(cv, "rebut", 2)
    _step(cv, "agree", 2)
    assert _state(cv, 2) == ("done", "disputed")
    cv.fresh_eye()
    assert _state(cv, "fresh-eye") == ("done", "disputed")
    assert _slate(cv).claims["F001"].state.status == "disputed"


def test_agree_keeps_survived_and_the_revised_text(cv: Converge) -> None:
    cv.ready(config=TWO_BATCHES)
    cv.batch_1(refuted=(BATCH_1[0],))
    text = "x breaks y only when the caller passes None"
    assert cv.append("reply", FINDER, claim="F001", batch=1, stance="rebut", evidence="e1",
                     evidence_sha256=ledger.evidence_hash("e1"), text=text) == []
    _step(cv, "agree")
    assert _state(cv) == ("done", "survived")
    assert _slate(cv).claims["F001"].text == text


def test_disputed_claim_is_killed_by_a_later_decline(cv: Converge) -> None:
    cv.ready(config=TWO_BATCHES)
    cv.batch_1(refuted=(BATCH_1[0],))
    for step in ("rebut", "disagree", "rebut"):
        _step(cv, step)
    _batch_2(cv, refuted=True)
    _step(cv, "decline", 2)
    assert _state(cv, 2) == ("killed", "killed")
    assert "F001 is killed; it accepts nothing" in cv.attack("F001", "retry timing", agent=R2,
                                                            batch="fresh-eye")
