"""The plan: one row per open item of the current phase, in rank order, chunked by
`caps.batch_items`; each claim's open phase; and the plan in `status --json`."""
from __future__ import annotations

from typing import Any

from conftest import BATCH_1, CUTTER, DISABLED, FINDER, R1, R2, Converge
from converge import ledger, model, protocol


def _slate(cv: Converge) -> model.Slate:
    return ledger.read(cv.path(), "s1")


def _plan(cv: Converge) -> list[list[dict[str, Any]]]:
    return protocol.batch_plan(_slate(cv))


def _row(claim: str, action: str, role: str, batch: Any = None,
         angles: tuple[str, ...] = ()) -> dict[str, Any]:
    return {"claim": claim, "action": action, "agent_role": role, "batch": batch,
            "angles": list(angles)}


def _fresh_row(claim: str, role: str, used: tuple[str, ...]) -> dict[str, Any]:
    return {"claim": claim, "action": "attack", "agent_role": role, "batch": "fresh-eye",
            "angles": [], "used": list(used)}


def _strip_rule(plan: list[list[dict[str, Any]]]) -> list[list[dict[str, Any]]]:
    return [[{k: v for k, v in row.items() if k != "rule"} for row in chunk] for chunk in plan]


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
    assert _strip_rule(_plan(cv)) == [[_row("F001", "reply", "finder", 1),
                                       _fresh_row("F002", "r2", BATCH_1)]]
    assert cv.append("reply", FINDER, claim="F001", batch=1, stance="rebut", evidence="e",
                     evidence_sha256=ledger.evidence_hash("e")) == []
    assert _plan(cv)[0][0] == _row("F001", "verdict", "r1", 1)


def test_fresh_eye_row_has_empty_angles_and_used_list(cv: Converge) -> None:
    cv.ready()
    cv.batch_1()
    assert cv.attack("F001", "retry timing", agent=R2, batch="fresh-eye") == []
    [[row]] = _plan(cv)
    assert row["angles"] == []
    assert row["used"] == [*BATCH_1, "retry timing"]
    assert row["rule"]


def test_status_fixed_remaining_empty_is_not_nothing_to_attack(cv: Converge) -> None:
    cv.ready()
    cv.batch_1()
    assert cv.status()["by_id"]["F001"]["fixed_remaining"] == []
    assert _strip_rule(_plan(cv)) == [[_fresh_row("F001", R2, BATCH_1)]]


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
    assert protocol.claim_phase(slate, slate.claims["F001"]) == "attack"
    assert [(c.id, phase) for c, phase in slate.open_claims()] == [("F001", "attack"),
                                                                  ("F002", "cut-before")]


def test_status_json_prints_the_plan(cv: Converge) -> None:
    cv.ready(claims=2)
    data = cv.status()
    assert data["plan"] == _plan(cv)
    assert data["plan"][0][0] == _row("F001", "attack", "r1", 1, BATCH_1)
