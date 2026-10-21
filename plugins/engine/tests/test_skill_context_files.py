"""Skill docs that name the project's principles and standards files as context
files; each test pins one stable substring per skill."""

import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = PLUGIN_DIR.parents[1]
SKILLS = {
    "clarify": PLUGIN_DIR / "skills" / "clarify" / "SKILL.md",
    "execute": PLUGIN_DIR / "skills" / "execute" / "SKILL.md",
    "debate": PLUGIN_DIR / "skills" / "debate" / "SKILL.md",
    "spec": REPO_ROOT / "plugins" / "spec" / "skills" / "spec" / "SKILL.md",
    "spec-review": REPO_ROOT / "plugins" / "spec" / "skills" / "spec-review" / "SKILL.md",
    "converge": REPO_ROOT / "plugins" / "converge" / "skills" / "converge" / "SKILL.md",
    "review": REPO_ROOT / "plugins" / "review" / "skills" / "review" / "SKILL.md",
    "test": REPO_ROOT / "plugins" / "test" / "skills" / "test" / "SKILL.md",
}
PRINCIPLES = "`.bootgear/config/principles.md`"
REVIEW_STANDARD = "`.bootgear/config/review-standard.md`"
TEST_STANDARD = "`.bootgear/config/test-standard.md`"
STANDARD_FILES = "each standard file in `.bootgear/config/`"
USER_PRINCIPLES = "the host user-principles file"


def _text(name: str) -> str:
    # One space between words, so a re-wrapped line still matches.
    return " ".join(SKILLS[name].read_text().split())


def _section(name: str, heading: str) -> str:
    text = SKILLS[name].read_text()
    start = text.index(f"{heading}\n")
    end = text.find("\n## ", start + len(heading))
    return " ".join(text[start : end if end != -1 else len(text)].split())


class SkillContextFilesTest(unittest.TestCase):
    def assertPinned(self, pins: dict[str, str]):
        for name, pin in pins.items():
            with self.subTest(skill=name):
                self.assertIn(pin, _text(name), f"{SKILLS[name]} lost its context-file rule")

    def test_clarify_reads_principles_and_both_standards(self):
        self.assertPinned({
            "clarify": f"and {PRINCIPLES}, {REVIEW_STANDARD} and {TEST_STANDARD} from the project root, each when present",
        })

    def test_execute_briefs_sub_agents_with_context_files(self):
        with self.subTest(skill="execute"):
            self.assertIn("## Briefing sub-agents", _text("execute"))
            self.assertIn(
                f"with the paths of {PRINCIPLES}, of {USER_PRINCIPLES} and of each standard file",
                _section("execute", "## Briefing sub-agents"),
            )

    def test_execute_reads_standards_where_it_reads_principles(self):
        with self.subTest(skill="execute"):
            self.assertIn(
                f"At the same triggers, read {REVIEW_STANDARD} and {TEST_STANDARD} in full",
                _section("execute", "## Reading and merging principles"),
            )

    def test_spec_reads_principles_and_standards(self):
        self.assertPinned({
            "spec": f"Read {PRINCIPLES}, {USER_PRINCIPLES}, {REVIEW_STANDARD} and {TEST_STANDARD}",
        })

    def test_role_briefs_name_principles_and_standard_files(self):
        self.assertPinned({
            "spec-review": f"Name {PRINCIPLES}, {USER_PRINCIPLES} and {STANDARD_FILES} in the brief of every role",
            "review": f"Name {PRINCIPLES}, {USER_PRINCIPLES} and {STANDARD_FILES} as context files for F, R1, R2 and C",
            "test": f"name {PRINCIPLES}, {USER_PRINCIPLES} and {STANDARD_FILES} in its brief",
        })

    def test_converge_gives_role_agents_the_context_files(self):
        self.assertPinned({
            "converge": "the context files that the caller names, and the instruction to read them",
        })

    def test_debate_briefs_parties_with_standard_files(self):
        self.assertPinned({
            "debate": "the paths of the project's standard files in `.bootgear/config/`, each when present, and the instruction to read them first",
        })


if __name__ == "__main__":
    unittest.main()
