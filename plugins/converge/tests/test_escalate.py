"""`escalate`: the finder's one chance to widen a claim before it is cut or refuted (R1, R8)."""
from __future__ import annotations

from conftest import CUTTER, FINDER, R1, R2, Converge
from converge import ledger

WIDER = {"wider": "every caller passing None loses the row", "evidence": "api.py:40 passes None"}


def _slate(cv: Converge, **steps: bool) -> None:
    cv.init(defaults=True, config={"steps": steps} if steps else None)
    cv.file()


def _claim(cv: Converge, cid: str = "F001"):
    return ledger.read(cv.path(), "s1").claims[cid]


def test_wider_text_replaces_the_claim_and_keeps_the_original(cv: Converge) -> None:
    _slate(cv)
    assert cv.append("escalate", FINDER, claim="F001", **WIDER) == []
    claim = _claim(cv)
    assert claim.text == WIDER["wider"] and claim.original == "x breaks y"
    assert claim.escalation is not None


def test_escalate_without_wider_text(cv: Converge) -> None:
    _slate(cv)
    assert cv.append("escalate", FINDER, claim="F001") == []
    assert _claim(cv).text == "x breaks y"


def test_wider_and_evidence_go_together(cv: Converge) -> None:
    _slate(cv)
    for fields in ({"wider": WIDER["wider"]}, {"evidence": WIDER["evidence"]}):
        problems = cv.append("escalate", FINDER, claim="F001", **fields)
        assert "escalate: `wider` and `evidence` are given together" in problems
    problems = cv.append("escalate", FINDER, claim="F001", wider=" ", evidence="x")
    assert "`wider` must be a non-empty string" in problems


def test_only_the_finder_escalates_once(cv: Converge) -> None:
    _slate(cv)
    assert "escalate: only F001's finder finder may escalate" in cv.append(
        "escalate", R1, claim="F001")
    assert cv.append("escalate", FINDER, claim="F001") == []
    assert "escalate: F001 is already escalated" in cv.append("escalate", FINDER, claim="F001")
    assert "unknown claim 'F009'" in cv.append("escalate", FINDER, claim="F009")


def test_escalate_comes_before_the_first_cut_and_refute(cv: Converge) -> None:
    _slate(cv, escalate=False, early_cut=False)
    cv.file()
    cv.refute("F001", 1, "boundary", R1)
    assert ("escalate: F001 is already cut or refuted; escalate comes before the first cut "
            "and the first refute") in cv.append("escalate", FINDER, claim="F001")
    cv.refute("F002", 1, "boundary", R1)
    cv.refute("F002", 1, "reachability", R2)
    cv.cut("F002", 1, CUTTER)
    assert ("escalate: F002 is already cut or refuted; escalate comes before the first cut "
            "and the first refute") in cv.append("escalate", FINDER, claim="F002")


def test_legacy_and_refute_only_slates_refuse_escalate(cv: Converge) -> None:
    cv.init(legacy=True)
    cv.file()
    assert ("escalate: this slate predates the steps config"
            in cv.append("escalate", FINDER, claim="F001"))
    cv.init("s2", "refute-only", "", defaults=True)
    cv.file("s2", agent="slate", lens="", angle="", origin="slate")
    assert "escalate: refute-only slates have no finder to escalate" in cv.append(
        "escalate", "slate", slate="s2", claim="F001")


def test_dead_claim_refuses_escalate(cv: Converge) -> None:
    _slate(cv, escalate=False, early_cut=False)
    cv.refute("F001", 1, "positive-control", R1, "killed")
    assert "F001 is killed; it accepts nothing" in cv.append("escalate", FINDER, claim="F001")


def test_escalate_step_gates_the_first_cut_and_refute(cv: Converge) -> None:
    _slate(cv)
    assert "cut: F001 needs an escalate event first" in cv.append(
        "cut", CUTTER, claim="F001", round=1)
    cv.init("s2", defaults=True, config={"steps": {"early_cut": False}})
    cv.file("s2")
    assert "refute: F001 needs an escalate event first" in cv.refute(
        "F001", 1, "boundary", R1, slate="s2", code=2).stderr
    assert cv.append("escalate", FINDER, slate="s2", claim="F001") == []
    cv.refute("F001", 1, "boundary", R1, slate="s2")


def test_escalate_step_off_needs_no_escalate(cv: Converge) -> None:
    _slate(cv, escalate=False)
    assert cv.append("cut", CUTTER, claim="F001", round=1) == []


def test_escalate_command(cv: Converge) -> None:
    _slate(cv)
    cv.file()
    out = cv.ok("escalate", "s1", "--as", FINDER, "--claim", "F001", "--wider", WIDER["wider"],
                "--evidence", WIDER["evidence"]).stdout
    assert out.startswith("ESCALATE seq=") and " F001 wider=yes" in out
    assert " F002 wider=no" in cv.ok("escalate", "s1", "--as", FINDER, "--claim", "F002").stdout
    assert cv.status()["by_id"]["F001"]["claim"] == WIDER["wider"]
    err = cv.refused("escalate", "s1", "--as", FINDER, "--claim", "F001", "--wider", "wider")
    assert "escalate: `wider` and `evidence` are given together" in err
