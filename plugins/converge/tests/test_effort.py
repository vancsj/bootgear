"""Effort: the patch measure, the after-cut cheap limits and difficulty classes, and the
`fix-now` result of gate 2."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from conftest import BATCH_1, CUTTER, FINDER, R1, Converge
from converge import config as config_mod
from converge import effort, ledger, model, protocol

GLOBS = config_mod.DEFAULTS["cutoff"]["cheap"]["test_globs"]


def patch(path: str = "src/a.py", lines: int = 1, header: str | None = None) -> str:
    """A git diff adding `lines` lines to `path`; `header` replaces the `+++ ` path."""
    new = header if header is not None else f"b/{path}"
    return (f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ {new}\n"
            f"@@ -0,0 +1,{lines} @@\n" + "+x = 1\n" * lines)


def cheap(text: str | None = None, difficulty: str = "local", **extra: Any) -> dict[str, Any]:
    """After-cut fields for a cheap fix of the `ready` claim's loc `src/a.py`."""
    return {"difficulty": difficulty, "patch": patch() if text is None else text,
            "callers": "none", "migration": "none", "choice": None, **extra}


def _slate(cv: Converge) -> model.Slate:
    return ledger.read(cv.path(), "s1")


def _results(cv: Converge) -> dict[str, tuple[str, str]]:
    return {row.claim.id: (row.result, row.reason)
            for row in protocol.compute_cutoff(_slate(cv))}


def _attacked(cv: Converge, claims: int = 1, **config: Any) -> list[str]:
    ids = cv.ready(cut="after", claims=claims, config=config or None)
    for cid in ids:
        cv.clean(cid)
    return ids


def _cut(cv: Converge, cid: str = "F001", rnd: int = 1, **fields: Any) -> list[str]:
    return cv.append("cut", CUTTER, claim=cid, round=rnd, when="after", **fields)


# -- measure ---------------------------------------------------------------------------


def test_effort_measure() -> None:
    assert effort.measure(patch(lines=3), GLOBS) == {
        "files": 1, "test_files": 0, "lines": 3, "paths": ["src/a.py"]}
    both = patch(lines=10) + patch("tests/test_a.py", lines=2)
    assert effort.measure(both, GLOBS) == {
        "files": 1, "test_files": 1, "lines": 12, "paths": ["src/a.py"]}
    assert effort.measure(patch(lines=11), GLOBS)["lines"] == 11
    changed = ("diff --git a/src/a.py b/src/a.py\n--- a/src/a.py\n+++ b/src/a.py\n"
               "@@ -3,3 +3,3 @@\n ctx\n--- removed line that looks like a header\n+y = 2\n ctx\n")
    assert effort.measure(changed, GLOBS)["lines"] == 2
    other = effort.measure(patch("src/b.py"), GLOBS)
    assert other["paths"] == ["src/b.py"]
    renamed = ("diff --git a/src/a.py b/src/c.py\nsimilarity index 90%\n"
               "rename from src/a.py\nrename to src/c.py\n")
    with pytest.raises(effort.EffortError, match="rename"):
        effort.measure(renamed, GLOBS)
    binary = ("diff --git a/logo.png b/logo.png\n"
              "Binary files a/logo.png and b/logo.png differ\n")
    with pytest.raises(effort.EffortError, match="binary"):
        effort.measure(binary, GLOBS)
    with pytest.raises(effort.EffortError, match="not a unified diff"):
        effort.measure("change line 10 to x = 1", GLOBS)


def test_default_test_globs_classify_test_files() -> None:
    for path in ("tests/test_a.py", "src/test_a.py", "pkg/a_test.go", "web/a.test.ts",
                 "web/a.spec.ts", "a/tests/helpers.py"):
        assert effort.is_test(path, GLOBS), path
    for path in ("src/a.py", "src/testing.py", "a.py"):
        assert not effort.is_test(path, GLOBS), path


