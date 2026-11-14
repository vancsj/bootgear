"""Mechanical skill schemas, local references, and shared host parity."""

import re
import unittest
from pathlib import Path
from urllib.parse import urlsplit

import yaml

REPO_ROOT = next(parent for parent in Path(__file__).resolve().parents
                 if (parent / "plugins/spec/skills").is_dir())
SKILLS = REPO_ROOT / "plugins/spec/skills"
LENSES = {"request-fit", "clarity-completeness", "architecture-fit", "simplicity",
          "proportionality", "testability"}
ANGLE_KEYS = {"id", "tag", "tell", "asks", "lens", "cost"}
KEBAB = r"\A[a-z0-9]+(-[a-z0-9]+)*\Z"
DESIGN_PATTERN_IDS = {
    "two-sources-of-truth", "implicit-state-machine", "partial-write", "non-idempotent-retry",
    "irreversible-migration", "invalid-states-representable", "no-timeout-backpressure",
    "config-sprawl",
}
MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def _rows(name: str) -> list[dict]:
    return yaml.safe_load((SKILLS / "spec-review/references" / name).read_text())


class SpecReviewContractTest(unittest.TestCase):
    def test_skill_metadata_is_valid_in_shared_source(self):
        for name in ("spec", "spec-review"):
            text = (SKILLS / name / "SKILL.md").read_text()
            _, frontmatter, _ = text.split("---", 2)
            metadata = yaml.safe_load(frontmatter)
            self.assertEqual(metadata["name"], name)
            self.assertIsInstance(metadata["description"], str)
            self.assertTrue(metadata["description"].strip())

    def test_angle_files_follow_converge_schema_in_shared_source(self):
        ids = []
        for name in ("angles.yaml", "design-patterns.yaml"):
            rows = _rows(name)
            self.assertIsInstance(rows, list, name)
            for row in rows:
                self.assertLessEqual(set(row), ANGLE_KEYS, row)
                self.assertRegex(row["id"], KEBAB)
                self.assertIn(row["tag"], ("find", "attack"), row)
                self.assertTrue(row["tell"].strip(), row)
                self.assertTrue(row["asks"].strip(), row)
                if row["tag"] == "find":
                    self.assertIn(row["lens"], LENSES, row)
                ids.append(row["id"])
        self.assertEqual(len(ids), len(set(ids)))

    def test_find_angles_cover_the_six_lenses_in_shared_source(self):
        rows = _rows("angles.yaml")
        self.assertEqual({row["lens"] for row in rows if row["tag"] == "find"}, LENSES)
        by_id = {row["id"]: row for row in rows}
        for name in ("value-lineage", "lifecycle-composition"):
            self.assertEqual(by_id[name]["tag"], "find")
            self.assertEqual(by_id[name]["lens"], "architecture-fit")

    def test_design_patterns_are_the_eight_architecture_fit_rows(self):
        rows = _rows("design-patterns.yaml")
        self.assertEqual({row["id"] for row in rows}, DESIGN_PATTERN_IDS)
        self.assertEqual(len(rows), len(DESIGN_PATTERN_IDS))
        for row in rows:
            self.assertEqual(row["tag"], "find", row)
            self.assertEqual(row["lens"], "architecture-fit", row)
            self.assertTrue(row["cost"].strip(), row)

    def test_local_markdown_references_resolve_in_shared_source(self):
        for name in ("spec", "spec-review"):
            skill = SKILLS / name
            for document in skill.rglob("*.md"):
                for target in MARKDOWN_LINK.findall(document.read_text()):
                    parsed = urlsplit(target)
                    if parsed.scheme or not parsed.path:
                        continue
                    resolved = (document.parent / parsed.path).resolve()
                    self.assertTrue(resolved.is_file(), (document, target))
                    self.assertTrue(resolved.is_relative_to(skill), (document, target))

    def test_reference_files_are_reachable_from_their_skill(self):
        for name in ("spec", "spec-review"):
            skill = SKILLS / name
            todo = [skill / "SKILL.md"]
            visited = set()
            while todo:
                path = todo.pop().resolve()
                if path in visited:
                    continue
                visited.add(path)
                if path.suffix != ".md":
                    continue
                for target in MARKDOWN_LINK.findall(path.read_text()):
                    parsed = urlsplit(target)
                    if not parsed.scheme and parsed.path:
                        todo.append((path.parent / parsed.path).resolve())
            for path in (skill / "references").iterdir():
                self.assertIn(path.resolve(), visited, path)

    def test_implementation_feedback_uses_spec_provider_for_each_host(self):
        text = (SKILLS / "spec/references/implementation-feedback.md").read_text()
        for host in ("Claude Code", "Codex CLI"):
            adapter = next(line for line in text.splitlines() if line.startswith(f"For {host},"))
            self.assertIn("`spec` for `<spec-plugin>`", adapter)

    def test_shared_skills_have_explicit_native_host_adapters(self):
        for name in ("spec", "spec-review"):
            text = (SKILLS / name / "SKILL.md").read_text()
            common, mechanics = text.split("\n## Host mechanics\n", 1)
            self.assertNotIn("--host claude", common)
            self.assertNotIn("--host codex", common)
            self.assertNotIn("codex-plugins", text)
            for header, host in (("Claude Code", "claude"), ("Codex", "codex")):
                adapter = mechanics.split(f"### {header}\n", 1)[1].split("\n### ", 1)[0]
                self.assertIn("cli:gear", adapter)
                self.assertIn(f"--host {host}", adapter)
                self.assertIn("spec spec-feedback", adapter)
                self.assertNotIn("engine spec-feedback", adapter)
                self.assertNotIn("engine converge", adapter)


if __name__ == "__main__":
    unittest.main()
