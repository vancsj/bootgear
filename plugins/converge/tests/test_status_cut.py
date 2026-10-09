"""`status` on steps slates (R16): the real cut state, the steps, caps and batch plan."""
from __future__ import annotations

import json

from conftest import CUTTER, FINDER, R1, R2, Converge


def _escalated(cv: Converge, *claims: str) -> None:
    cv.init(defaults=True)
    for cid in claims:
        cv.file()
        cv.ok("escalate", "s1", "--as", FINDER, "--claim", cid)


def test_cut_state_shows_once_a_cut_exists(cv: Converge) -> None:
    _escalated(cv, "F001")
    claim = cv.status()["by_id"]["F001"]
    assert claim["cut"] == "-" and claim["phase"] == "cut"
    assert claim["escalated"] is True and claim["parked"] is False
    cv.cut("F001", 1, CUTTER)
    claim = cv.status()["by_id"]["F001"]
    assert (claim["refute"], claim["cut"], claim["cut_round"]) == ("open", "open", 1)
    assert "F001 stage=cut refute=open round=0 cut=open cut_round=1" in cv.ok("status", "s1").stdout
    cv.accept("F001", 1)
    claim = cv.status()["by_id"]["F001"]
    assert claim["cut"] == "converged" and claim["phase"] == "refute"
    cv.refute("F001", 1, "boundary", R1, "downgraded", "--narrowed", "only on retry")
    cv.refute("F001", 1, "reachability", R2)
    claim = cv.status()["by_id"]["F001"]
    assert claim["cut"] == "open" and claim["cut_note"] == "stale after refute, round 1"


def test_status_json_prints_steps_caps_and_plan(cv: Converge) -> None:
    _escalated(cv)
    cv.file()
    cv.file(agent=R2, origin="gap-hunt")
    data = cv.status()
    assert data["steps"] == {"escalate": True, "early_cut": True, "gap_hunt": True}
    assert data["caps"] == {"batch_items": 30, "angles_per_claim": 5}
    assert data["plan"]["escalate"] == [[{"claim": "F001", "finder": FINDER},
                                         {"claim": "F002", "finder": R2}]]
    assert data["plan"]["cut"] == [[{"claim": "F001", "finder": FINDER},
                                    {"claim": "F002", "finder": R2}]]
    cv.ok("escalate", "s1", "--as", FINDER, "--claim", "F001")
    cv.cut_converge("F001")
    data = cv.status()
    assert data["plan"]["refute"] == [[{"claim": "F001", "finder": FINDER, "round": 1,
                                        "angles": 5}]]
    lines = cv.ok("status", "s1").stdout.splitlines()
    assert "PLAN escalate batch=1 F002" in lines
    assert "PLAN cut batch=1 F002" in lines
    assert "PLAN refute batch=1 F001x5" in lines


def test_legal_event_types_follow_the_phase(cv: Converge) -> None:
    _escalated(cv, "F001")
    assert {"cut", "escalate"} & set(cv.status()["legal_event_types"]) == {"cut"}
    cv.file()
    legal = set(cv.status()["legal_event_types"])
    assert {"cut", "escalate"} <= legal and "refute" not in legal
    cv.cut_converge("F001")
    legal = set(cv.status()["legal_event_types"])
    assert {"refute", "angle-na"} <= legal


def test_legacy_status_has_no_plan(cv: Converge) -> None:
    cv.init(legacy=True)
    cv.file()
    data = json.loads(cv.ok("status", "s1", "--json").stdout)
    assert not {"steps", "caps", "plan"} & set(data)
    assert not {"escalated", "parked", "phase"} & set(data["claims"][0])
    assert data["claims"][0]["cut"] == "-"


def test_converged_phases(cv: Converge) -> None:
    _escalated(cv, "F001")
    out = cv.ok("converged", "s1", "--phase", "cut", code=1).stdout
    assert "F001 phase=cut cut=open" in out
    out = cv.ok("converged", "s1", "--phase", "refute", code=1).stdout
    assert "F001 refute=open round=0" in out
    cv.cut("F001", 1, CUTTER, "rare", "cosmetic", "traced", "trivial", "--fix", "reword the label")
    cv.accept("F001", 1)
    assert "CONVERGED phase=refute" in cv.ok("converged", "s1", "--phase", "refute").stdout
    assert "CONVERGED phase=cut" in cv.ok("converged", "s1", "--phase", "cut").stdout


def test_converged_cut_next_line_follows_each_claim_phase(cv: Converge) -> None:
    _escalated(cv, "F001", "F002", "F003", "F004")
    cv.file()
    cv.cut_converge("F001")
    cv.cut("F002", 1, CUTTER)
    cv.cut("F004", 1, CUTTER)
    cv.rebut_cut("F004", "the retry path is guarded")
    lines = cv.ok("converged", "s1", "--phase", "cut", code=1).stdout.splitlines()
    assert "F001 phase=refute cut=converged" in lines
    assert "F005 phase=cut cut=open" in lines
    step = lines[-1]
    assert step.startswith("next: ")
    assert "continue the refuters with F001" in step
    assert "continue each claim's finder to accept or rebut F002" in step
    assert "continue the cutter with F003, F004" in step
    assert "continue each claim's finder to escalate F005" in step
    data = json.loads(cv.ok("converged", "s1", "--phase", "cut", "--json", code=1).stdout)
    assert "cutter with F001" not in data["next"]
    assert "cutter with F002" not in data["next"]