def test_patch_path_normalization(tmp_path: Path) -> None:
    root = tmp_path / "project"
    target = root / "src" / "a.py"
    relative = effort.header_path("b/src/a.py")
    assert relative == "src/a.py"
    assert effort.same_file(relative, "src/a.py", root)
    assert effort.same_file(relative, str(target), root)
    assert effort.same_file(effort.header_path(str(target)), "src/a.py", root)
    no_index = effort.header_path("b" + str(target))
    assert no_index == str(target)[1:]
    assert effort.same_file(no_index, str(target), root)
    dated = effort.header_path(f"{target}\t2026-10-15 10:00:00.000000000 +0200")
    assert dated == str(target)
    assert effort.same_file(dated, "src/a.py", root)
    assert not effort.same_file("src/b.py", "src/a.py", root)
    under_tests = root / "tests" / "test_a.py"
    assert effort.measure(patch(header="b" + str(under_tests)), GLOBS, root)["test_files"] == 1
    measured = effort.measure(f"--- {target}\t2026-10-15 09:00:00 +0200\n"
                              f"+++ {target}\t2026-10-15 10:00:00 +0200\n"
                              "@@ -0,0 +1 @@\n+x = 1\n", GLOBS, root)
    assert measured == {"files": 1, "test_files": 0, "lines": 1, "paths": [str(target)]}


# -- the after cut ---------------------------------------------------------------------


def test_trivial_without_patch_refused(cv: Converge) -> None:
    _attacked(cv)
    problems = _cut(cv, difficulty="trivial", patch=None, callers=None, migration=None)
    assert "cut: F001 difficulty trivial needs `patch`" in problems
    assert "cut: F001 difficulty trivial needs `callers` none; got None" in problems
    assert "cut: F001 difficulty trivial needs `migration` none; got None" in problems
    problems = _cut(cv, **cheap(difficulty="trivial", callers="changed", migration="needed"))
    assert "cut: F001 difficulty trivial needs `callers` none; got 'changed'" in problems
    assert "cut: F001 difficulty trivial needs `migration` none; got 'needed'" in problems


def test_local_over_limit_refused(cv: Converge) -> None:
    _attacked(cv)
    assert ("cut: F001 difficulty local: the patch changes 11 lines; cutoff.cheap.lines is 10"
            in _cut(cv, **cheap(patch(lines=11))))
    two = patch(lines=5) + patch("src/b.py", lines=1)
    problems = _cut(cv, **cheap(two))
    assert ("cut: F001 difficulty local: the patch touches 2 non-test files; "
            "cutoff.cheap.files is 1") in problems
    assert ("cut: F001 difficulty local: patch file src/b.py is not the claim's loc file "
            "src/a.py") in problems
    tests = patch(lines=4) + patch("tests/test_a.py") + patch("tests/test_b.py")
    assert ("cut: F001 difficulty local: the patch touches 2 test files; cutoff.cheap.tests is 1"
            in _cut(cv, **cheap(tests)))
    assert ("cut: F001 difficulty local: patch file src/b.py is not the claim's loc file "
            "src/a.py") in _cut(cv, **cheap(patch("src/b.py", lines=5)))
    renamed = "diff --git a/src/a.py b/src/c.py\nrename from src/a.py\nrename to src/c.py\n"
    assert any(p.startswith("cut: F001 `patch`: ") and "rename" in p
               for p in _cut(cv, **cheap(renamed)))
    assert _cut(cv, **cheap(patch(lines=8) + patch("tests/test_a.py", lines=2))) == []


def test_difficulty_class_precedence(cv: Converge) -> None:
    _attacked(cv)
    assert ("cut: F001 difficulty local: the patch changes 3 lines, within "
            "cutoff.cheap.trivial_lines 3; type trivial") in _cut(cv, **cheap(patch(lines=3)))
    assert ("cut: F001 difficulty trivial: the patch changes 4 lines; "
            "cutoff.cheap.trivial_lines is 3") in _cut(
        cv, **cheap(patch(lines=4), difficulty="trivial"))
    assert _cut(cv, difficulty="cross-cutting", patch=patch("src/b.py", lines=40),
                callers="changed", choice="move the check or keep it") == []
    other = Converge(cv.root / "trivial")
    _attacked(other)
    assert _cut(other, **cheap(patch(lines=3), difficulty="trivial")) == []


