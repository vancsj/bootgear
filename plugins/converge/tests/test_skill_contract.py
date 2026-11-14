"""Shared fresh-eye instructions keep the caller's angle choices open."""
from pathlib import Path


def test_fresh_eye_instructions_allow_angles_outside_the_fixed_list() -> None:
    skill = Path(__file__).resolve().parents[1] / "skills/converge/SKILL.md"
    lines = [line for line in skill.read_text().splitlines()
             if "Fresh-eye batch (`batch` `fresh-eye`)" in line]
    assert len(lines) == 1
    for phrase in ("including names outside the fixed list", "fixed list is not a menu", "For example"):
        assert phrase in lines[0]
