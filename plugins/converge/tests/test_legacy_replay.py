"""A slate whose init config has no `steps` section replays and behaves as it always did.

`fixtures/legacy_slate.jsonl` was written by the CLI before `steps` existed: find, refute
(rounds, downgrades, a dependent reset, a kill, an inconclusive and an unconverged claim),
rebut, cut (a rebut re-cut and a capped cut), accept and cutoff. Its `status`,
`cutoff` and `render` output are stored next to it and compared byte for byte.
"""
from __future__ import annotations

import json
from pathlib import Path

from conftest import Converge

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SLATE = "legacy"
# The refute prefix: init, files and find coverage, before the first refute or cut.
PREFIX_EVENTS = 13


def _load(cv: Converge, events: int | None = None) -> list[str]:
    lines = (FIXTURES / "legacy_slate.jsonl").read_text().splitlines(keepends=True)
    cv.dir.mkdir(parents=True, exist_ok=True)
    kept = lines if events is None else lines[:events]
    cv.path(SLATE).write_text("".join(kept))
    return kept


def _append(cv: Converge, event: dict) -> None:
    seq = len(cv.path(SLATE).read_text().splitlines()) + 1
    line = json.dumps({"seq": seq, "ts": "2026-10-09T00:00:00Z", **event}) + "\n"
    with cv.path(SLATE).open("a") as handle:
        handle.write(line)


def _expected(name: str, cv: Converge) -> str:
    return (FIXTURES / name).read_text().replace("<dir>", str(cv.dir))


def test_fixture_has_no_steps_section(cv: Converge) -> None:
    init = json.loads(_load(cv)[0])
    assert init["event"] == "init" and "steps" not in init["config"]


def test_status_json_replays_unchanged(cv: Converge) -> None:
    _load(cv)
    out = cv.ok("status", SLATE, "--json").stdout
    assert out == _expected("legacy_slate.status.json", cv)


def test_status_prose_replays_unchanged(cv: Converge) -> None:
    _load(cv)
    assert cv.ok("status", SLATE).stdout == _expected("legacy_slate.status.txt", cv)


def test_cutoff_replays_unchanged(cv: Converge) -> None:
    lines = _load(cv)
    out = cv.ok("cutoff", SLATE).stdout
    assert out == _expected("legacy_slate.cutoff.txt", cv)
    # The stored cutoff is current, so cutoff writes nothing.
    assert cv.path(SLATE).read_text() == "".join(lines)


def test_render_replays_unchanged(cv: Converge) -> None:
    _load(cv)
    assert cv.ok("render", SLATE).stdout == _expected("legacy_slate.render.md", cv)


def test_gate_passes(cv: Converge) -> None:
    _load(cv)
    assert f"GATE ok {SLATE}" in cv("gate", SLATE, "--dir", str(cv.dir)).stdout


def test_appended_escalate_is_refused(cv: Converge) -> None:
    prefix = _load(cv, PREFIX_EVENTS)
    assert all(json.loads(line)["event"] not in ("refute", "cut") for line in prefix)
    _append(cv, {"event": "escalate", "as": "finder", "claim": "F001"})
    err = cv.refused("status", SLATE, "--json")
    assert "ledger is corrupt or out of order" in err
    assert f"line {PREFIX_EVENTS + 1}: escalate: this slate predates the steps config" in err


def test_appended_cut_before_refute_is_refused(cv: Converge) -> None:
    _load(cv, PREFIX_EVENTS)
    _append(cv, {"event": "cut", "as": "cutter", "claim": "F001", "round": 1,
                 "frequency": "common", "severity": "wrong-behavior", "confidence": "traced",
                 "difficulty": "local",
                 "evidence": {"entry-points": "POST /x reaches it", "blast-radius": "one row",
                              "evidence-tier": "traced a.py:10", "files-touched": "a.py"}})
    err = cv.refused("status", SLATE, "--json")
    assert (f"line {PREFIX_EVENTS + 1}: cut: F001 refute state is open; cut needs refute "
            f"converged, inconclusive or unconverged") in err


def test_reads_leave_the_slate_untouched(cv: Converge) -> None:
    lines = _load(cv)
    for command in ("status", "coverage", "render"):
        cv.ok(command, SLATE)
    cv.ok("converged", SLATE, "--phase", "cut")
    assert cv.path(SLATE).read_text() == "".join(lines)