# -- gate 2 step 2: fix-now ---------------------------------------------------------------


def test_fix_now_result_and_render(cv: Converge) -> None:
    _attacked(cv, claims=2)
    cv.rate("F001", **cheap(patch(lines=4)))
    cv.rate("F002", impact="security")
    assert _results(cv) == {"F001": ("fix-now", "cheap (local)"),
                            "F002": ("finding", "report_if[0]")}
    out = cv.ok("cutoff", "s1").stdout.splitlines()
    assert out[0].endswith("fix-now=1 fixed=0 findings=1 follow-up=0 killed=0")
    assert "F001 fix-now status=survived cut=no rank=2 reason=cheap (local)" in out
    rendered = cv.ok("render", "s1").stdout
    assert "fix-now=1 fixed=0 findings=1 follow-up=0 killed=0 converged=yes" in rendered
    section = rendered.split("## Fix now\n\n", 1)[1].split("\n\n", 1)[0].splitlines()
    assert section == [
        "| rank | claim | lens | loc | text | impact | reach | difficulty | patch lines |",
        "|" + "---|" * 9,
        "| 2 | F001 | correctness | src/a.py:10 | claim 1 | wrong-output | normal | local | 4 |"]
    findings = rendered.split("## Findings\n\n", 1)[1].split("\n\n", 1)[0]
    assert "| F002 |" in findings and "| F001 |" not in findings
    data = json.loads(cv.ok("render", "s1", "--json").stdout)
    assert data["fix_now"] == [{"claim": "F001", "patch": patch(lines=4)}]
    assert cv("converged", "s1", "--dir", str(cv.dir)).stdout.startswith("CONVERGED")


def test_cheap_needs_accept_not_repeat(cv: Converge) -> None:
    _attacked(cv)
    assert _cut(cv, **cheap(patch(lines=4))) == []
    assert cv.append("rebut", FINDER, claim="F001", when="after", evidence="two fixes fit",
                     evidence_sha256=ledger.evidence_hash("two fixes fit")) == []
    assert _cut(cv, rnd=2, **cheap(patch(lines=4))) == []
    assert protocol.slate_phase(_slate(cv)) == "cutoff"
    assert _results(cv) == {"F001": ("finding", "report_if[0]")}


def test_cheap_requires_survived(cv: Converge) -> None:
    cv.ready(cut="after")
    cv.batch_1("F001", refuted=(BATCH_1[0],))
    for n, (kind, fields) in enumerate((("reply", {"stance": "rebut"}),
                                        ("verdict", {"verdict": "disagree", "evidence": "b"}),
                                        ("reply", {"stance": "rebut"}))):
        agent = R1 if kind == "verdict" else FINDER
        if kind == "reply":
            fields = {**fields, "evidence": f"e{n}",
                      "evidence_sha256": ledger.evidence_hash(f"e{n}")}
        assert cv.append(kind, agent, claim="F001", batch=1, **fields) == []
    cv.fresh_eye("F001")
    cv.rate("F001", **cheap(patch(lines=4)))
    assert _results(cv) == {"F001": ("finding", "report_if[0]")}


def test_cheap_disabled_never_fix_now(cv: Converge) -> None:
    _attacked(cv, cutoff={"cheap": {"enabled": False}})
    cv.rate("F001", **cheap(patch(lines=4)))
    assert _results(cv) == {"F001": ("finding", "report_if[0]")}


def test_report_rules_claim_is_never_fix_now(cv: Converge) -> None:
    cv.ready(cut="after", config={"cutoff": {"report_rules": ["R002"]}}, claims=0,
             escalate=False)
    cv.file(extra=("--rule", "R002"))
    cv.clean("F001")
    cv.rate("F001", **cheap(patch(lines=4)))
    assert _results(cv) == {"F001": ("finding", "report_rules[R002]")}
