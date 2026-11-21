from __future__ import annotations

import json
from pathlib import Path

from workflow_output_test_support import (
    AFTER_ONLY,
    BATCH_1,
    FINDER,
    MAIN,
    PATCH,
    R2,
    Slate,
    _ok,
    _patch_review,
    _stamp,
)

from conftest import HOST


def test_shared_fix_now_flow(tmp_path: Path) -> None:
    slate = Slate(tmp_path)
    slate.init(config=AFTER_ONLY)
    slate.file("None crashes the parser")
    slate.cover()
    slate.batch_1()
    slate.check("retry timing", "--last", agent=R2, batch="fresh-eye")
    slate.cut("F001", "after", difficulty="local",
              extra=("--patch", PATCH, "--callers", "none", "--migration", "none"))
    slate.accept("F001", "after")
    out = slate.lines("cutoff")
    assert out[0].endswith(" fix-now=1 fixed=0 findings=0 follow-up=0 killed=0")
    assert out[1] == "F001 fix-now status=survived cut=no rank=1 reason=cheap (local)"
    data = json.loads(slate.ok("render", "--json").stdout)
    assert data["fix_now"] == [{"claim": "F001", "patch": PATCH}]
    assert data["difficulty_basis"] == "artifact"
    assert data["claims"][0]["artifact_patch_eligible"] is True
    task = tmp_path / "review.yaml"
    task.write_text(AFTER_ONLY)
    review = ("s2", "--dir", str(slate.dir))
    _ok(tmp_path, "init", *review, "--as", MAIN, "--lenses", "correctness",
        "--angles", str(slate.angles), "--project-root", str(tmp_path), "--config", str(task))
    for angle in ("changed-contract", "failure-path"):
        _ok(tmp_path, "angle-na", *review, "--as", FINDER, "--phase", "find",
            "--lens", "correctness", "--angle", angle, "--reason", "the patch has no I/O")
    _ok(tmp_path, "cutoff", *review)
    out = slate.lines("fix-check", "--as", MAIN, "--claim", "F001", "--outcome", "pass",
                      "--evidence", "pytest passes", "--review-slate", "s2")
    assert out[0].endswith(" F001 outcome=pass")
    assert out[-1] == "next: " + slate.cmd("cutoff s1 --dir {dir}")
    assert slate.status()["by_id"]["F001"]["fix_check"] == "pass"
    out = slate.lines("cutoff")
    assert out[0].endswith(" fix-now=0 fixed=1 findings=0 follow-up=0 killed=0")
    assert slate.status()["by_id"]["F001"]["result"] == "fixed"


def test_shared_fix_check_compares_against_last_cutoff_before_the_first_fix_check(
        tmp_path: Path) -> None:
    """Cutoffs at t0 and t2 precede the first fix-check and one at t4 follows it; review
    slates cut at t1 and t3 tell the t2 cutoff apart from the first and the latest."""
    slate = Slate(tmp_path)
    ledger = slate.dir / "s1.jsonl"
    slate.init(config=AFTER_ONLY)
    for text in ("None crashes the parser", "None crashes the printer"):
        slate.file(text)
    slate.cover()
    for claim in ("F001", "F002"):
        for angle in BATCH_1:
            slate.check(angle, claim=claim)
        slate.check("retry timing", "--last", agent=R2, batch="fresh-eye", claim=claim)
    for claim in ("F001", "F002"):
        slate.cut(claim, "after", difficulty="local",
                  extra=("--patch", PATCH, "--callers", "none", "--migration", "none"))
        slate.lines("accept", "--as", FINDER, "--claim", claim, "--when", "after", "--round", "1")
    slate.ok("cutoff")
    seq = _stamp(ledger, 0, "2026-01-01T00:00:00Z")
    _patch_review(tmp_path, slate, "early", "2026-01-01T00:00:01Z")
    slate.ok("angle-na", "--as", FINDER, "--phase", "find", "--lens", "correctness",
             "--angle", "failure-path", "--reason", "the fix adds no I/O")
    slate.ok("cutoff")
    baseline = seq = _stamp(ledger, seq, "2026-01-01T00:00:02Z")
    _patch_review(tmp_path, slate, "late", "2026-01-01T00:00:03Z")
    check = ("fix-check", "--as", MAIN, "--outcome", "pass", "--evidence", "pytest passes")
    err = slate.lines(*check, "--claim", "F001", "--review-slate", "early", code=2)
    assert f"s1's cutoff seq={baseline} (2026-01-01T00:00:02Z)" in " ".join(err)
    slate.ok(*check, "--claim", "F001", "--review-slate", "late")
    slate.ok("cutoff")
    _stamp(ledger, seq, "2026-01-01T00:00:04Z")
    err = slate.lines(*check, "--claim", "F002", "--review-slate", "early", code=2)
    assert (f"  - --review-slate: slate 'early''s cutoff (2026-01-01T00:00:01Z) is older than "
            f"s1's cutoff seq={baseline} (2026-01-01T00:00:02Z), its last before the first "
            "fix-check; re-review the patch") in err
    slate.ok(*check, "--claim", "F002", "--review-slate", "late")
    out = slate.lines("cutoff")
    assert out[0].endswith(" fix-now=0 fixed=2 findings=0 follow-up=0 killed=0")


def test_shared_cut_rate_help_points_to_the_evaluate_angles(tmp_path: Path) -> None:
    out = " ".join(_ok(tmp_path, "cut", "--help").stdout.split())
    assert "call sites" not in out and "production queries" not in out
    assert "--rate RATE the count an evaluate angle with field rate asks for" in out
    assert f"plugins/cli/bin/gear --host {HOST} converge converge angles " \
        "--tag evaluate --angles <file>)" in out
