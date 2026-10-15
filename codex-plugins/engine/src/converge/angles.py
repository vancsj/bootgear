"""Angle tables: built-in rows plus caller and config files.

A file is YAML: a top-level list of rows, or a mapping whose one key is
`angles:` holding that list. Rows are keyed by (tag, id):
the same id may appear under two tags (e.g. `reversibility` evaluates and
decides) but never twice under one tag.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from . import model

BUILTIN = Path(__file__).resolve().parent / "angles" / "builtin.yaml"
TAGS = ("find", "attack", "evaluate", "decide")
KEY_RE = re.compile(r"\A[a-z0-9]+(?:-[a-z0-9]+)*\Z")
REQUIRED = ("id", "tag", "tell", "asks")
OPTIONAL = ("field", "lens", "cost", "values")
# Fields an evaluate angle collects evidence for.
FIELDS = (*model.CUT_FIELDS, *model.AFTER_FIELDS)


class AngleError(Exception):
    def __init__(self, problems: list[str]):
        super().__init__("\n".join(problems))
        self.problems = problems


def validate_rows(rows: Any, label: str) -> list[str]:
    problems: list[str] = []
    if not isinstance(rows, list):
        return [f"{label}: `angles` must be a list"]
    seen: set[tuple[str, str]] = set()
    for i, row in enumerate(rows):
        at = f"{label}: angles[{i}]"
        if not isinstance(row, dict):
            problems.append(f"{at} must be a mapping")
            continue
        at = f"{at} ({row.get('id', '?')})"
        for key in REQUIRED:
            if key not in row:
                problems.append(f"{at}: missing `{key}`")
        for key in sorted(set(row) - set(REQUIRED) - set(OPTIONAL)):
            problems.append(f"{at}: unknown key `{key}`")
        angle_id, tag = row.get("id"), row.get("tag")
        if "id" in row and not (isinstance(angle_id, str) and KEY_RE.match(angle_id)):
            problems.append(f"{at}: id must be kebab-case ({KEY_RE.pattern})")
        if "tag" in row and tag not in TAGS:
            problems.append(f"{at}: tag must be one of {', '.join(TAGS)}")
        for key in ("tell", "asks", "lens", "cost"):
            if key in row and not (isinstance(row[key], str) and row[key].strip()):
                problems.append(f"{at}: `{key}` must be a non-empty string")
        if "field" in row:
            if tag != "evaluate":
                problems.append(f"{at}: `field` is only for evaluate angles")
            elif row["field"] not in FIELDS:
                problems.append(f"{at}: field must be one of {', '.join(FIELDS)}")
        if "values" in row:
            _values(row, at, problems)
        if isinstance(angle_id, str) and isinstance(tag, str):
            if (tag, angle_id) in seen:
                problems.append(f"{at}: duplicate {tag} angle id {angle_id!r}")
            seen.add((tag, angle_id))
    return problems


def _values(row: dict[str, Any], at: str, problems: list[str]) -> None:
    """`values` maps each value of the angle's enum field it tests to its test text."""
    enum = model.FIELD_ENUMS.get(row.get("field", "")) if row.get("tag") == "evaluate" else None
    if enum is None:
        problems.append(f"{at}: `values` is only for evaluate angles of "
                        f"{', '.join(model.FIELD_ENUMS)}")
        return
    values = row["values"]
    if not isinstance(values, dict) or not values:
        problems.append(f"{at}: `values` must map values to their test text")
        return
    for value, test in values.items():
        if value not in enum:
            problems.append(f"{at}: `values` key {value!r} is not a value of {row['field']} "
                            f"(allowed: {', '.join(enum)})")
        elif not (isinstance(test, str) and test.strip()):
            problems.append(f"{at}: `values.{value}` must be a non-empty string")


def value_gaps(rows: list[dict[str, Any]]) -> list[str]:
    """Each enum field with a value that no evaluate angle of that field gives a test for."""
    tested: dict[str, set[str]] = {name: set() for name in model.FIELD_ENUMS}
    for row in rows:
        if row["tag"] == "evaluate" and row.get("field") in tested:
            tested[row["field"]].update(row.get("values", {}))
    problems = []
    for name, enum in model.FIELD_ENUMS.items():
        missing = [value for value in enum if value not in tested[name]]
        if missing:
            problems.append(f"evaluate angles of field {name} give no test for "
                            f"{', '.join(missing)}")
    return problems


def load_file(path: Path) -> list[dict[str, Any]]:
    try:
        document = yaml.safe_load(path.read_text())
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise AngleError([f"cannot read angle file {path}: {exc}"]) from exc
    if isinstance(document, dict) and set(document) == {"angles"}:
        document = document["angles"]
    if not isinstance(document, list):
        raise AngleError([(f"{path}: an angle file is a list of rows (or a mapping with one key, "
                           f"`angles`, holding that list)")])
    problems = validate_rows(document, str(path))
    if problems:
        raise AngleError(problems)
    return document


def resolve(files: list[Path], config: dict[str, Any] | None = None,
            project_root: Path | None = None) -> list[dict[str, Any]]:
    """builtin + `files` + config `angles.files` − config `angles.disable`."""
    config = config or {}
    angles_cfg = config.get("angles", {})
    root = project_root or Path.cwd()
    paths = [BUILTIN, *files]
    for name in angles_cfg.get("files", []):
        path = Path(name).expanduser()
        paths.append(path if path.is_absolute() else root / path)
    rows: list[dict[str, Any]] = []
    problems: list[str] = []
    owner: dict[tuple[str, str], Path] = {}
    for path in paths:
        try:
            loaded = load_file(path)
        except AngleError as exc:
            problems.extend(exc.problems)
            continue
        for row in loaded:
            key = (row["tag"], row["id"])
            if key in owner:
                problems.append(f"{path}: duplicate {key[0]} angle id {key[1]!r} (also in {owner[key]})")
                continue
            owner[key] = path
            rows.append(dict(row))
    if problems:
        raise AngleError(problems)
    disabled = set(angles_cfg.get("disable", []))
    rows = [row for row in rows if row["id"] not in disabled]
    gaps = value_gaps(rows)
    if gaps:
        raise AngleError(gaps)
    return rows
