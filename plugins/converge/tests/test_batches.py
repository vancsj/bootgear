"""Attack batches: fixed chunks of table angles, the fresh-eye batch, who attacks each batch,
and the slate phase order."""
from __future__ import annotations

from typing import Any

import pytest
from conftest import BATCH_1, CUTTER, DISABLED, FINDER, R1, R2, Converge
from converge import ledger, model, protocol

BATCH_2 = tuple(DISABLED[:5])
TWO_BATCHES = {"angles": {"disable": DISABLED[5:]}}
TABLE = (*BATCH_1, *BATCH_2)


def _slate(cv: Converge) -> model.Slate:
    return ledger.read(cv.path(), "s1")


def _next(cv: Converge, cid: str = "F001") -> Any:
    slate = _slate(cv)
    return protocol.next_batch(slate, slate.claims[cid])


def _batch_state(cv: Converge, batch: Any, cid: str = "F001") -> str:
    slate = _slate(cv)
    return protocol.batch_state(slate, slate.claims[cid], batch)


def _na(cv: Converge, angle: str, cid: str = "F001", agent: str = R1) -> list[str]:
    return cv.append("angle-na", agent, phase="attack", angle=angle, claim=cid,
                     reason="no such path")


def _reply(cv: Converge, batch: Any = 1, evidence: str = "e1") -> list[str]:
    return cv.append("reply", FINDER, claim="F001", batch=batch, stance="rebut",
                     evidence=evidence, evidence_sha256=ledger.evidence_hash(evidence))


# -- table batches ----------------------------------------------------------------


def test_table_batches_are_fixed_chunks_of_angles_per_claim(cv: Converge) -> None:
    cv.ready(claims=2, config=TWO_BATCHES, angles_per_claim=3)
    slate = _slate(cv)
    assert protocol.table_batches(slate) == [list(TABLE[0:3]), list(TABLE[3:6]),
                                             list(TABLE[6:9]), [TABLE[9]]]
    assert [protocol.next_batch(slate, c) for c in slate.claims.values()] == [1, 1]


def test_batch_completes_with_attacks_and_not_applicable_angles(cv: Converge) -> None:
    cv.ready(config=TWO_BATCHES)
    for angle in BATCH_1[:4]:
        assert cv.attack("F001", angle) == []
    assert (_next(cv), _batch_state(cv, 1)) == (1, "open")
    assert _na(cv, BATCH_1[4]) == []
    assert (_next(cv), _batch_state(cv, 1)) == (2, "done")
    assert _batch_state(cv, 2) == "open"


def test_attack_outside_the_open_batch_is_refused(cv: Converge) -> None:
    cv.ready(config=TWO_BATCHES)
    open_batch = ", ".join(BATCH_1)
    assert (f"attack: angle {BATCH_2[0]!r} is not in F001's open batch 1 ({open_batch})"
            in cv.attack("F001", BATCH_2[0]))
    assert ("attack: F001's open batch is 1 (open); got batch 2"
            in cv.attack("F001", BATCH_2[0], batch=2))
    assert ("attack: F001's open batch is 1 (open); got batch fresh-eye"
            in cv.attack("F001", "retry timing", agent=R2, batch="fresh-eye"))
    assert (f"angle-na: angle {BATCH_2[0]!r} is not in F001's open batch 1 ({open_batch})"
            in _na(cv, BATCH_2[0]))


def test_next_batch_starts_when_the_dispute_is_done(cv: Converge) -> None:
    cv.ready(config=TWO_BATCHES)
    cv.batch_1(refuted=(BATCH_1[1],))
    assert (_next(cv), _batch_state(cv, 1)) == (1, "awaiting-reply-1")
    assert ("attack: F001's open batch is 1 (awaiting-reply-1); got batch 2"
            in cv.attack("F001", BATCH_2[0], batch=2))
    assert ("verdict: F001 batch 1 is awaiting-reply-1; verdict needs awaiting-verdict"
            in cv.append("verdict", R1, claim="F001", batch=1, verdict="agree"))
    assert _reply(cv) == []
    assert ("attack: F001 batch 1 is awaiting-verdict; attack needs open"
            in cv.attack("F001", BATCH_1[0]))
    assert ("reply: F001 batch 1 is awaiting-verdict; reply needs awaiting-reply-1 or "
            "awaiting-reply-2") in _reply(cv, evidence="e2")
    assert cv.append("verdict", R1, claim="F001", batch=1, verdict="agree") == []
    assert _next(cv) == 2
    assert cv.attack("F001", BATCH_2[0], batch=2) == []


def test_reply_waits_for_the_batch_to_complete(cv: Converge) -> None:
    cv.ready()
    assert cv.attack("F001", BATCH_1[0], outcome="refuted") == []
    assert ("reply: F001 batch 1 is open; reply needs awaiting-reply-1 or awaiting-reply-2"
            in _reply(cv))


def test_every_claim_gets_its_own_batch(cv: Converge) -> None:
    cv.ready(claims=2, config=TWO_BATCHES)
    cv.batch_1("F001")
    assert (_next(cv, "F001"), _next(cv, "F002")) == (2, 1)
    assert cv.attack("F001", BATCH_2[0], batch=2) == []
    assert cv.attack("F002", BATCH_1[0]) == []


