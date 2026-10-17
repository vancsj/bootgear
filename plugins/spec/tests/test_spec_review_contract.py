import re
import unittest
from pathlib import Path

import yaml

PLUGIN_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = PLUGIN_DIR.parents[1]
SKILL_DIR = PLUGIN_DIR / "skills" / "spec-review"
CODEX_SKILL_DIR = REPO_ROOT / "codex-plugins" / "engine" / "skills" / "spec-review"
REFERENCES = SKILL_DIR / "references"
ANGLE_KEYS = {"id", "tag", "tell", "asks", "lens", "cost"}
KEBAB = r"\A[a-z0-9]+(-[a-z0-9]+)*\Z"
DESIGN_PATTERN_IDS = {
    "two-sources-of-truth", "implicit-state-machine", "partial-write", "non-idempotent-retry",
    "irreversible-migration", "invalid-states-representable", "no-timeout-backpressure",
    "config-sprawl",
}
MACHINES = (
    REPO_ROOT / "plugins" / "engine" / "state-machines" / "ticket-writing.yaml",
    REPO_ROOT / "plugins" / "engine" / "state-machines" / "ticket-to-pr.yaml",
    REPO_ROOT / ".bootgear" / "config" / "state-machine-ticket-writing.yaml",
    REPO_ROOT / ".bootgear" / "config" / "state-machine-ticket-to-pr.yaml",
)
EXECUTE_SKILLS = (
    REPO_ROOT / "plugins" / "engine" / "skills" / "execute" / "SKILL.md",
    REPO_ROOT / "codex-plugins" / "engine" / "skills" / "execute" / "SKILL.md",
)
PASS_RULE = ("In an active run with `<n>` >= 3 add `--pass <n>` to `init`; with `<n>` 1 or 2, "
             "and always standalone, omit `--pass`.")
EXECUTE_PASS_RULE = "(the slate id, and from `<n>` >= 3 spec-review's `--pass <n>`)"
CAP_CLAUSE = re.compile(r"`<n>` is (\d+) and `revise` or `choices` is non-empty")


def _rows(name: str) -> list[dict]:
    return yaml.safe_load((REFERENCES / name).read_text())


def _skill() -> str:
    return (SKILL_DIR / "SKILL.md").read_text()


class SpecReviewContractTest(unittest.TestCase):
    def test_angle_files_follow_converge_schema(self):
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
                ids.append(row["id"])
        self.assertEqual(len(ids), len(set(ids)))

    def test_angle_counts(self):
        tags = [row["tag"] for row in _rows("angles.yaml")]
        self.assertEqual(tags.count("find"), 12)
        self.assertEqual(tags.count("attack"), 5)

    def test_design_patterns_are_the_eight_architecture_fit_rows(self):
        rows = _rows("design-patterns.yaml")
        self.assertEqual({row["id"] for row in rows}, DESIGN_PATTERN_IDS)
        self.assertEqual(len(rows), len(DESIGN_PATTERN_IDS))
        for row in rows:
            self.assertEqual(row["tag"], "find", row)
            self.assertEqual(row["lens"], "architecture-fit", row)
            self.assertTrue(row["cost"].strip(), row)

    def test_every_lens_states_what_is_out_of_scope(self):
        lines = (REFERENCES / "lenses.md").read_text().splitlines()
        self.assertEqual(sum(line.startswith("Out of scope:") for line in lines), 6)

    def test_skill_names_its_references_and_drops_the_precedence_line(self):
        skill = _skill()
        for text in ("angles.yaml", "design-patterns.yaml", "implementation-level"):
            self.assertIn(text, skill)
        self.assertNotIn("blocked > revise", skill)

    def test_mapping_rules_keep_their_order_and_an_unfinished_slate_resumes(self):
        skill = _skill()
        self.assertIn("already exists in the converge directory, do not `init`; resume it", skill)
        rules = ("1. missing role", "2. status `disputed`", "3. survived claim", "4. a finding of lens",
                 "5. a finding whose cut", "6. status `survived`", "7. any other finding")
        positions = [skill.find(f"   {rule}") for rule in rules]
        self.assertNotIn(-1, positions)
        self.assertEqual(positions, sorted(positions))

    def test_pass_flag_is_passed_only_from_slate_three_and_never_standalone(self):
        self.assertIn(PASS_RULE, _skill())
        for execute in EXECUTE_SKILLS:
            self.assertIn(EXECUTE_PASS_RULE, execute.read_text(), execute)

    def test_iteration_cap_equals_the_state_machines_max_visits(self):
        match = CAP_CLAUSE.search(_skill())
        self.assertIsNotNone(match, "SKILL.md has no iteration-cap clause")
        for machine in MACHINES:
            nodes = yaml.safe_load(machine.read_text())["nodes"]
            self.assertEqual(nodes["spec-review"]["max_visits"], int(match.group(1)), machine)

    def test_codex_twin_matches_the_claude_skill(self):
        claude, codex = (
            (directory / "SKILL.md").read_text().split("\n## Host mechanics\n")[0]
            for directory in (SKILL_DIR, CODEX_SKILL_DIR)
        )
        self.assertEqual(codex, claude)
        names = sorted(path.name for path in REFERENCES.iterdir())
        self.assertEqual(sorted(path.name for path in (CODEX_SKILL_DIR / "references").iterdir()), names)
        for name in names:
            self.assertEqual((CODEX_SKILL_DIR / "references" / name).read_bytes(),
                             (REFERENCES / name).read_bytes(), name)


if __name__ == "__main__":
    unittest.main()
