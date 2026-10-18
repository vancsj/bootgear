"""The deputy skills: section order, outcomes, and the script path on each host."""
from __future__ import annotations

import re
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
SKILLS = {name: PLUGIN / "skills" / name / "SKILL.md" for name in ("ask", "record")}
HEADINGS = ["## Inputs and outcomes", "## Procedure", "## Rules", "## Host mechanics"]


def section(text: str, heading: str) -> str:
    start = text.index(heading + "\n")
    end = text.find("\n## ", start + 1)
    return text[start:] if end == -1 else text[start:end]


class SkillTests(unittest.TestCase):
    def text(self, name: str) -> str:
        return SKILLS[name].read_text(encoding="utf-8")

    def test_sections_are_in_order(self) -> None:
        for name in SKILLS:
            with self.subTest(skill=name):
                self.assertEqual(re.findall(r"(?m)^## .*$", self.text(name)), HEADINGS)

    def test_ask_escalates_without_memory_ledger(self) -> None:
        self.assertIn("memory-ledger-not-found", section(self.text("ask"), "## Procedure"))

    def test_record_lists_its_outcomes_with_inputs(self) -> None:
        inputs = section(self.text("record"), "## Inputs and outcomes")
        for outcome in ("VOTED", "UNCHANGED", "NEW", "REFUSED"):
            with self.subTest(outcome=outcome):
                self.assertIn(f"`{outcome}", inputs)
        refused = next(line for line in inputs.splitlines() if "`REFUSED" in line)
        self.assertIn("memory-ledger", refused)

    def test_host_mechanics_names_the_script_on_each_host(self) -> None:
        for name in SKILLS:
            with self.subTest(skill=name):
                mechanics = section(self.text(name), "## Host mechanics")
                self.assertIn("${CLAUDE_PLUGIN_ROOT}/scripts/deputy.py", mechanics)
                self.assertIn("<directory holding this SKILL.md>/../../scripts/deputy.py", mechanics)
                self.assertNotIn("${PLUGIN_ROOT}", self.text(name))

    def test_record_passes_the_codex_session_on_codex(self) -> None:
        self.assertIn("--host codex --session-id", section(self.text("record"), "## Host mechanics"))


if __name__ == "__main__":
    unittest.main()
