from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from quality import check_skill_references


class SkillReferenceTests(unittest.TestCase):
    def _fixture(self, source: str) -> Path:
        root = Path(tempfile.mkdtemp(prefix="skill-reference-test-"))
        skill = root / "plugins" / "demo" / "skills" / "one"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(source)
        return root

    def _fixture_with_two_skills(self, source: str) -> Path:
        root = self._fixture(source)
        other = root / "plugins" / "demo" / "skills" / "two"
        other.mkdir(parents=True)
        (other / "SKILL.md").write_text("---\nname: two\n---\n")
        return root

    def _fixture_with_reference(self, source: str, reference: str) -> Path:
        root = self._fixture(source)
        (root / "plugins" / "demo" / "skills" / "one" / "reference.md").write_text(reference)
        return root

    def test_repository_has_no_cross_skill_private_references(self) -> None:
        self.assertEqual(check_skill_references.find_violations(), [])

    def test_cross_skill_path_is_rejected(self) -> None:
        root = self._fixture("See `../two/SKILL.md`.\n")
        violations = check_skill_references.find_violations(root)
        self.assertEqual([item.target for item in violations], ["two"])

    def test_cross_skill_private_phrase_is_rejected(self) -> None:
        root = self._fixture("See the two skill's own reference.\n")
        violations = check_skill_references.find_violations(root)
        self.assertEqual([item.target for item in violations], ["two"])

    def test_markdown_code_private_phrase_is_rejected(self) -> None:
        root = self._fixture("See the two skill's `reference.md`.\n")
        violations = check_skill_references.find_violations(root)
        self.assertEqual([item.target for item in violations], ["two"])

    def test_host_specific_skill_invocation_is_rejected(self) -> None:
        root = self._fixture_with_two_skills(
            "---\nname: one\n---\nUse `$two` or `/two`.\n"
        )
        violations = check_skill_references.find_violations(root)
        self.assertEqual([item.target for item in violations], ["two", "two"])

    def test_repeated_frontmatter_name_heading_is_rejected(self) -> None:
        root = self._fixture("---\nname: one\n---\n# one\n")
        violations = check_skill_references.find_violations(root)
        self.assertEqual([item.rule for item in violations], ["duplicate skill-name heading"])

    def test_same_skill_reference_and_public_outcome_are_allowed(self) -> None:
        root = self._fixture(
            "See `../one/SKILL.md` and use the two skill's public outcome.\n"
        )
        self.assertEqual(check_skill_references.find_violations(root), [])

    def test_same_skill_reference_resolves_a_heading(self) -> None:
        root = self._fixture_with_reference(
            "---\nname: one\n---\nRead `reference.md` § `Output contract`.\n",
            "# rationale\n\n## Output contract\n",
        )
        self.assertEqual(check_skill_references.find_violations(root), [])

    def test_same_skill_reference_resolves_nested_heading_path(self) -> None:
        root = self._fixture_with_reference(
            "---\nname: one\n---\nRead `reference.md` § `Output contract` > `JSON`.\n",
            "# rationale\n\n## Output contract\n\n### JSON\n",
        )
        self.assertEqual(check_skill_references.find_violations(root), [])

    def test_same_skill_reference_rejects_missing_heading(self) -> None:
        root = self._fixture_with_reference(
            "---\nname: one\n---\nRead `reference.md` § `Missing`.\n",
            "# rationale\n",
        )
        violations = check_skill_references.find_violations(root)
        self.assertEqual([item.rule for item in violations], ["missing same-skill reference heading"])

    def test_same_skill_reference_rejects_duplicate_heading(self) -> None:
        root = self._fixture_with_reference(
            "---\nname: one\n---\nRead `reference.md` § `Output contract`.\n",
            "# rationale\n\n## Output contract\n\n## Output contract\n",
        )
        violations = check_skill_references.find_violations(root)
        self.assertEqual([item.rule for item in violations], ["duplicate same-skill reference heading"])

    def test_broad_same_skill_reference_is_rejected(self) -> None:
        root = self._fixture_with_reference(
            "---\nname: one\n---\nRead `reference.md` for rationale.\n",
            "# rationale\n\n## Output contract\n",
        )
        violations = check_skill_references.find_violations(root)
        self.assertEqual([item.rule for item in violations], ["unaddressed same-skill reference"])


if __name__ == "__main__":
    unittest.main()
