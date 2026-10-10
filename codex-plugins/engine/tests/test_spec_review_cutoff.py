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
    assert table["cutoff"]["report_if_gap_hunt"] == table["cutoff"]["report_if"]


@pytest.mark.parametrize(
    ("severity", "frequency", "confidence", "reported"),
    [
        ("degraded", "common", "traced", True),
        ("data-loss", "rare", "traced", False),
        ("data-loss", "rare", "reproduced", True),
        ("cosmetic", "every-call", "reproduced", False),
    ],
)
def test_table_reports(severity: str, frequency: str, confidence: str, reported: bool) -> None:
    values: dict[str, str | None] = {
        "severity": severity,
        "frequency": frequency,
        "confidence": confidence,
    }
    for key in ("report_if", "report_if_gap_hunt"):
        rules = _table()["cutoff"][key]
        assert any(rule_matches(rule, values) for rule in rules) is reported
