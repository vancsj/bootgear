"""The `fix-check` event: after the cutoff, the caller that applied a fix-now patch records
whether the patch passed its checks and a patch-only re-review slate."""
from __future__ import annotations

from typing import Any

from conftest import BATCH_1, DISABLED, FINDER, MAIN, R2, Converge
from converge import ledger, model, protocol
from test_effort import cheap, patch

CHECKS = "pytest and quality/check.py pass"


def _slate(cv: Converge) -> model.Slate:
    return ledger.read(cv.path(), "s1")


def _results(cv: Converge) -> dict[str, tuple[str, str]]:
    return {row.claim.id: (row.result, row.reason)
            for row in protocol.compute_cutoff(_slate(cv))}


def _fix_now(cv: Converge, *ratings: dict[str, Any]) -> None:
    """One claim per rating, attacked and rated after the attack, then the cutoff."""
    ids = cv.ready(cut="after", claims=len(ratings))
    for cid in ids:
        cv.clean(cid)
    for cid, rating in zip(ids, ratings, strict=True):
        cv.rate(cid, **rating)
    cv.ok("cutoff", "s1")


def _review(cv: Converge, slate: str, *, finding: bool = False, cutoff: bool = True) -> None:
    """A patch-only re-review slate; with `finding`, one claim on another file reported."""
    task = {"steps": {"cut": "none", "gap_hunt": False, "escalate": False},
            "angles": {"disable": DISABLED}}
    cv.init(slate, "correctness,security", MAIN, config=task)
    if finding:
        cv.file(slate=slate, claim="the patch drops the None guard")
    cv.cover(slate=slate)
    if finding:
        for angle in BATCH_1:
            assert cv.attack("F001", angle, slate=slate) == []
        assert cv.attack("F001", "retry timing", agent=R2, batch="fresh-eye", last=True,
                         slate=slate) == []
    if cutoff:
        cv.ok("cutoff", slate)


def _check(cv: Converge, outcome: str, *extra: str, claim: str = "F001", agent: str = MAIN,
           code: int = 0) -> Any:
    return cv.ok("fix-check", "s1", "--as", agent, "--claim", claim, "--outcome", outcome,
                 "--evidence", CHECKS, *extra, code=code)


def test_fix_check_pass_needs_clean_review_slate(cv: Converge) -> None:
    _fix_now(cv, cheap(patch(lines=4)))
    err = _check(cv, "pass", code=2).stderr
    assert "fix-check: outcome pass needs `review_slate`" in err
    assert ("fix-check: `review_slate` must name another slate than s1"
            in _check(cv, "pass", "--review-slate", "s1", code=2).stderr)
    assert ("--review-slate: no slate 'r1-review' in"
            in _check(cv, "pass", "--review-slate", "r1-review", code=2).stderr)
    _review(cv, "open-review", cutoff=False)
    assert ("--review-slate: slate 'open-review' has no current cutoff"
            in _check(cv, "pass", "--review-slate", "open-review", code=2).stderr)
    _review(cv, "found", finding=True)
    err = _check(cv, "pass", "--review-slate", "found", code=2).stderr
    assert "--review-slate: slate 'found' holds findings (F001)" in err
    assert err.splitlines()[-1].startswith("next: record --outcome fail")
    _review(cv, "clean")
    out = _check(cv, "pass", "--review-slate", "clean").stdout.splitlines()
    assert out[0].startswith("FIX-CHECK seq=") and out[0].endswith(" F001 outcome=pass")
    assert out[-1] == f"next: converge cutoff s1 --dir {cv.dir}"
    assert _results(cv) == {"F001": ("fixed", "fix-check passed")}


def test_fix_check_fail_falls_back(cv: Converge) -> None:
    _fix_now(cv, cheap(patch(lines=4)), cheap(patch(lines=4), impact="cosmetic"))
    assert _results(cv) == {"F001": ("fix-now", "cheap (local)"),
                            "F002": ("fix-now", "cheap (local)")}
    _check(cv, "fail")
    _check(cv, "fail", claim="F002")
    assert _results(cv) == {"F001": ("finding", "fix-check failed"),
                            "F002": ("follow-up", "fix-check failed")}


def test_fix_check_once_per_claim(cv: Converge) -> None:
    _fix_now(cv, cheap(patch(lines=4)), {"impact": "security"})
    assert ("fix-check: F002's cutoff result is finding; fix-check takes a fix-now claim"
            in _check(cv, "fail", claim="F002", code=2).stderr)
    assert ("fix-check: finder filed F001 and may not check its fix"
            in _check(cv, "fail", agent=FINDER, code=2).stderr)
    assert "`outcome` must be one of pass, fail; got 'maybe'" in _check(
        cv, "maybe", code=2).stderr
    _check(cv, "fail")
    assert ("fix-check: F001 already has a fix-check; a fix is checked once"
            in _check(cv, "fail", code=2).stderr)


