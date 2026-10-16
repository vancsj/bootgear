"""spec-review's cutoff table: same file on both hosts, a valid converge
config layer, and the report decisions it encodes."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

PLUGIN_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_DIR / "src"))

from converge.config import rereview, validate_config
from converge.model import rule_matches

REPO_ROOT = PLUGIN_DIR.parents[1]
CLAUDE_CUTOFF = REPO_ROOT / "plugins" / "spec" / "skills" / "spec-review" / "references" / "cutoff.yaml"
CODEX_CUTOFF = PLUGIN_DIR / "skills" / "spec-review" / "references" / "cutoff.yaml"
LENSES = {"default", "request-fit", "simplicity", "proportionality"}
CHOICE_LENSES = ("simplicity", "proportionality")


def _table() -> dict:
    return yaml.safe_load(CLAUDE_CUTOFF.read_text())


def _rules(cutoff: dict, lens: str, key: str) -> list:
    lenses = cutoff["lenses"]
    return lenses.get(lens, lenses["default"]).get(key, [])


def _rereview_cutoff() -> dict:
    return rereview({"cutoff": _table()["cutoff"]})["cutoff"]


def _reported(cutoff: dict, lens: str, impact: str) -> bool:
    values = {"impact": impact, "reach": "normal", "status": "survived", "size": "one", "rate": 0,
              "tier": "traced", "difficulty": "trivial", "lens": lens, "origin": "lens"}
    return any(rule_matches(rule, values) for rule in _rules(cutoff, lens, "report_if"))


def _attacked(cutoff: dict, lens: str, impact: str) -> bool:
    values = {"impact": impact, "reach": "normal", "size": "one", "rate": 0, "tier": "traced",
              "lens": lens, "origin": "lens"}
    return any(rule_matches(rule, values) for rule in _rules(cutoff, lens, "attack_if"))


def test_codex_copy_matches_claude_file() -> None:
    assert CODEX_CUTOFF.read_bytes() == CLAUDE_CUTOFF.read_bytes()


def test_table_is_a_valid_config_layer() -> None:
    table = _table()
    assert validate_config(table, str(CLAUDE_CUTOFF)) == []
    assert set(table) == {"cutoff"}
    assert set(table["cutoff"]) == {"cheap", "lenses", "rereview"}
    assert table["cutoff"]["cheap"] == {"enabled": False}
    assert set(table["cutoff"]["lenses"]) == LENSES


@pytest.mark.parametrize(
    ("impact", "reach", "attacked"),
    [
        ("clarity", "normal", True),
        ("wrong-output", "crafted", True),
        ("security", "unreachable", False),
        ("cosmetic", "normal", False),
    ],
)
def test_table_attacks(impact: str, reach: str, attacked: bool) -> None:
    values = {"impact": impact, "reach": reach, "size": "one", "rate": 0, "tier": "traced",
              "lens": "requirements", "origin": "lens"}
    rules = _table()["cutoff"]["lenses"]["default"]["attack_if"]
    assert any(rule_matches(rule, values) for rule in rules) is attacked


@pytest.mark.parametrize(
    ("impact", "reach", "status", "reported"),
    [
        ("clarity", "normal", "survived", True),
        ("data-loss", "crafted", "disputed", True),
        ("wrong-output", "unreachable", "survived", False),
        ("cosmetic", "normal", "survived", False),
    ],
)
def test_table_reports(impact: str, reach: str, status: str, reported: bool) -> None:
    values = {"impact": impact, "reach": reach, "status": status, "size": "one", "rate": 0,
              "tier": "traced", "difficulty": "trivial", "lens": "requirements",
              "origin": "gap-hunt"}
    rules = _table()["cutoff"]["lenses"]["default"]["report_if"]
    assert any(rule_matches(rule, values) for rule in rules) is reported


@pytest.mark.parametrize("lens", CHOICE_LENSES)
def test_simplicity_and_proportionality_carry_a_choice_for_a_wrong_result(lens: str) -> None:
    cutoff = _table()["cutoff"]
    assert _rules(cutoff, lens, "choice_if") == [{"impact": ["security", "data-loss", "wrong-output"]}]
    assert _rules(_rereview_cutoff(), lens, "choice_if") == _rules(cutoff, lens, "choice_if")


@pytest.mark.parametrize("lens", sorted(LENSES - set(CHOICE_LENSES)))
def test_other_lenses_have_no_choice_rule(lens: str) -> None:
    assert _rules(_table()["cutoff"], lens, "choice_if") == []


@pytest.mark.parametrize("lens", ["default", "simplicity", "proportionality", "clarity-completeness"])
def test_rereview_does_not_report_clarity(lens: str) -> None:
    assert _reported(_table()["cutoff"], lens, "clarity")
    assert not _reported(_rereview_cutoff(), lens, "clarity")


def test_rereview_keeps_reporting_clarity_for_request_fit() -> None:
    assert _reported(_rereview_cutoff(), "request-fit", "clarity")


@pytest.mark.parametrize("lens", sorted(LENSES))
@pytest.mark.parametrize("impact", ["security", "data-loss", "wrong-output"])
def test_rereview_reports_the_three_impacts(lens: str, impact: str) -> None:
    assert _reported(_rereview_cutoff(), lens, impact)


@pytest.mark.parametrize("lens", sorted(LENSES))
def test_rereview_still_attacks_clarity(lens: str) -> None:
    assert _attacked(_rereview_cutoff(), lens, "clarity")
