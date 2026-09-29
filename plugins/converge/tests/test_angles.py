"""Angle tables: built-in rows, caller files, config files/disable, validation."""
from __future__ import annotations

from conftest import Converge

ATTACK = {"cited-but-unread", "point-in-time", "provenance", "reachability", "absent-vs-default",
          "downstream-consumer", "inverse-reading", "carve-out", "boundary", "dependents",
          "positive-control", "inherited-bounds", "guarded-elsewhere", "deliberate", "real-referent"}
EVALUATE = {"entry-points": "frequency", "call-site-count": "frequency", "prod-traffic": "frequency",
            "blast-radius": "severity", "reversibility": "severity", "who-notices": "severity",
            "evidence-tier": "confidence", "independent-confirmations": "confidence",
            "files-touched": "difficulty", "callers-affected": "difficulty",
            "migration": "difficulty", "test-cost": "difficulty"}
DECIDE = {"reversibility", "blast-radius", "principle-fit", "cost-of-delay", "precedent",
          "stakeholder-view"}


def _rows(cv: Converge, *args: str, code: int = 0) -> list[list[str]]:
    out = cv("angles", "--project-root", str(cv.project), *args, code=code).stdout
    return [line.split(" — ")[0].split() for line in out.splitlines()]


def test_builtin_rows(cv: Converge) -> None:
    rows = _rows(cv)
    by_tag: dict[str, set[str]] = {}
    for row in rows:
        by_tag.setdefault(row[0], set()).add(row[1])
    assert by_tag == {"attack": ATTACK, "evaluate": set(EVALUATE), "decide": DECIDE}
    fields = {row[1]: row[2].removeprefix("field=") for row in rows if row[0] == "evaluate"}
    assert fields == EVALUATE


def test_tag_filter_and_caller_file(cv: Converge) -> None:
    assert {r[1] for r in _rows(cv, "--tag", "decide")} == DECIDE
    finds = _rows(cv, "--tag", "find", "--angles", str(cv.angles))
    assert [r[1] for r in finds] == ["changed-contract", "failure-path", "god-object"]
    assert finds[2][2] == "lens=architecture"


def test_mapping_layout_accepted(cv: Converge) -> None:
    mapping = cv.root / "mapped.yaml"
    mapping.write_text("angles:\n  - {id: odd-old-code, tag: find, tell: t, asks: a}\n")
    assert [r[1] for r in _rows(cv, "--tag", "find", "--angles", str(mapping))] == ["odd-old-code"]


def test_duplicate_within_tag_rejected_across_files(cv: Converge) -> None:
    dup = cv.root / "dup.yaml"
    dup.write_text("- {id: changed-contract, tag: find, tell: t, asks: a}\n")
    err = cv("angles", "--project-root", str(cv.project), "--angles", str(cv.angles), str(dup),
             code=2).stderr
    assert "duplicate find angle id 'changed-contract'" in err
    clash = cv.root / "clash.yaml"
    clash.write_text("- {id: boundary, tag: attack, tell: t, asks: a}\n")
    assert "duplicate attack angle id 'boundary'" in cv(
        "angles", "--project-root", str(cv.project), "--angles", str(clash), code=2).stderr


def test_row_validation_lists_every_problem(cv: Converge) -> None:
    bad = cv.root / "bad.yaml"
    bad.write_text("- {id: Bad_Id, tag: smell, tell: t, asks: a, colour: red}\n"
                   "- {id: ok-one, tag: find, tell: '', asks: a, field: severity}\n"
                   "- {id: ev-one, tag: evaluate, tell: t, asks: a, field: speed}\n"
                   "- {tag: find}\n")
    err = cv("angles", "--project-root", str(cv.project), "--angles", str(bad), code=2).stderr
    for fragment in ("id must be kebab-case", "tag must be one of", "unknown key `colour`",
                     "`tell` must be a non-empty string", "`field` is only for evaluate angles",
                     "field must be one of", "missing `id`"):
        assert fragment in err


def test_config_files_and_disable(cv: Converge) -> None:
    cfg = cv.project / ".bootgear" / "config"
    cfg.mkdir(parents=True)
    (cv.project / "extra.yaml").write_text("- {id: gated-path, tag: find, tell: t, asks: a}\n")
    (cfg / "converge.yaml").write_text("angles: {files: [extra.yaml], disable: [boundary, precedent]}\n")
    rows = _rows(cv)
    ids = {(r[0], r[1]) for r in rows}
    assert ("find", "gated-path") in ids
    assert ("attack", "boundary") not in ids and ("decide", "precedent") not in ids


def test_init_rejects_unknown_angle_use(cv: Converge) -> None:
    cv.init()
    assert "unknown find angle 'gated-path'" in cv.file(angle="gated-path", code=2)
    assert "belongs to lens 'architecture'" in cv.file(angle="god-object", code=2)


def test_angle_lens_matches(cv: Converge) -> None:
    cv.init(lenses="correctness,architecture")
    assert cv.file(agent="find-architecture-1", lens="architecture", angle="god-object") == "F001"