def test_fix_check_needs_a_cutoff(cv: Converge) -> None:
    ids = cv.ready(cut="after")
    cv.clean(ids[0])
    cv.rate(ids[0], **cheap(patch(lines=4)))
    assert ("fix-check: the slate has no cutoff event; run `converge cutoff` first"
            in _check(cv, "fail", code=2).stderr)


def test_fix_check_reopens_cutoff(cv: Converge) -> None:
    _fix_now(cv, cheap(patch(lines=4)))
    assert protocol.slate_phase(_slate(cv)) == "done"
    _review(cv, "clean")
    _check(cv, "pass", "--review-slate", "clean")
    data = cv.status()
    assert (data["phase"], data["cutoff"]) == ("cutoff", "stale")
    out = cv.ok("cutoff", "s1").stdout.splitlines()
    assert out[0].endswith("fix-now=0 fixed=1 findings=0 follow-up=0 killed=0")
    assert "F001 fixed status=survived cut=no rank=1 reason=fix-check passed" in out
    rendered = cv.ok("render", "s1").stdout
    assert "fix-now=0 fixed=1 findings=0" in rendered
    fixed = rendered.split("## Fixed\n\n", 1)[1].split("\n\n", 1)[0].splitlines()
    assert fixed[2] == ("| 1 | F001 | correctness | src/a.py:10 | claim 1 | wrong-output | "
                        "normal | local | 4 |")
    assert cv("converged", "s1", "--dir", str(cv.dir)).stdout.startswith("CONVERGED")


def test_status_json_carries_result_and_fix_check(cv: Converge) -> None:
    ids = cv.ready(cut="after")
    cv.clean(ids[0])
    cv.rate(ids[0], **cheap(patch(lines=4)))
    claim = cv.status()["by_id"]["F001"]
    assert "result" not in claim and claim["fix_check"] == "none"
    cv.ok("cutoff", "s1")
    claim = cv.status()["by_id"]["F001"]
    assert (claim["result"], claim["fix_check"]) == ("fix-now", "none")
    _review(cv, "clean")
    _check(cv, "pass", "--review-slate", "clean")
    claim = cv.status()["by_id"]["F001"]
    assert (claim["result"], claim["fix_check"]) == ("fix-now", "pass")
    cv.ok("cutoff", "s1")
    assert cv.status()["by_id"]["F001"]["result"] == "fixed"


def test_fix_check_pass_refuses_review_older_than_cutoff(cv: Converge, monkeypatch: Any) -> None:
    monkeypatch.setattr(ledger, "now", lambda: "2026-01-01T00:00:00Z")
    _review(cv, "early")
    monkeypatch.setattr(ledger, "now", lambda: "2026-01-01T00:00:01Z")
    _fix_now(cv, cheap(patch(lines=4)))
    err = _check(cv, "pass", "--review-slate", "early", code=2).stderr
    seq = [e["seq"] for e in cv.events() if e["event"] == "cutoff"][-1]
    assert ("--review-slate: slate 'early''s cutoff (2026-01-01T00:00:00Z) is older than "
            f"s1's cutoff seq={seq} (2026-01-01T00:00:01Z), its last before the first "
            "fix-check; re-review the patch" in err)


def test_fix_check_pass_compares_against_last_cutoff_before_the_first_fix_check(
        cv: Converge, monkeypatch: Any) -> None:
    """Cutoffs at t0 and t2 precede the first fix-check and one at t4 follows it; review
    slates cut at t1 and t3 tell the t2 cutoff apart from the first and the latest."""
    def at(second: int) -> None:
        monkeypatch.setattr(ledger, "now", lambda: f"2026-01-01T00:00:0{second}Z")

    at(0)
    _fix_now(cv, cheap(patch(lines=4)), cheap(patch(lines=4), impact="cosmetic"))
    at(1)
    _review(cv, "early")
    at(2)
    cv.ok("angle-na", "s1", "--as", FINDER, "--phase", "find", "--angle", "failure-path",
          "--lens", "correctness", "--reason", "the fix adds no I/O")
    cv.ok("cutoff", "s1")
    baseline = [e["seq"] for e in cv.events() if e["event"] == "cutoff"][-1]
    at(3)
    _review(cv, "late")
    _check(cv, "pass", "--review-slate", "late")
    at(4)
    cv.ok("cutoff", "s1")
    err = _check(cv, "pass", "--review-slate", "early", claim="F002", code=2).stderr
    assert (f"s1's cutoff seq={baseline} (2026-01-01T00:00:02Z), its last before the first "
            "fix-check" in err)
    _check(cv, "pass", "--review-slate", "late", claim="F002")
    cv.ok("cutoff", "s1")
    assert _results(cv) == {"F001": ("fixed", "fix-check passed"),
                            "F002": ("fixed", "fix-check passed")}


def test_rate_help_points_to_the_evaluate_angles(cv: Converge) -> None:
    out = cv("cut", "--help").stdout
    assert "call sites" not in out and "production queries" not in out
    assert "converge angles --tag evaluate --angles <file>" in " ".join(out.split())
