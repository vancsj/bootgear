"""`escalate`: the finder's one chance to widen a claim before it is cut or attacked."""
from __future__ import annotations

from conftest import BATCH_1, CUTTER, DISABLED, FINDER, R1, Converge
from converge import ledger, protocol

WIDER = {"wider": "every caller passing None loses the row", "evidence": "api.py:40 passes None"}


def _slate(cv: Converge) -> None:
    cv.init()
    cv.file()
    cv.cover()


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


def test_escalate_command(cv: Converge) -> None:
    cv.init()
    cv.file()
    cv.file()
    cv.cover()
    out = cv.ok("escalate", "s1", "--as", FINDER, "--claim", "F001", "--wider", WIDER["wider"],
                "--evidence", WIDER["evidence"]).stdout
    assert out.startswith("ESCALATE seq=") and " F001 wider=yes" in out
    assert " F002 wider=no" in cv.ok("escalate", "s1", "--as", FINDER, "--claim", "F002").stdout
    assert cv.status()["by_id"]["F001"]["claim"] == WIDER["wider"]
    err = cv.refused("escalate", "s1", "--as", FINDER, "--claim", "F001", "--wider", "wider")
    assert "escalate: `wider` and `evidence` are given together" in err


def test_no_cut_or_attack_before_every_claim_is_escalated(cv: Converge) -> None:
    cv.init(config={"steps": {"cut": "both", "gap_hunt": False, "escalate": True},
                    "angles": {"disable": DISABLED}})
    cv.file()
    cv.file()
    cv.cover()
    assert cv.append("escalate", FINDER, claim="F001") == []
    assert ("cut: the slate is in phase escalate; cut needs phase cut-before"
            in cv.append("cut", CUTTER, claim="F001", round=1, when="before",
                         confidence="inferred"))
    assert ("attack: the slate is in phase escalate; attack needs phase attack"
            in cv.attack("F001", BATCH_1[0]))
    assert cv.append("escalate", FINDER, claim="F002") == []
    assert protocol.slate_phase(ledger.read(cv.path(), "s1")) == "cut-before"


def test_escalate_is_not_needed_when_the_step_is_off(cv: Converge) -> None:
    cv.ready(escalate=False)
    assert protocol.slate_phase(ledger.read(cv.path(), "s1")) == "attack"
    assert cv.attack("F001", BATCH_1[0]) == []
    assert ("escalate: the slate is in phase attack; escalate needs phase escalate"
            in cv.append("escalate", FINDER, claim="F001"))
