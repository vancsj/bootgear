"""spec-review's cutoff table: same file on both hosts, a valid converge
config layer, and the report decisions it encodes."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

PLUGIN_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_DIR / "src"))

from converge.config import validate_config
from converge.model import rule_matches

REPO_ROOT = PLUGIN_DIR.parents[1]
CLAUDE_CUTOFF = REPO_ROOT / "plugins" / "spec" / "skills" / "spec-review" / "references" / "cutoff.yaml"
CODEX_CUTOFF = PLUGIN_DIR / "skills" / "spec-review" / "references" / "cutoff.yaml"


def _table() -> dict:
    return yaml.safe_load(CLAUDE_CUTOFF.read_text())


def test_codex_copy_matches_claude_file() -> None:
    assert CODEX_CUTOFF.read_bytes() == CLAUDE_CUTOFF.read_bytes()


def test_table_is_a_valid_config_layer() -> None:
    table = _table()
    assert validate_config(table, str(CLAUDE_CUTOFF)) == []
    assert set(table) == {"cutoff"}
    assert set(table["cutoff"]) == {"cheap", "lenses"}
    assert table["cutoff"]["cheap"] == {"enabled": False}
    assert set(table["cutoff"]["lenses"]) == {"default"}


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