def test_table_batches_are_attacked_by_r1(cv: Converge) -> None:
    cv.ready(claims=2)
    assert cv.attack("F001", BATCH_1[0]) == []
    assert ("attack: table batches are attacked by r1 (r1), not r2"
            in cv.attack("F002", BATCH_1[0], agent=R2))
    assert "angle-na: table batches are attacked by r1 (r1), not r2" in _na(
        cv, BATCH_1[0], "F002", R2)


# -- the fresh-eye batch ------------------------------------------------------------


def test_fresh_eye_follows_the_last_table_batch(cv: Converge) -> None:
    cv.ready(config=TWO_BATCHES)
    cv.batch_1()
    for angle in BATCH_2:
        assert cv.attack("F001", angle, batch=2) == []
    assert _next(cv) == "fresh-eye"


def test_fresh_eye_batch_holds_up_to_angles_per_claim_attacks(cv: Converge) -> None:
    cv.ready(claims=2)
    cv.batch_1()
    for n in range(1, 6):
        assert _next(cv) == "fresh-eye"
        assert cv.attack("F001", f"angle {n}", agent=R2, batch="fresh-eye") == []
    assert _next(cv) is None
    assert _batch_state(cv, "fresh-eye") == "done"
    assert ("attack: F001 has finished its attack"
            in cv.attack("F001", "angle 6", agent=R2, batch="fresh-eye"))


def test_last_closes_the_fresh_eye_batch(cv: Converge) -> None:
    cv.ready()
    cv.batch_1()
    assert cv.attack("F001", "angle 1", agent=R2, batch="fresh-eye", last=False) == []
    assert _next(cv) == "fresh-eye"
    assert cv.attack("F001", "angle 2", agent=R2, batch="fresh-eye", last=True) == []
    assert _next(cv) is None


def test_fresh_eye_batch_needs_one_attack(cv: Converge) -> None:
    cv.ready()
    cv.batch_1()
    slate = _slate(cv)
    assert protocol.batch_state(slate, slate.claims["F001"], "fresh-eye") == "open"
    assert protocol.slate_phase(slate) == "attack"


def test_fresh_eye_attacker_is_r2(cv: Converge) -> None:
    cv.ready()
    cv.batch_1()
    assert ("attack: the fresh-eye batch of F001 is attacked by r2, not r1 (r1)"
            in cv.attack("F001", "angle 1", agent=R1, batch="fresh-eye"))
    assert cv.attack("F001", "angle 1", agent=R2, batch="fresh-eye") == []


def test_fresh_eye_attacker_is_r1_with_one_refuter(cv: Converge) -> None:
    cv.ready(refuters=1)
    cv.batch_1()
    assert ("attack: the fresh-eye batch of F001 is attacked by r1 (r1), not r2"
            in cv.attack("F001", "angle 1", agent=R2, batch="fresh-eye"))
    assert cv.attack("F001", "angle 1", agent=R1, batch="fresh-eye", last=True) == []


def test_fresh_eye_attacker_is_r1_on_a_gap_hunt_claim(cv: Converge) -> None:
    cv.init(config={"steps": {"cut": "none", "gap_hunt": True, "escalate": False},
                    "angles": {"disable": DISABLED}})
    cv.file()
    cv.cover()
    assert cv.file(agent=R2, origin="gap-hunt") == "F002"
    cv.batch_1("F001")
    cv.batch_1("F002")
    assert cv.attack("F001", "angle 1", agent=R2, batch="fresh-eye", last=True) == []
    problems = cv.attack("F002", "angle 1", agent=R2, batch="fresh-eye")
    assert "attack: r2 filed F002 and may not attack it" in problems
    assert "attack: the fresh-eye batch of F002 is attacked by r1 (r1), not r2" in problems
    assert cv.attack("F002", "angle 1", agent=R1, batch="fresh-eye", last=True) == []


# -- phase order ------------------------------------------------------------------


def _phase(cv: Converge) -> str:
    return protocol.slate_phase(_slate(cv))


def _cut_round(cv: Converge, when: str) -> None:
    confidence = "inferred" if when == "before" else "traced"
    assert cv.append("cut", CUTTER, claim="F001", round=1, when=when, confidence=confidence) == []
    assert cv.append("accept", FINDER, claim="F001", round=1, when=when) == []


@pytest.mark.parametrize(("cut", "escalate", "phases"), [
    ("both", True, ["find", "escalate", "cut-before", "attack", "cut-after", "cutoff"]),
    ("before", True, ["find", "escalate", "cut-before", "attack", "cutoff"]),
    ("after", False, ["find", "attack", "cut-after", "cutoff"]),
    ("none", True, ["find", "escalate", "attack", "cutoff"]),
])
def test_phase_order(cv: Converge, cut: str, escalate: bool, phases: list[str]) -> None:
    cv.init(config={"steps": {"cut": cut, "gap_hunt": False, "escalate": escalate},
                    "angles": {"disable": DISABLED}})
    cv.file()
    seen = [_phase(cv)]
    cv.cover()
    seen.append(_phase(cv))
    if escalate:
        assert cv.append("escalate", FINDER, claim="F001") == []
        seen.append(_phase(cv))
    if cut in ("before", "both"):
        _cut_round(cv, "before")
        seen.append(_phase(cv))
    cv.batch_1()
    assert _phase(cv) == "attack"
    cv.fresh_eye()
    seen.append(_phase(cv))
    if cut in ("after", "both"):
        _cut_round(cv, "after")
        seen.append(_phase(cv))
    assert seen == phases
