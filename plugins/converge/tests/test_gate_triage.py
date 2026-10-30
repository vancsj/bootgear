"""`gate --kind triage --report <file>`: no claim is disputed or unverified; each surviving
claim is reproduced and has a report row with the slate tier, a command and an output; each
row names a slate claim and quotes its text; the report has the four headings; at least one
claim survives; each surviving claim has a `reproduction-rerun` attack. A killed claim needs no
tier and no row. A gate call without the options keeps the plain checks."""
from __future__ import annotations

import os
import shlex
from pathlib import Path

import pytest
from conftest import BATCH_1, DISABLED, FIND_ANGLES, FINDER, R1, Converge
from converge import cli

RERUN = "reproduction-rerun"
TRIAGE_ANGLES = FIND_ANGLES + f"""\
- id: {RERUN}
  tag: attack
  tell: the claim quotes a reproduction command and its output
  asks: does a re-run of the command show the quoted output in substance?
"""
HEADINGS = ("Cause", "Impact", "Confidence", "Next action")
COLUMNS: tuple[str, ...] = ("id", "claim", "tier", "command", "output")
# The claim and output cells hold an escaped pipe and a line break: a split on `\|` shifts
# the tier cell, and the tier check then fails.
COMMAND = "uv run pytest -q tests/test_a.py"
OUTPUT = "1 failed<br>AssertionError: x is None"
TRIAGE_EXAMPLE = "gate <slate> --dir <abs-dir> --kind triage --report <abs-file>"
FAILED_NEXT = "next: no revision is possible after this gate; end the run as failed"


def _claim(cid: str) -> str:
    """The slate claim text of `cid`."""
    return f"x | y is None\nat a.py:{int(cid[1:])}"


def _slate(cv: Converge, *tiers: str) -> list[str]:
    """A slate whose one attack angle is `reproduction-rerun`, one claim per tier."""
    cv.angles.write_text(TRIAGE_ANGLES)
    cv.init("s1", "correctness", config={
        "steps": {"cut": "none", "gap_hunt": False, "escalate": False},
        "angles": {"disable": [*BATCH_1, *DISABLED]}})
    ids = [cv.file(claim=_claim(f"F{n:03d}"), tier=tier)
           for n, tier in enumerate(tiers, start=1)]
    cv.cover(lenses=("correctness",))
    return ids


def _survive(cv: Converge, cid: str) -> None:
    assert cv.attack(cid, RERUN) == []
    cv.fresh_eye(cid)


def _cutoff(cv: Converge) -> None:
    cv.ok("cutoff", "s1")


def _row(cid: str, tier: str = "reproduced", command: str = COMMAND,
         output: str = OUTPUT, claim: str | None = None) -> tuple[str, ...]:
    """A `## Claims` row; the claim cell defaults to the slate text of `cid`, escaped."""
    text = _claim(cid) if claim is None else claim
    return (cid, text.replace("|", "\\|").replace("\n", "<br>"), tier, command, output)


def _report(cv: Converge, rows: list[tuple[str, ...]],
            headings: tuple[str, ...] = HEADINGS) -> Path:
    lines = ["# Triage report", "", "## Claims", "",
             f"| {' | '.join(COLUMNS)} |", "|---|---|---|---|---|",
             *(f"| {' | '.join(row)} |" for row in rows)]
    for heading in headings:
        lines += ["", f"## {heading}", "", f"{heading} text."]
    path = cv.root / "s1.triage-report.md"
    path.write_text("\n".join(lines) + "\n")
    return path


def _gate(cv: Converge, *options: str, code: int = 0) -> list[str]:
    return cv("gate", "s1", "--dir", str(cv.dir), *options, code=code).stdout.splitlines()


def _triage(cv: Converge, report: Path, code: int = 0) -> list[str]:
    return _gate(cv, "--kind", "triage", "--report", str(report), code=code)


def _fail(lines: list[str]) -> list[str]:
    """The problem lines of a `GATE fail` result."""
    assert lines[0] == "GATE fail s1" and lines[-1].startswith("next: "), lines
    return lines[1:-1]


