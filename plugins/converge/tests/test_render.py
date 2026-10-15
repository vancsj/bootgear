"""The rendered report: summary line, Findings, Choices, Follow-up, Killed and Coverage."""
from __future__ import annotations

import json

from conftest import BATCH_1, CHOICE, FINDER, R1, Converge
from converge import ledger

FINDINGS = ("| rank | claim | lens | loc | text | impact | size | reach | rate | "
            "difficulty | status | cut | reason |")
FOLLOW_UP = ("| rank | claim | lens | loc | text | impact | size | reach | rate | "
             "difficulty | status | choice | reason |")


def _sections(out: str) -> dict[str, str]:
    return {part.split("\n", 1)[0].strip(): part.split("\n", 1)[1].strip()
            for part in out.split("## ")[1:]}


def _reply(cv: Converge, stance: str, evidence: str | None = None, cid: str = "F003") -> None:
    fields = {} if evidence is None else {"evidence": evidence,
                                          "evidence_sha256": ledger.evidence_hash(evidence)}
    assert cv.append("reply", FINDER, claim=cid, batch=1, stance=stance, **fields) == []


def _full_slate(cv: Converge) -> None:
    """F001 and F004 findings, F002 a follow-up, each with a choice; F003 killed after a
    disagree verdict."""
    cv.ready(cut="after", claims=4)
    for cid in ("F001", "F002", "F004"):
        cv.clean(cid)
    cv.batch_1("F003", refuted=(BATCH_1[0],))
    _reply(cv, "rebut", "b.py:4 passes None")
    assert cv.append("verdict", R1, claim="F003", batch=1, verdict="disagree",
                     evidence="b.py:4 is dead code") == []
    _reply(cv, "decline")
    cv.rate("F001", impact="wrong-output")
    cv.rate("F002", impact="cosmetic")
    cv.rate("F004", impact="data-loss", difficulty="cross-cutting",
            choice="idempotency key or single-shot write")


def test_render_after_cutoff(cv: Converge) -> None:
    _full_slate(cv)
    cv.ok("cutoff", "s1")
    out = cv.ok("render", "s1").stdout
    lines = out.splitlines()
    assert lines[:5] == ["# converge slate `s1`", "",
                         "fix-now=0 fixed=0 findings=2 follow-up=1 killed=1 converged=yes", "",
                         ("lenses: correctness, security · claims: 4 · phase: done · "
                         "cutoff: current")]
    sections = _sections(out)
    assert list(sections) == ["Findings", "Fix now", "Fixed", "Choices", "Follow-up", "Killed",
                              "Coverage"]
    assert sections["Findings"].splitlines() == [
        FINDINGS, "|" + "---|" * 13,
        ("| 1 | F004 | correctness | src/a.py:10 | claim 4 | data-loss | one | normal | 0 | "
        "cross-cutting | survived | no | report_if[0] |"),
        ("| 2 | F001 | correctness | src/a.py:10 | claim 1 | wrong-output | one | normal | 0 | "
        "cross-cutting | survived | no | report_if[0] |")]
    assert sections["Fix now"] == sections["Fixed"] == "None."
    assert sections["Choices"].splitlines() == [
        "- **F004** (finding) — idempotency key or single-shot write",
        f"- **F001** (finding) — {CHOICE}"]
    assert sections["Follow-up"].splitlines() == [
        FOLLOW_UP, "|" + "---|" * 13,
        ("| 3 | F002 | correctness | src/a.py:10 | claim 2 | cosmetic | one | normal | 0 | "
        f"cross-cutting | survived | {CHOICE} | no rule matched |")]
    assert sections["Killed"] == (
        f"- **F003** killed by r1 ({BATCH_1[0]}, batch 1) — claim 3 — evidence: read a.py:10 "
        "· verdict disagree: b.py:4 is dead code")
    assert sections["Coverage"].startswith("- **correctness** — ran: none · n/a: ")


def test_render_before_cutoff_shows_the_current_rows(cv: Converge) -> None:
    _full_slate(cv)
    out = cv.ok("render", "s1").stdout
    assert "findings=2 follow-up=1 killed=1 converged=no" in out
    assert "phase: cutoff · cutoff: none" in out


def test_render_empty_sections(cv: Converge) -> None:
    cv.ready(cut="none")
    cv.batch_1(refuted=(BATCH_1[0],))
    _reply(cv, "decline", cid="F001")
    cv.ok("cutoff", "s1")
    sections = _sections(cv.ok("render", "s1").stdout)
    assert (sections["Findings"], sections["Choices"], sections["Follow-up"]) == (
        "None.", "None.", "None.")
    assert sections["Killed"].startswith("- **F001** killed by r1 ")


def test_render_disputed_finding_is_not_converged(cv: Converge) -> None:
    cv.ready(cut="after")
    cv.batch_1(refuted=(BATCH_1[0],))
    _reply(cv, "rebut", "e1", cid="F001")
    assert cv.append("verdict", R1, claim="F001", batch=1, verdict="disagree",
                     evidence="b") == []
    _reply(cv, "rebut", "e2", cid="F001")
    cv.fresh_eye()
    cv.rate(impact="security")
    cv.ok("cutoff", "s1")
    out = cv.ok("render", "s1").stdout
    assert "findings=1 follow-up=0 killed=0 converged=no" in out
    assert ("| claim 1 | security | one | normal | 0 | cross-cutting | disputed | no | "
            "report_if[0] |") in out


def test_render_json_carries_the_markdown_and_choices(cv: Converge) -> None:
    _full_slate(cv)
    cv.ok("cutoff", "s1")
    data = json.loads(cv.ok("render", "s1", "--json").stdout)
    assert data["markdown"] == cv.ok("render", "s1").stdout
    assert data["choices"] == [{"claim": "F004", "result": "finding",
                                "choice": "idempotency key or single-shot write"},
                               {"claim": "F001", "result": "finding", "choice": CHOICE}]
    assert data["fix_now"] == []


def _choice_slate(cv: Converge) -> None:
    """Every claim carries a choice: F001 a finding, F002 unverified (cut before the attack),
    F003 cut after the attack."""
    cv.ready(cut="both", claims=3)
    cv.rate("F001", "before", impact="wrong-output", choice="split or patch")
    cv.rate("F002", "before", impact="cosmetic", choice="drop or keep")
    cv.rate("F003", "before", impact="wrong-output")
    for cid in ("F001", "F003"):
        cv.clean(cid)
    cv.rate("F001", impact="wrong-output", difficulty="redesign", choice="split or patch")
    cv.rate("F003", impact="cosmetic", difficulty="cross-cutting", choice="lock or queue")
    cv.ok("cutoff", "s1")


def test_choices_list_findings_only_and_follow_ups_keep_their_choice(cv: Converge) -> None:
    _choice_slate(cv)
    sections = _sections(cv.ok("render", "s1").stdout)
    assert sections["Choices"] == "- **F001** (finding) — split or patch"
    rows = {line.split(" | ")[1]: line for line in sections["Follow-up"].splitlines()[2:]}
    assert set(rows) == {"F002", "F003"}
    assert "| unverified | drop or keep | unverified |" in rows["F002"]
    assert "| survived | lock or queue | no rule matched |" in rows["F003"]


def test_render_json_choices_hold_findings_only(cv: Converge) -> None:
    _choice_slate(cv)
    data = json.loads(cv.ok("render", "s1", "--json").stdout)
    assert data["choices"] == [{"claim": "F001", "result": "finding", "choice": "split or patch"}]
