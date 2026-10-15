"""review's converge layers: the cutoff table and the evaluate-angle file are the same
file on both hosts, a valid converge config layer and angle file, and the lens decisions the
cutoff table encodes."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

PLUGIN_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_DIR / "src"))

from converge.angles import load_file, resolve
from converge.config import DEFAULTS, _merge, rereview, validate_config
from converge.model import rule_matches

REPO_ROOT = PLUGIN_DIR.parents[1]
CLAUDE_REFS = REPO_ROOT / "plugins" / "review" / "skills" / "review" / "references"
CODEX_REFS = PLUGIN_DIR / "skills" / "review" / "references"
NEW_ANGLE_FILES = (
    "angles-security.yaml", "angles-tests.yaml", "angles-simplicity.yaml",
    "angles-consistency.yaml", "pack-web.yaml", "pack-typed-oop.yaml",
    "pack-concurrency-db.yaml", "pack-test-tooling.yaml",
)
FILES = ("cutoff.yaml", "evaluate-angles.yaml", "lenses.md", *NEW_ANGLE_FILES)


def _effective(review_pass: int = 1) -> dict:
    """The built-in defaults with review's cutoff table as the caller layer."""
    effective = _merge(DEFAULTS, yaml.safe_load((CLAUDE_REFS / "cutoff.yaml").read_text()))
    return rereview(effective) if review_pass >= 2 else effective


@pytest.mark.parametrize("name", FILES)
def test_codex_copy_matches_claude_file(name: str) -> None:
    assert (CODEX_REFS / name).read_bytes() == (CLAUDE_REFS / name).read_bytes()


def test_cutoff_is_a_valid_config_layer() -> None:
    table = yaml.safe_load((CLAUDE_REFS / "cutoff.yaml").read_text())
    assert validate_config(table, "review cutoff.yaml") == []
    assert set(table) == {"cutoff"} and set(table["cutoff"]) == {"lenses", "rereview"}
    assert set(table["cutoff"]["lenses"]) == {"security", "correctness", "contract", "tests",
                                              "architecture", "consistency"}
    assert validate_config(_effective(2), "pass 2", complete=True) == []


def test_evaluate_angles_file() -> None:
    rows = load_file(CLAUDE_REFS / "evaluate-angles.yaml")
    assert [(row["id"], row["tag"], row["field"], row["lens"]) for row in rows] == [
        ("file-churn", "evaluate", "rate", "architecture")]
    assert "git log --since" in rows[0]["asks"]


def test_review_angle_files_resolve_together() -> None:
    names = ("find-angles.yaml", "design-patterns.yaml", "evaluate-angles.yaml", *NEW_ANGLE_FILES)
    assert resolve([CLAUDE_REFS / name for name in names])


def _decides(lens: str, key: str, review_pass: int = 1, **values: object) -> bool:
    lenses = _effective(review_pass)["cutoff"]["lenses"]
    rules = lenses.get(lens, lenses["default"]).get(key, [])
    base = {"size": "one", "rate": 0, "tier": "traced", "status": "survived",
            "difficulty": "local", "lens": lens, "origin": "lens"}
    return any(rule_matches(rule, {**base, **values}) for rule in rules)


@pytest.mark.parametrize(
    ("lens", "values", "attacked"),
    [
        ("security", {"impact": "cosmetic", "reach": "crafted"}, True),
        ("correctness", {"impact": "wrong-output", "reach": "crafted"}, False),
        ("correctness", {"impact": "cosmetic", "reach": "normal", "tier": "reproduced"}, True),
        ("tests", {"impact": "cosmetic", "reach": "unreachable", "tier": "traced"}, True),
        ("architecture", {"impact": "cosmetic", "reach": "normal", "rate": 2}, False),
        ("architecture", {"impact": "cosmetic", "reach": "normal", "rate": 3}, True),
        ("simplicity", {"impact": "wrong-output", "reach": "normal"}, True),
        ("consistency", {"tier": "traced", "impact": "clarity"}, True),
        ("consistency", {"tier": "traced", "impact": "cosmetic"}, True),
        ("consistency", {"tier": "inferred", "impact": "clarity"}, False),
    ],
)
def test_cutoff_attacks(lens: str, values: dict, attacked: bool) -> None:
    assert _decides(lens, "attack_if", **values) is attacked


@pytest.mark.parametrize(
    ("lens", "review_pass", "values", "reported"),
    [
        ("correctness", 1, {"impact": "wrong-output", "reach": "normal", "size": "one"}, False),
        ("correctness", 1, {"impact": "wrong-output", "reach": "normal", "size": "many"}, True),
        ("correctness", 1, {"impact": "data-loss", "reach": "normal", "rate": 3}, True),
        ("contract", 1, {"impact": "clarity", "reach": "normal"}, True),
        ("contract", 2, {"impact": "clarity", "reach": "normal"}, False),
        ("contract", 2, {"impact": "wrong-output", "reach": "normal", "tier": "reproduced"},
         True),
        ("architecture", 2, {"impact": "cosmetic", "reach": "normal", "rate": 4}, False),
        ("simplicity", 2, {"impact": "security", "reach": "crafted"}, True),
        ("consistency", 1, {"tier": "traced", "impact": "clarity"}, True),
        ("consistency", 1, {"tier": "traced", "impact": "cosmetic"}, False),
        ("consistency", 1, {"tier": "inferred", "impact": "clarity"}, False),
        ("consistency", 2, {"tier": "traced", "impact": "clarity"}, False),
    ],
)
def test_cutoff_reports(lens: str, review_pass: int, values: dict, reported: bool) -> None:
    assert _decides(lens, "report_if", review_pass, **values) is reported


def test_pass_two_contract_keeps_choice_if() -> None:
    contract = _effective(2)["cutoff"]["lenses"]["contract"]
    assert contract["choice_if"] == [{"difficulty": ["cross-cutting", "redesign"]}]
