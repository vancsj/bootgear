"""Angle tables: built-in rows, caller files, config files/disable, validation."""
from __future__ import annotations

from conftest import PLUGIN_DIR, Converge
from converge import model

ATTACK = {"cited-but-unread", "point-in-time", "provenance", "reachability", "absent-vs-default",
          "downstream-consumer", "inverse-reading", "carve-out", "boundary", "dependents",
          "positive-control", "inherited-bounds", "guarded-elsewhere", "deliberate", "real-referent"}
EVALUATE = {"blast-radius": "impact", "reversibility": "impact", "who-notices": "impact",
            "affected-count": "size", "entry-points": "reach", "crafted-only": "reach",
            "call-site-count": "rate", "prod-traffic": "rate",
            "files-touched": "difficulty", "callers-affected": "difficulty",
            "migration": "difficulty", "test-cost": "difficulty"}
REVIEW_EVALUATE = (PLUGIN_DIR.parents[1] / "plugins" / "review" / "skills" / "review"
                   / "references" / "evaluate-angles.yaml")
DECIDE = {"reversibility", "blast-radius", "principle-fit", "cost-of-delay", "precedent",
          "stakeholder-view"}


def _rows(cv: Converge, *args: str, code: int = 0) -> list[list[str]]:
    out = cv("angles", "--project-root", str(cv.project), *args, code=code).stdout
    return [line.split(" — ")[0].split() for line in out.splitlines() if not line.startswith(" ")]


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


def test_find_tag_refuses_empty_results(cv: Converge) -> None:
    err = cv("angles", "--project-root", str(cv.project), "--tag", "find", code=2).stderr
    assert "no find angles" in err
    assert "--angles <file>" in err


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
                   "- {id: ev-one, tag: evaluate, tell: t, asks: a, field: severity}\n"
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
    assert [r[1] for r in _rows(cv, "--tag", "find")] == ["gated-path"]


def test_init_rejects_unknown_angle_use(cv: Converge) -> None:
    cv.init()
    assert "unknown find angle 'gated-path'" in cv.file(angle="gated-path", code=2)
    assert "belongs to lens 'architecture'" in cv.file(angle="god-object", code=2)


def test_angle_lens_matches(cv: Converge) -> None:
    cv.init(lenses="correctness,architecture")
    assert cv.file(agent="find-architecture-1", lens="architecture", angle="god-object") == "F001"


# -- value tests -----------------------------------------------------------------------


def _value_lines(cv: Converge, *args: str) -> dict[str, list[str]]:
    """Per evaluate angle, its indented `<value>: <test>` lines."""
    out = cv("angles", "--project-root", str(cv.project), "--tag", "evaluate", *args).stdout
    lines: dict[str, list[str]] = {}
    current = ""
    for line in out.splitlines():
        if line.startswith("  "):
            lines[current].append(line.strip())
        else:
            current = line.split()[1]
            lines[current] = []
    return lines


def test_angles_prints_value_tests(cv: Converge) -> None:
    lines = _value_lines(cv)
    assert lines["blast-radius"] == [
        ("security: a path from input an unauthorised caller controls to a resource they may "
         "not read, change or run")]
    assert lines["reversibility"] == [
        "data-loss: stored data is lost or overwritten and the same store cannot restore it"]
    assert [line.split(":")[0] for line in lines["who-notices"]] == [
        "wrong-output", "clarity", "cosmetic"]
    assert [line.split(":")[0] for line in lines["affected-count"]] == ["many", "one"]
    assert [line.split(":")[0] for line in lines["entry-points"]] == ["normal", "unreachable"]
    assert [line.split(":")[0] for line in lines["crafted-only"]] == ["crafted"]
    assert [line.split(":")[0] for line in lines["files-touched"]] == [
        "redesign", "cross-cutting", "trivial", "local"]
    assert lines["call-site-count"] == [] and lines["prod-traffic"] == []


def test_value_tests_cover_every_enum_value(cv: Converge) -> None:
    lines = _value_lines(cv)
    covered: dict[str, set[str]] = {}
    for angle, field in EVALUATE.items():
        covered.setdefault(field, set()).update(line.split(":")[0] for line in lines[angle])
    for field, enum in model.FIELD_ENUMS.items():
        assert covered[field] == set(enum), field
    cfg = cv.project / ".bootgear" / "config"
    cfg.mkdir(parents=True)
    (cfg / "converge.yaml").write_text("angles: {disable: [who-notices, crafted-only]}\n")
    err = cv("angles", "--project-root", str(cv.project), code=2).stderr
    assert "evaluate angles of field impact give no test for wrong-output, clarity, cosmetic" in err
    assert "evaluate angles of field reach give no test for crafted" in err


def test_values_key_outside_enum_refused(cv: Converge) -> None:
    bad = cv.root / "bad-values.yaml"
    bad.write_text(
        "- {id: ev-impact, tag: evaluate, field: impact, tell: t, asks: a,\n"
        "   values: {catastrophic: t, cosmetic: ''}}\n"
        "- {id: ev-rate, tag: evaluate, field: rate, tell: t, asks: a, values: {many: t}}\n"
        "- {id: ev-size, tag: evaluate, field: size, tell: t, asks: a, values: [many]}\n"
        "- {id: fd-one, tag: find, tell: t, asks: a, values: {many: t}}\n")
    err = cv("angles", "--project-root", str(cv.project), "--angles", str(bad), code=2).stderr
    only = "`values` is only for evaluate angles of impact, size, reach, difficulty"
    for fragment in (("(ev-impact): `values` key 'catastrophic' is not a value of impact "
                      "(allowed: security, data-loss, wrong-output, clarity, cosmetic)"),
                     "(ev-impact): `values.cosmetic` must be a non-empty string",
                     f"(ev-rate): {only}",
                     "(ev-size): `values` must map values to their test text",
                     f"(fd-one): {only}"):
        assert fragment in err, err


def test_evaluate_angle_loads_from_an_extra_file(cv: Converge) -> None:
    rows = _rows(cv, "--tag", "evaluate", "--angles", str(REVIEW_EVALUATE))
    assert ["evaluate", "file-churn", "field=rate", "lens=architecture"] in rows
    assert {r[1] for r in rows} == {*EVALUATE, "file-churn"}