# -- pass ----------------------------------------------------------------------------


def test_triage_gate_passes_a_reproduced_report(cv: Converge) -> None:
    (cid,) = _slate(cv, "reproduced")
    _survive(cv, cid)
    _cutoff(cv)
    lines = _triage(cv, _report(cv, [_row(cid)]))
    assert lines[0].startswith("GATE ok s1 cutoff_seq=")
    assert lines[-1] == f"next: converge converged s1 --dir {shlex.quote(str(cv.dir))}"


@pytest.mark.parametrize("tier", ["reproduced", "inferred"])
def test_a_killed_claim_needs_no_row_or_tier(cv: Converge, tier: str) -> None:
    kept, killed = _slate(cv, "reproduced", tier)
    _survive(cv, kept)
    assert cv.attack(killed, RERUN, outcome="refuted") == []
    cv.ok("reply", "s1", "--as", FINDER, "--claim", killed, "--batch", "1",
          "--stance", "decline")
    _cutoff(cv)
    assert cv.status()["by_id"][killed]["status"] == "killed"
    assert _triage(cv, _report(cv, [_row(kept)]))[0].startswith("GATE ok s1 ")


# -- D7 checks ---------------------------------------------------------------------------


def test_surviving_claim_not_reproduced(cv: Converge) -> None:
    reproduced, traced = _slate(cv, "reproduced", "traced")
    for cid in (reproduced, traced):
        _survive(cv, cid)
    _cutoff(cv)
    assert cv.status()["by_id"][traced]["status"] == "survived"
    report = _report(cv, [_row(reproduced), _row(traced, tier="traced")])
    assert _gate(cv)[0].startswith("GATE ok s1 ")
    assert _fail(_triage(cv, report, code=1)) == [
        f"{traced} has tier traced; a surviving triage claim needs tier reproduced"]


def test_row_tier_differs_from_slate_tier(cv: Converge) -> None:
    (cid,) = _slate(cv, "reproduced")
    _survive(cv, cid)
    _cutoff(cv)
    report = _report(cv, [_row(cid, tier="traced")])
    assert _fail(_triage(cv, report, code=1)) == [
        f"report row {cid}: tier 'traced' differs from the slate tier 'reproduced'"]


def test_surviving_claim_without_row(cv: Converge) -> None:
    first, second = _slate(cv, "reproduced", "reproduced")
    for cid in (first, second):
        _survive(cv, cid)
    _cutoff(cv)
    assert _fail(_triage(cv, _report(cv, [_row(first)]), code=1)) == [
        f"{second} survived but has no row in the report's ## Claims table"]


@pytest.mark.parametrize("column", ["command", "output"])
def test_empty_command_or_output_cell(cv: Converge, column: str) -> None:
    (cid,) = _slate(cv, "reproduced")
    _survive(cv, cid)
    _cutoff(cv)
    report = _report(cv, [_row(cid, **{column: " "})])
    assert _fail(_triage(cv, report, code=1)) == [f"report row {cid}: the {column} cell is empty"]


@pytest.mark.parametrize("missing", HEADINGS)
def test_missing_heading(cv: Converge, missing: str) -> None:
    (cid,) = _slate(cv, "reproduced")
    _survive(cv, cid)
    _cutoff(cv)
    report = _report(cv, [_row(cid)], tuple(h for h in HEADINGS if h != missing))
    assert _fail(_triage(cv, report, code=1)) == [f"report has no ## {missing} heading"]


def test_no_surviving_claim(cv: Converge) -> None:
    (cid,) = _slate(cv, "reproduced")
    assert cv.attack(cid, RERUN, outcome="refuted") == []
    cv.ok("reply", "s1", "--as", FINDER, "--claim", cid, "--batch", "1", "--stance", "decline")
    _cutoff(cv)
    assert _gate(cv)[0].startswith("GATE ok s1 ")
    assert _fail(_triage(cv, _report(cv, [_row(cid)]), code=1)) == [
        "no claim survived; a triage slate needs at least one surviving cause claim"]


