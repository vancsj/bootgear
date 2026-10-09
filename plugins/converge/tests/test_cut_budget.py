"""Cut-round budget on steps slates (R15): first cuts, stale re-cuts and rebut re-cuts share
`caps.cut_rounds`; a rebut --stage refute or a dependency reset keeps the cut rounds."""
from __future__ import annotations

from conftest import CUTTER, FINDER, R1, R2, Converge


def _escalate(cv: Converge, *claims: str) -> None:
    for cid in claims:
        assert cv.append("escalate", FINDER, claim=cid) == []


def _downgrade_round(cv: Converge, rnd: int, angles: tuple[str, str]) -> None:
    cv.refute("F001", rnd, angles[0], R1, "downgraded", "--narrowed", f"narrower {rnd}")
    cv.refute("F001", rnd, angles[1], R2)


def test_stale_cut_at_the_cap_is_capped_and_reported(cv: Converge) -> None:
    cv.init(defaults=True, config={"caps": {"cut_rounds": 2}})
    cv.cover()
    cv.file()
    _escalate(cv, "F001")
    cv.cut_converge("F001", "common", "degraded")
    _downgrade_round(cv, 1, ("boundary", "reachability"))
    cv.cut("F001", 2, CUTTER, "common", "degraded")
    cv.accept("F001", 2)
    _downgrade_round(cv, 2, ("provenance", "carve-out"))
    claim = cv.status()["by_id"]["F001"]
    assert claim["cut"] == "capped" and claim["cut_round"] == 2
    assert "exceeds caps.cut_rounds 2" in cv.cut("F001", 3, CUTTER, code=2).stderr
    cv.quiet_round("F001", 3, ("dependents", "deliberate"))
    assert "F001 reported rank=1 reason=cut-capped" in cv.ok("cutoff", "s1").stdout


def test_rebut_refute_keeps_the_cut_rounds_and_makes_the_cut_stale(cv: Converge) -> None:
    cv.init(defaults=True)
    cv.file()
    _escalate(cv, "F001")
    cv.cut_converge("F001")
    cv.quiet_round("F001", 1, ("boundary", "reachability"))
    cv.ok("rebut", "s1", "--as", FINDER, "--claim", "F001", "--stage", "refute",
          "--evidence", "the retry path skips the guard")
    claim = cv.status()["by_id"]["F001"]
    assert claim["stage"] == "refute" and claim["cut_round"] == 1 and claim["cut"] == "open"
    assert "needs a converged cut first" in cv.refute("F001", 2, "provenance", R1,
                                                      code=2).stderr
    cv.cut("F001", 2, CUTTER)
    cv.accept("F001", 2)
    cv.quiet_round("F001", 2, ("provenance", "carve-out"))


def test_dependency_reset_keeps_the_cut_rounds(cv: Converge) -> None:
    cv.init(defaults=True)
    cv.file()
    cv.file(extra=("--depends", "F001"))
    _escalate(cv, "F001", "F002")
    cv.cut_converge("F001")
    cv.cut_converge("F002")
    cv.quiet_round("F002", 1, ("boundary", "reachability"))
    _downgrade_round(cv, 1, ("boundary", "reachability"))
    dependent = cv.status()["by_id"]["F002"]
    assert dependent["reopened"] and dependent["cut_round"] == 1 and dependent["cut"] == "open"
    cv.cut("F002", 2, CUTTER)


def test_choice_required_at_every_cut(cv: Converge) -> None:
    cv.init(defaults=True)
    cv.file()
    _escalate(cv, "F001")
    err = cv.cut("F001", 1, CUTTER, "common", "wrong-behavior", "traced", "redesign",
                 code=2).stderr
    assert "cut: F001 has difficulty redesign; a non-empty `choice` is required" in err
    cv.cut("F001", 1, CUTTER, "common", "wrong-behavior", "traced", "redesign",
           "--choice", "split the table or keep one")
