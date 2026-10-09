"""`batch_plan`: live eligible claims per step, in rank order, in batches of `caps.batch_items`."""
from __future__ import annotations

from conftest import (
    FINDER,
    R1,
    R2,
    Converge,
    add_claim,
    add_cut,
    add_refute,
    make_slate,
)
from converge import model


def _ids(batches: list[list[dict]]) -> list[list[str]]:
    return [[row["claim"] for row in batch] for batch in batches]


def _escalated(claim: model.Claim) -> None:
    claim.escalation = {"event": "escalate", "claim": claim.id}


def test_legacy_slate_has_an_empty_plan() -> None:
    slate = make_slate(legacy=True)
    add_claim(slate)
    assert model.batch_plan(slate) == {"escalate": [], "cut": [], "refute": [], "rebut": []}


def test_escalate_rows_are_unescalated_untouched_claims() -> None:
    slate = make_slate(batch_items=2)
    first, second, third = add_claim(slate), add_claim(slate, finder=R2), add_claim(slate)
    plan = model.batch_plan(slate)
    assert _ids(plan["escalate"]) == [[first.id, second.id], [third.id]]
    assert plan["escalate"][0][1] == {"claim": second.id, "finder": R2}
    _escalated(first)
    add_cut(slate, third)
    assert _ids(model.batch_plan(slate)["escalate"]) == [[second.id]]
    off = make_slate(steps={"escalate": False})
    add_claim(off)
    assert model.batch_plan(off)["escalate"] == []


def test_cut_rows_follow_rank_order() -> None:
    slate = make_slate()
    low, high = add_claim(slate), add_claim(slate)
    for claim in (low, high):
        _escalated(claim)
    add_cut(slate, low, "cosmetic", accept=False)
    add_cut(slate, high, "security", accept=False)
    assert _ids(model.batch_plan(slate)["cut"]) == [[high.id, low.id]]


def _refute_ready(slate: model.Slate, n: int) -> list[model.Claim]:
    claims = []
    for _ in range(n):
        claim = add_claim(slate)
        _escalated(claim)
        add_cut(slate, claim)
        claims.append(claim)
    return claims


def test_refute_angles_split_the_batch() -> None:
    slate = make_slate(attack=8)
    _refute_ready(slate, 7)
    batch = model.batch_plan(slate)["refute"][0]
    assert [row["angles"] for row in batch] == [5, 5, 4, 4, 4, 4, 4]
    assert all(row["round"] == 1 for row in batch)
    assert set(batch[0]) == {"claim", "finder", "round", "angles"}


def test_refute_angles_capped_per_claim_and_by_unused_angles() -> None:
    slate = make_slate(attack=3)
    claims = _refute_ready(slate, 2)
    plan = model.batch_plan(slate)["refute"]
    assert [row["angles"] for row in plan[0]] == [3, 3]
    add_refute(slate, claims[0], 1, "boundary")
    row = model.batch_plan(slate)["refute"][0][0]
    assert row["claim"] == claims[0].id and row["round"] == 1 and row["angles"] == 2


def test_many_claims_split_into_batches() -> None:
    slate = make_slate(batch_items=30)
    _refute_ready(slate, 40)
    plan = model.batch_plan(slate)["refute"]
    assert [len(batch) for batch in plan] == [30, 10]
    assert {row["angles"] for row in plan[0]} == {1}
    assert {row["angles"] for row in plan[1]} == {3}


def test_next_round_after_a_complete_round() -> None:
    slate = make_slate()
    (claim,) = _refute_ready(slate, 1)
    add_refute(slate, claim, 1, "boundary", "downgraded")
    add_refute(slate, claim, 1, "reachability")
    plan = model.batch_plan(slate)
    assert _ids(plan["rebut"]) == [[claim.id]]
    assert plan["refute"] == [] and _ids(plan["cut"]) == [[claim.id]]
    add_cut(slate, claim)
    plan = model.batch_plan(slate)
    assert plan["refute"][0][0]["round"] == 2
    claim.refute_pending = 1
    assert model.batch_plan(slate)["rebut"] == []


def test_parked_and_dead_claims_leave_the_plan() -> None:
    slate = make_slate()
    parked = add_claim(slate)
    _escalated(parked)
    add_cut(slate, parked, "cosmetic", fix="reword")
    dead = add_claim(slate)
    _escalated(dead)
    add_cut(slate, dead)
    add_refute(slate, dead, 1, "boundary", "killed")
    plan = model.batch_plan(slate)
    assert not any(plan.values())


def test_refute_round_holds_at_most_angles_per_claim_events(cv: Converge) -> None:
    cv.init(defaults=True, config={"caps": {"angles_per_claim": 2}})
    cv.file()
    assert cv.append("escalate", FINDER, claim="F001") == []
    cv.cut_converge("F001")
    cv.quiet_round("F001", 1, ("boundary", "reachability"))
    err = cv.refute("F001", 1, "provenance", R1, code=2).stderr
    assert "refute: round 1 of F001 already holds 2 refute events (caps.angles_per_claim 2)" in err


def test_rebut_row_leaves_after_an_accepted_re_cut() -> None:
    slate = make_slate()
    (claim,) = _refute_ready(slate, 1)
    add_refute(slate, claim, 1, "boundary", "downgraded")
    add_refute(slate, claim, 1, "reachability")
    assert _ids(model.batch_plan(slate)["rebut"]) == [[claim.id]]
    add_cut(slate, claim, accept=False)
    assert _ids(model.batch_plan(slate)["rebut"]) == [[claim.id]]
    claim.accepted_round = claim.cut_round
    assert model.batch_plan(slate)["rebut"] == []
