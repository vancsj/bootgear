"""Grouped clean checks retain evidence and use the normal role and batch gates."""
from __future__ import annotations

import json
from typing import Any

import pytest
from converge import ledger, protocol

from conftest import BATCH_1, CUTTER, FINDER, MAIN, R1, R2, Converge


def checks(*angles: str) -> list[dict[str, str]]:
    return [{"angle": angle, "tell": f"tell for {angle}", "evidence": f"a.py:10 {angle}",
             "searches": f"rg {angle}", "positive_control": f"found {angle}"}
            for angle in angles]


def clean(cv: Converge, *angles: str, agent: str = R1, batch: int | str = 1,
          **extra: Any) -> list[str]:
    return cv.append("clean", agent, claim="F001", batch=batch, checks=checks(*angles), **extra)


def test_group_replays_each_check_with_its_evidence(cv: Converge) -> None:
    # Test standard R004: this event must work before role work can generate it.
    cv.ready()
    before = len(cv.events())
    assert clean(cv, *BATCH_1) == []
    events = cv.events()
    assert len(events) == before + 1
    assert events[-1]["event"] == "clean"
    assert events[-1]["checks"] == checks(*BATCH_1)
    claim = ledger.read(cv.path(), "s1").claims["F001"]
    assert claim.used_angles == set(BATCH_1)
    assert [row["angle"] for row in claim.state.attacks[1]] == list(BATCH_1)
    for row, check in zip(claim.state.attacks[1], checks(*BATCH_1), strict=True):
        assert all(row[key] == value for key, value in check.items())
        assert row["outcome"] == "clean"
        assert row["seq"] == events[-1]["seq"]
    assert protocol.next_batch(ledger.read(cv.path(), "s1"), claim) == "fresh-eye"


@pytest.mark.parametrize("command", ["clean", "act"])
def test_invalid_checks_report_all_problems_and_append_nothing(cv: Converge, command: str) -> None:
    cv.ready()
    rows = checks(BATCH_1[0], BATCH_1[0], BATCH_1[1])
    rows[0]["evidence"] = ""
    rows[2]["searches"] = ""
    value = {"slate": "s1", "source_seq": len(cv.events()), "role": R1,
             "action": "clean", "claim": "F001", "batch": 1, "checks": rows}
    path = cv.root / "invalid-group.json"
    path.write_text(json.dumps(value))
    before = cv.path().read_bytes()
    result = cv.ok(command, "s1", "--as", R1, "--input", str(path), code=2)
    assert "checks[0]" in result.stderr and "evidence" in result.stderr
    assert "duplicate" in result.stderr and BATCH_1[0] in result.stderr
    assert "checks[2]" in result.stderr and "searches" in result.stderr
    assert cv.path().read_bytes() == before


@pytest.mark.parametrize("agent", [FINDER, MAIN, R2])
def test_clean_keeps_role_checks(cv: Converge, agent: str) -> None:
    cv.ready()
    assert clean(cv, BATCH_1[0]) == []
    before = cv.path().read_bytes()
    problems = clean(cv, BATCH_1[1], agent=agent)
    assert any("clean:" in problem for problem in problems)
    assert cv.path().read_bytes() == before


def test_clean_refuter_cannot_cut_the_claim(cv: Converge) -> None:
    cv.ready(cut="after")
    assert clean(cv, *BATCH_1) == []
    assert clean(cv, "new route", agent=R2, batch="fresh-eye", last=True) == []
    assert "refuters and cutters are disjoint" in cv.cut("F001", 1, R1, code=2).stderr
    assert cv.cut("F001", 1, CUTTER).returncode == 0


def test_refuted_attack_stays_separate_from_clean_group(cv: Converge) -> None:
    cv.ready()
    refuted = checks(BATCH_1[0])[0]
    assert cv.append("attack", R1, claim="F001", batch=1, **refuted) == []
    assert clean(cv, *BATCH_1[1:]) == []
    slate = ledger.read(cv.path(), "s1")
    claim = slate.claims["F001"]
    assert protocol.batch_state(slate, claim, 1) == "awaiting-reply-1"
    first = protocol.first_refuted(claim, 1)
    assert first is not None and first["angle"] == BATCH_1[0]
    assert [event["event"] for event in cv.events()[-2:]] == ["attack", "clean"]
    assert "outcome" not in cv.events()[-2]


def test_fresh_eye_counts_checks_and_closes_only_after_the_final_check(cv: Converge) -> None:
    cv.ready(angles_per_claim=5)
    assert clean(cv, *BATCH_1) == []
    assert clean(cv, "route one", "route two", agent=R2, batch="fresh-eye", last=True) == []
    slate = ledger.read(cv.path(), "s1")
    claim = slate.claims["F001"]
    assert protocol.next_batch(slate, claim) is None
    assert len(claim.state.attacks["fresh-eye"]) == 2
    assert "last" not in claim.state.attacks["fresh-eye"][0]
    assert claim.state.attacks["fresh-eye"][-1]["last"] is True


def test_fresh_eye_group_cap_and_old_angle_are_atomic_refusals(cv: Converge) -> None:
    cv.ready()
    assert clean(cv, *BATCH_1) == []
    assert clean(cv, "route one", "route two", agent=R2, batch="fresh-eye") == []
    before = cv.path().read_bytes()
    problems = clean(cv, "route one", "three", "four", "five", "six", agent=R2,
                     batch="fresh-eye")
    assert any("already used" in problem for problem in problems)
    assert any("cap" in problem for problem in problems)
    assert cv.path().read_bytes() == before


def test_render_keeps_each_grouped_angles_evidence_visible(cv: Converge) -> None:
    cv.ready()
    assert clean(cv, *BATCH_1) == []
    report = cv.ok("render", "s1").stdout
    for row in checks(*BATCH_1):
        assert row["angle"] in report
        assert row["evidence"] in report