def test_surviving_claim_without_rerun_attack(cv: Converge) -> None:
    attacked, skipped = _slate(cv, "reproduced", "reproduced")
    _survive(cv, attacked)
    cv.ok("angle-na", "s1", "--as", R1, "--phase", "attack", "--claim", skipped,
          "--angle", RERUN, "--reason", "no command to re-run")
    cv.fresh_eye(skipped)
    _cutoff(cv)
    report = _report(cv, [_row(attacked), _row(skipped)])
    assert _fail(_triage(cv, report, code=1)) == [f"{skipped} survived with no {RERUN} attack"]


def test_report_row_names_no_slate_claim(cv: Converge) -> None:
    cid = _ready(cv)
    report = _report(cv, [_row(cid), _row("F009")])
    assert _fail(_triage(cv, report, code=1)) == ["report row F009 names no slate claim"]


def test_row_claim_differs_from_slate_claim(cv: Converge) -> None:
    cid = _ready(cv)
    report = _report(cv, [_row(cid, claim="x is None")])
    assert _fail(_triage(cv, report, code=1)) == [
        f"report row {cid}: claim 'x is None' differs from the slate claim {_claim(cid)!r}"]


@pytest.mark.parametrize("column", ["id", "tier"])
def test_a_code_spanned_cell_reads_its_plain_value(cv: Converge, column: str) -> None:
    cid = _ready(cv)
    row = dict(zip(COLUMNS, _row(cid)))
    row[column] = f"`{row[column]}`"
    assert _triage(cv, _report(cv, [tuple(row.values())]))[0].startswith("GATE ok s1 ")


def test_a_disputed_claim_fails_while_another_survives(cv: Converge) -> None:
    kept, disputed = _slate(cv, "reproduced", "reproduced")
    _survive(cv, kept)
    assert cv.attack(disputed, RERUN, outcome="refuted") == []
    reply = ("reply", "s1", "--as", FINDER, "--claim", disputed, "--batch", "1",
             "--stance", "rebut")
    cv.ok(*reply, "--evidence", "the re-run shows the quoted output")
    cv.ok("verdict", "s1", "--as", R1, "--claim", disputed, "--batch", "1",
          "--verdict", "disagree", "--evidence", "the re-run passes")
    cv.ok(*reply, "--evidence", "the re-run fails on a clean checkout")
    cv.fresh_eye(disputed)
    _cutoff(cv)
    assert cv.status()["by_id"][disputed]["status"] == "disputed"
    report = _report(cv, [_row(kept), _row(disputed)])
    assert _fail(_triage(cv, report, code=1)) == [
        f"{disputed} is disputed; each triage cause claim must survive or be killed"]


def test_every_problem_in_one_run(cv: Converge) -> None:
    first, second = _slate(cv, "reproduced", "traced")
    for cid in (first, second):
        _survive(cv, cid)
    _cutoff(cv)
    report = _report(cv, [_row(first, command="")], ("Cause", "Impact"))
    lines = _triage(cv, report, code=1)
    assert _fail(lines) == [
        f"{second} has tier traced; a surviving triage claim needs tier reproduced",
        f"report row {first}: the command cell is empty",
        f"{second} survived but has no row in the report's ## Claims table",
        "report has no ## Confidence heading",
        "report has no ## Next action heading"]
    assert lines[-1] == FAILED_NEXT
    assert _gate(cv)[0].startswith("GATE ok s1 ")


def test_open_slate_lists_its_open_items_and_the_triage_problems(cv: Converge) -> None:
    (cid,) = _slate(cv, "reproduced")
    lines = _triage(cv, _report(cv, [_row(cid)]), code=1)
    assert _fail(lines) == [
        f"{cid} is open in attack",
        "no current cutoff (run `converge cutoff` after the last state change)",
        f"{cid} survived with no {RERUN} attack"]
    assert lines[-1].startswith(f"next: attack: r1 attack {cid} batch 1")


