"""The plan: one row per open item of the current phase, in rank order, chunked by
`caps.batch_items`; each claim's open phase; and the plan in `status --json`."""
from __future__ import annotations

from typing import Any

from conftest import BATCH_1, CUTTER, DISABLED, FINDER, R1, R2, Converge
from converge import ledger, model


def _slate(cv: Converge) -> model.Slate:
    return ledger.read(cv.path(), "s1")


def _plan(cv: Converge) -> list[list[dict[str, Any]]]:
    return model.batch_plan(_slate(cv))


def _row(claim: str, action: str, role: str, batch: Any = None,
         angles: tuple[str, ...] = ()) -> dict[str, Any]:
    return {"claim": claim, "action": action, "agent_role": role, "batch": batch,
            "angles": list(angles)}


def test_escalate_rows_name_each_claims_finder(cv: Converge) -> None:
    cv.init(config={"steps": {"cut": "both", "gap_hunt": True, "escalate": True},
                    "angles": {"disable": DISABLED}})
    cv.file()
    assert _plan(cv) == []
    cv.cover()
    cv.file(agent=R2, origin="gap-hunt")
    assert _plan(cv) == [[_row("F001", "escalate", "finder"), _row("F002", "escalate", "r2")]]


def test_rows_are_chunked_by_batch_items(cv: Converge) -> None:
    cv.ready(cut="before", claims=3, escalate=False, batch_items=2)
    assert _plan(cv) == [[_row("F001", "cut-before", "cutter"),
                          _row("F002", "cut-before", "cutter")],
                         [_row("F003", "cut-before", "cutter")]]


def test_cut_rows_follow_rank_order_and_the_finder_answers(cv: Converge) -> None:
    cv.ready(cut="before", claims=3)
    assert cv.append("cut", CUTTER, claim="F002", round=1, when="before",
                     confidence="inferred", severity="security") == []
    assert cv.append("cut", CUTTER, claim="F003", round=1, when="before",
                     confidence="inferred", severity="degraded") == []
    assert _plan(cv) == [[_row("F002", "accept", "finder"), _row("F003", "accept", "finder"),
                          _row("F001", "cut-before", "cutter")]]


def test_attack_rows(cv: Converge) -> None:
    cv.ready(claims=2)
    assert cv.attack("F001", BATCH_1[0], outcome="refuted") == []
    assert cv.append("angle-na", R1, phase="attack", angle=BATCH_1[1], claim="F001",
                     reason="no time window") == []
    assert _plan(cv) == [[_row("F001", "attack", "r1", 1, BATCH_1[2:]),
                          _row("F002", "attack", "r1", 1, BATCH_1)]]
    for angle in BATCH_1[2:]:
        assert cv.attack("F001", angle) == []
    cv.batch_1("F002")
    assert _plan(cv) == [[_row("F001", "reply", "finder", 1),
                          _row("F002", "attack", "r2", "fresh-eye", (*BATCH_1,))]]
    assert cv.append("reply", FINDER, claim="F001", batch=1, stance="rebut", evidence="e",
                     evidence_sha256=ledger.evidence_hash("e")) == []
    assert _plan(cv)[0][0] == _row("F001", "verdict", "r1", 1)


def test_fresh_eye_row_lists_the_angles_used(cv: Converge) -> None:
    cv.ready()
    cv.batch_1()
    assert cv.attack("F001", "retry timing", agent=R2, batch="fresh-eye") == []
    assert _plan(cv) == [[_row("F001", "attack", "r2", "fresh-eye",
                               (*BATCH_1, "retry timing"))]]


def test_cut_after_rows_and_an_empty_plan_at_cutoff(cv: Converge) -> None:
    cv.ready(cut="after")
    cv.clean()
    assert _plan(cv) == [[_row("F001", "cut-after", "cutter")]]
    cv.rate("F001")
    assert _plan(cv) == []


def test_each_claims_open_phase(cv: Converge) -> None:
    cv.ready(cut="before", claims=2)
    cv.rate("F001", "before", frequency="common", severity="wrong-behavior")
    slate = _slate(cv)
    assert slate.phase(slate.claims["F001"]) == "attack"
    assert [(c.id, phase) for c, phase in slate.open_claims()] == [("F001", "attack"),
                                                                  ("F002", "cut-before")]


def test_status_json_prints_the_plan(cv: Converge) -> None:
    cv.ready(claims=2)
    data = cv.status()
    assert data["plan"] == _plan(cv)
    assert data["plan"][0][0] == _row("F001", "attack", "r1", 1, BATCH_1)
