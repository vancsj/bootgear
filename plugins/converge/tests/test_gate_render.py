"""Gate, coverage and render over complete slates."""
from __future__ import annotations

from conftest import Converge


def _full_slate(cv: Converge) -> None:
    cv.init()
    reported = cv.file(claim="None crashes the parser")
    cv.ok("find-run", "s1", "--as", "finder", "--lens", "correctness",
          "--angle", "changed-contract", "--tell", "signature changed", "--searches", "rg parse(",
          "--positive-control", "rg def parse finds it", "--result", reported)
    appendix = cv.file(claim="log line typo")
    killed = cv.file(claim="nobody calls legacy()")
    choice = cv.file(claim="retry loop duplicates writes")
    cv.ok("angle-na", "s1", "--as", "finder", "--phase", "find", "--angle",
          "failure-path", "--lens", "security", "--reason", "no I/O in the diff")
    for cid in (reported, appendix, choice):
        cv.quiet_round(cid, 1, ("boundary", "reachability"))
    cv.refute(killed, 1, "positive-control", "r1", "killed")
    cv.cut_converge(reported, "common", "wrong-behavior", "reproduced", "local")
    cv.cut_converge(appendix, "rare", "cosmetic", "traced", "trivial")
    cv.cut_converge(choice, "common", "data-loss", "traced", "cross-cutting",
                    extra=("--choice", "idempotency key or single-shot write"))


def _complete_find_coverage(cv: Converge) -> None:
    cv.ok("angle-na", "s1", "--as", "finder", "--phase", "find", "--angle",
          "failure-path", "--lens", "correctness", "--reason", "no I/O in the diff")
    cv.ok("angle-na", "s1", "--as", "finder", "--phase", "find", "--angle",
          "changed-contract", "--lens", "security", "--reason", "no contract change")


def test_gate_fails_until_complete(cv: Converge) -> None:
    cv.init()
    cv.file()
    out = cv("gate", "s1", "--dir", str(cv.dir), code=1).stdout
    assert "GATE fail s1" in out
    assert "lens correctness has missing find angles: changed-contract, failure-path" in out
    assert "lens security has missing find angles: changed-contract, failure-path" in out
    assert "F001 is open in refute" in out
    assert "no current cutoff" in out


def test_gate_passes_after_cutoff_and_fails_after_rebut(cv: Converge) -> None:
    _full_slate(cv)
    assert "no current cutoff" in cv("gate", "s1", "--dir", str(cv.dir), code=1).stdout
    _complete_find_coverage(cv)
    cv.ok("cutoff", "s1")
    assert "GATE ok s1" in cv("gate", "s1", "--dir", str(cv.dir)).stdout
    cv.ok("rebut", "s1", "--as", "finder", "--claim", "F002", "--stage", "cut",
          "--evidence", "it is shown to every user")
    out = cv("gate", "s1", "--dir", str(cv.dir), code=1).stdout
    assert "F002 is open in cut" in out and "no current cutoff" in out


def test_gate_refused_for_refute_only(cv: Converge) -> None:
    cv.init(mode="refute-only", lenses="")
    assert "refute-only slate has no cut stage" in cv("gate", "s1", "--dir", str(cv.dir), code=2).stderr


def test_coverage_command(cv: Converge) -> None:
    _full_slate(cv)
    out = cv.ok("coverage", "s1").stdout
    assert "LENS correctness ran=changed-contract na=- missing=failure-path" in out
    assert "LENS security ran=- na=failure-path missing=changed-contract" in out
    assert "NA security failure-path no I/O in the diff" in out


def test_render_full(cv: Converge) -> None:
    _full_slate(cv)
    before = cv.ok("render", "s1").stdout
    assert "## Live claims (no current cutoff)" in before
    _complete_find_coverage(cv)
    cv.ok("cutoff", "s1")
    out = cv.ok("render", "s1").stdout
    assert "cutoff: current" in out
    reported = out.split("## Reported")[1].split("## Choices")[0]
    assert "F001" in reported and "F004" in reported and "F002" not in reported
    assert "- **F004** (reported) — idempotency key or single-shot write" in out
    appendix = out.split("## Appendix")[1].split("## Killed")[0]
    assert "<details><summary>1 below the cutoff</summary>" in appendix and "F002" in appendix
    killed = out.split("## Killed / retracted")[1]
    assert "**F003** killed by r1 (positive-control, round 1)" in killed
    assert "- **correctness** — ran: changed-contract" in out
    assert "n/a: failure-path (no I/O in the diff)" in out


def test_render_refute_only(cv: Converge) -> None:
    cv.init(mode="refute-only", lenses="")
    for text in ("survives", "unsure", "too broad", "false", "no referent", "capped"):
        cv.file(agent="slate", lens="", angle="", origin="slate", claim=text)
    cv.quiet_round("F001", 1, ("boundary", "reachability"))
    cv.refute("F002", 1, "boundary", "r1", "inconclusive")
    cv.refute("F002", 1, "reachability", "r2")
    cv.refute("F003", 1, "boundary", "r1", "downgraded", "--narrowed", "only on empty input")
    cv.refute("F003", 1, "reachability", "r2")
    cv.quiet_round("F003", 2, ("provenance", "carve-out"))
    cv.refute("F004", 1, "inverse-reading", "r1", "killed")
    cv.refute("F005", 1, "real-referent", "r1", "retracted")
    attack = iter(("boundary", "reachability", "provenance", "carve-out", "dependents",
                   "positive-control", "deliberate", "point-in-time", "inverse-reading", "cited-but-unread"))
    for rnd in range(1, 6):
        cv.refute("F006", rnd, next(attack), "r1", "downgraded", "--narrowed", f"n{rnd}")
        cv.refute("F006", rnd, next(attack), "r2")
    cv.ok("converged", "s1", "--phase", "refute")
    out = cv.ok("render", "s1").stdout
    sections = {s.split("\n", 1)[0].strip(): s for s in out.split("## ")[1:]}
    assert "**F001** survives" in sections["Survived"]
    assert "**F002** unsure" in sections["Inconclusive"]
    assert "None." in sections["Unconverged"]
    assert "**F003** too broad → only on empty input (converged)" in sections["Downgraded"]
    assert "**F006** capped → n5 (unconverged)" in sections["Downgraded"]
    assert "**F004** killed" in sections["Killed"]
    assert "**F005** retracted" in sections["Retracted"]
    assert "## Reported" not in out and "## Coverage" not in out