# -- option mismatches ---------------------------------------------------------------


def _refused(cv: Converge, *options: str, code: int = 1) -> list[str]:
    result = cv("gate", "s1", "--dir", str(cv.dir), *options, code=code)
    assert result.stdout == ""
    return result.stderr.splitlines()


def _ready(cv: Converge) -> str:
    (cid,) = _slate(cv, "reproduced")
    _survive(cv, cid)
    _cutoff(cv)
    return cid


def test_kind_without_report(cv: Converge) -> None:
    _ready(cv)
    err = _refused(cv, "--kind", "triage")
    assert err[0] == f"example: converge {TRIAGE_EXAMPLE}"
    assert err[-2:] == ["converge: refused:", "  - --kind triage needs --report <absolute file>"]


def test_report_without_kind(cv: Converge) -> None:
    cid = _ready(cv)
    err = _refused(cv, "--report", str(_report(cv, [_row(cid)])))
    assert err[0] == f"example: converge {TRIAGE_EXAMPLE}"
    assert err[-1] == "  - --report needs --kind triage"


@pytest.mark.parametrize("kind", ["missing", "directory"])
def test_report_is_not_a_file(cv: Converge, kind: str) -> None:
    _ready(cv)
    report = cv.root / ("absent.md" if kind == "missing" else "ledgers")
    err = _refused(cv, "--kind", "triage", "--report", str(report))
    assert err[-1] == f"  - --report {report} is not a file"


def test_report_is_relative(cv: Converge) -> None:
    cid = _ready(cv)
    report = _report(cv, [_row(cid)])
    rel = os.path.relpath(report, cv.project)
    err = _refused(cv, "--kind", "triage", "--report", rel)
    assert err[-1] == f"  - --report needs an absolute path; got {rel!r}"


def test_kind_outside_its_set(cv: Converge) -> None:
    cid = _ready(cv)
    err = _refused(cv, "--kind", "review", "--report", str(_report(cv, [_row(cid)])), code=2)
    assert err[0] == f"example: converge {TRIAGE_EXAMPLE}"
    assert "argument --kind: invalid choice: 'review'" in err[-1] and "triage" in err[-1]


def test_triage_example_parses() -> None:
    args = cli._parser().parse_args(shlex.split(cli.TRIAGE_CATALOG.examples["gate"]))
    assert (args.command, args.kind, str(args.report)) == ("gate", "triage", "<abs-file>")
    assert cli.TRIAGE_CATALOG.examples["gate"] == TRIAGE_EXAMPLE
    assert cli.EXAMPLES["gate"] == "gate <slate> --dir <abs-dir>"


# -- base slate ------------------------------------------------------------------------


def test_base_slate_needs_kind(cv: Converge) -> None:
    _ready(cv)
    err = _refused(cv, "--base-slate", "s1")
    assert err[-1] == "  - --base-slate needs --kind triage"


def test_base_slate_passes_when_every_row_is_a_base_claim(cv: Converge) -> None:
    cid = _ready(cv)
    lines = _gate(cv, "--kind", "triage", "--report", str(_report(cv, [_row(cid)])),
                  "--base-slate", "s1")
    assert lines[0].startswith("GATE ok s1 ")


def test_base_slate_refuses_a_row_it_does_not_hold(cv: Converge) -> None:
    kept, added = _slate(cv, "reproduced", "reproduced")
    for cid in (kept, added):
        _survive(cv, cid)
    _cutoff(cv)
    cv.init("s0", "correctness", config={
        "steps": {"cut": "none", "gap_hunt": False, "escalate": False},
        "angles": {"disable": [*BATCH_1, *DISABLED]}})
    cv.file(slate="s0", claim=_claim(kept), tier="reproduced")
    report = _report(cv, [_row(kept), _row(added)])
    lines = _gate(cv, "--kind", "triage", "--report", str(report), "--base-slate", "s0", code=1)
    message = (f"report row {added} names no claim of the base slate s0; "
               "a later visit cannot add a cause claim")
    assert _fail(lines) == [message]
