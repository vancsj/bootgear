"""Parking (R4): a converged `cosmetic` cut parks its claim; it is never refuted and is listed
as follow-up `unverified` with the cutter's `fix`."""
from __future__ import annotations

import json

from conftest import CUTTER, FINDER, R1, R2, Converge
from converge import ledger


def _cosmetic(cv: Converge, fix: str | None = "rename the label") -> list[str]:
    fields = {"severity": "cosmetic", "frequency": "rare"}
    if fix is not None:
        fields["fix"] = fix
    return cv.append("cut", CUTTER, claim="F001", round=1, **fields)


def _escalated(cv: Converge) -> None:
    cv.init(defaults=True)
    cv.file()
    assert cv.append("escalate", FINDER, claim="F001") == []


def test_cosmetic_cut_needs_a_fix(cv: Converge) -> None:
    _escalated(cv)
    assert "cut: a cosmetic cut needs a non-empty `fix`" in _cosmetic(cv, None)
    assert "`fix` must be a non-empty string" in _cosmetic(cv, " ")
    assert _cosmetic(cv) == []


def test_legacy_slate_refuses_fix(cv: Converge) -> None:
    cv.init(legacy=True)
    cv.file()
    cv.quiet_round("F001", 1, ("boundary", "reachability"))
    assert "cut: `fix` is recorded only on slates with a steps config" in _cosmetic(cv)
    assert _cosmetic(cv, None) == []


def test_parked_claim_is_never_refuted(cv: Converge) -> None:
    _escalated(cv)
    assert _cosmetic(cv) == []
    cv.accept("F001", 1)
    slate = ledger.read(cv.path(), "s1")
    assert slate.parked(slate.claims["F001"])
    err = cv.refute("F001", 1, "boundary", R1, code=2).stderr
    assert "refute: F001 is parked (a cosmetic cut); it is never refuted" in err


def test_rebut_challenges_a_parked_cut_only_at_stage_cut(cv: Converge) -> None:
    _escalated(cv)
    assert _cosmetic(cv) == []
    cv.accept("F001", 1)
    problems = cv.append("rebut", FINDER, claim="F001", stage="refute", evidence="it leaks data")
    assert "rebut: F001 is parked; challenge the cut with --stage cut" in problems
    cv.rebut_cut("F001", "the label is shown on the invoice total")
    slate = ledger.read(cv.path(), "s1")
    assert not slate.parked(slate.claims["F001"])
    cv.cut("F001", 2, CUTTER, "common", "wrong-behavior")


def test_cut_command_takes_a_fix(cv: Converge) -> None:
    _escalated(cv)
    err = cv.cut("F001", 1, CUTTER, "rare", "cosmetic", code=2).stderr
    assert "cut: a cosmetic cut needs a non-empty `fix`" in err
    cv.cut("F001", 1, CUTTER, "rare", "cosmetic", "traced", "trivial", "--fix", "rename the label")
    assert cv.events()[-1]["fix"] == "rename the label"


THREE_ATTACK = {"angles": {"disable": [
    "cited-but-unread", "point-in-time", "absent-vs-default", "downstream-consumer",
    "inverse-reading", "carve-out", "dependents", "positive-control", "inherited-bounds",
    "guarded-elsewhere", "deliberate", "real-referent"]}}


def _parked_and_exhausted(cv: Converge) -> None:
    """F001 parked by a cosmetic cut; F002 unconverged once its three angles are spent."""
    cv.init(defaults=True, config=THREE_ATTACK)
    cv.cover()
    cv.file(claim="label typo on the invoice")
    cv.file(claim="cache key ignores locale")
    for cid in ("F001", "F002"):
        cv.ok("escalate", "s1", "--as", FINDER, "--claim", cid)
    cv.cut("F001", 1, CUTTER, "rare", "cosmetic", "traced", "redesign", "--fix",
           "rename the label", "--choice", "rename or drop the label")
    cv.accept("F001", 1)
    cv.cut_converge("F002", "common", "degraded")
    cv.refute("F002", 1, "boundary", R1, "downgraded", "--narrowed", "only for fr-CA")
    cv.refute("F002", 1, "reachability", R2)
    cv.cut("F002", 2, CUTTER, "common", "degraded")
    cv.accept("F002", 2)
    cv.refute("F002", 2, "provenance", R1)


def test_parked_and_unconverged_claims_pass_the_gate(cv: Converge) -> None:
    _parked_and_exhausted(cv)
    status = cv.status()["by_id"]
    assert status["F001"]["parked"] and status["F002"]["refute"] == "unconverged"
    out = cv.ok("cutoff", "s1").stdout
    assert "F002 follow-up rank=1 reason=unconverged" in out
    assert "F001 follow-up rank=2 reason=unverified" in out
    assert "GATE ok s1" in cv("gate", "s1", "--dir", str(cv.dir)).stdout


def _section(markdown: str, title: str) -> str:
    return markdown.split(f"## {title}\n\n", 1)[1].split("\n\n", 1)[0]


def test_render_lists_follow_up_claims_apart_from_findings(cv: Converge) -> None:
    _parked_and_exhausted(cv)
    cv.ok("cutoff", "s1")
    markdown = cv.ok("render", "s1").stdout
    assert _section(markdown, "Follow-up").splitlines() == [
        "- **F002** unconverged — only for fr-CA — angles: boundary, provenance, reachability",
        "- **F001** unverified — label typo on the invoice — suggested fix: rename the label"]
    for title in ("Reported", "Choices", "Inconclusive / unconverged", "Appendix"):
        assert _section(markdown, title) == "None."
    assert markdown.index("## Choices") < markdown.index("## Follow-up") < markdown.index(
        "## Inconclusive / unconverged")
    rendered = json.loads(cv.ok("render", "s1", "--json").stdout)
    assert rendered["choices"] == []
