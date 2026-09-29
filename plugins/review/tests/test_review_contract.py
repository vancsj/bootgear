import json
import re
import unittest
from pathlib import Path

import yaml

PLUGIN_DIR = Path(__file__).resolve().parents[1]
SKILL_DIR = PLUGIN_DIR / "skills" / "review"
REFERENCES = SKILL_DIR / "references"
ANGLE_FILES = ("find-angles.yaml", "design-patterns.yaml")
ANGLE_KEYS = {"id", "tag", "tell", "asks", "lens", "cost"}


class ReviewContractTest(unittest.TestCase):
    def setUp(self):
        self.skill = (SKILL_DIR / "SKILL.md").read_text()

    def test_keeps_override_acceptance_and_reporting_contract(self):
        self.assertIn("## Check for an override first", self.skill)
        self.assertIn("### 6. Apply accepted feedback", self.skill)
        self.assertIn("Acceptance is per comment.", self.skill)
        self.assertIn("an overall PR approval;", self.skill)
        self.assertIn("### `accepted_only`", self.skill)
        self.assertIn("### `auto_within_permitted_mutations`", self.skill)
        for field in ("`applied`", "`accepted but not applied`",
                      "`rejected or won't-fix`", "`unclear`"):
            self.assertIn(field, self.skill)
        self.assertIn("ending outcome\nand iteration count", self.skill)

    def test_runs_converge_with_plugin_angle_files(self):
        self.assertIn("`quick`: lenses `correctness,tests`", self.skill)
        self.assertIn(
            "`full`: lenses `correctness,security,architecture,tests,simplicity,contract`",
            self.skill,
        )
        self.assertIn("Initialize the slate through the public `converge` command", self.skill)
        self.assertIn("slate `<run-id>-review-<n>`", self.skill)
        self.assertIn("`<session-dir>/converge` as an absolute", self.skill)
        self.assertIn("`$HOME/.bootgear/converge` as an absolute path", self.skill)
        self.assertIn("Run the `converge` skill in `full` mode", self.skill)
        self.assertIn("--rule R###", self.skill)
        self.assertIn("`cutoff: {report_rules: [<every rule ID whose severity is at or above", self.skill)
        self.assertIn("--config <converge-dir>/<slate>.yaml", self.skill)

    def test_depth_agent_allocation(self):
        self.assertIn("`quick`: lenses `correctness,tests`; agents main, F, R1, C; no gap hunt.",
                      self.skill)
        self.assertIn("agents main, F, R1, R2, C; gap hunt by R2.", self.skill)
        self.assertIn("The cap counts this slate only", self.skill)
        self.assertIn("F covers every find angle of every lens", self.skill)
        self.assertIn("each refuter\ntakes ≥1 unused attack angle per claim per round", self.skill)
        self.assertIn("Spawn one finder, F, for every lens", self.skill)
        self.assertIn("one brief listing\nevery lens with its scope", self.skill)
        self.assertNotIn("one finder per lens", self.skill)
        self.assertNotIn("fresh", self.skill)

    def test_rationale_for_agent_budget_lives_in_reference(self):
        reference = (SKILL_DIR / "reference.md").read_text()
        self.assertIn("at most five agents per task", reference)
        self.assertIn("unused-angle rule", reference)
        self.assertNotIn("token", self.skill)

    def test_gap_hunt_then_cutoff_then_render(self):
        self.assertIn("### 4. Gap hunt", self.skill)
        self.assertIn("`origin: gap-hunt`", self.skill)
        self.assertIn("`full` only; `quick` has no gap hunt.", self.skill)
        self.assertIn("continue R2 as the gap-hunt finder", self.skill)
        self.assertIn("R1 refutes them", self.skill)
        self.assertIn("asked but missing, present but unasked", self.skill)
        gap = self.skill.index("### 4. Gap hunt")
        cutoff = self.skill.index("Run the fixed cutoff action printed by the CLI")
        self.assertLess(gap, cutoff)
        # `converge cutoff` prints `next: converge render ...`; the skill does not repeat it.
        self.assertNotIn(
            "converge cutoff <slate> --dir <converge-dir>\nconverge render", self.skill
        )

    def test_routes_choices_and_records_leave_args(self):
        self.assertIn("report it to the caller for the `review-debate` node", self.skill)
        self.assertIn("Standalone: report it to the user.", self.skill)
        self.assertIn(
            "`--leave-arg slate=<slate> --leave-arg converge_dir=<converge-dir>`",
            self.skill,
        )
        self.assertIn(
            "Record the slate, converge directory, snapshot, and render counts",
            self.skill,
        )

    def test_iterate_to_closure_outcomes(self):
        for outcome in ("`handoff`", "`comment_only`", "`clean`", "`below_cutoff`", "`blocked`",
                        "`no_progress`", "`iteration_cap`"):
            self.assertIn(f"- **{outcome}:**", self.skill)
        self.assertIn("whose refute\nstate converged as `survived`", self.skill)
        self.assertIn("`difficulty` is `trivial` or `local`", self.skill)
        self.assertIn("re-reviews the result with a new slate", self.skill)
        self.assertIn("skill handed back `blocked`", self.skill)

    def test_hands_fixing_to_a_fix_node(self):
        self.assertIn("public engine state\ninterface", self.skill)
        self.assertIn("In an active run, apply no claim in any mode; fixing happens only "
                      "in the `fix` node.", self.skill)
        self.assertIn("When `machine.nodes[current].next` includes `fix` and the mode would "
                      "apply at least one claim, end the iteration after sub-task 5 with "
                      "outcome `handoff`", self.skill)
        self.assertIn("the ids of those claims; `execute` applies them in the `fix` node.", self.skill)
        self.assertIn("includes `fix` and the fix list is empty, end with the outcome the "
                      "render gives below: `clean`, `below_cutoff`, or `blocked`.", self.skill)
        self.assertIn("- **`handoff`:** In an active run, the current node has a `fix` edge "
                      "and the\n  mode would apply at least one claim", self.skill)
        self.assertIn("Otherwise, end the iteration after sub-task 5 with outcome "
                      "`comment_only`: report every surviving claim and apply none, "
                      "whatever `review_fix_mode` says.", self.skill)
        self.assertIn("- **`comment_only`:** In an active run, the current node has no "
                      "`fix` edge.", self.skill)
        self.assertIn("For `comment_only`, report every\nsurviving claim as a comment", self.skill)
        self.assertNotIn("current node has no `fix` edge — or any", self.skill)
        self.assertIn("- **`clean`:** A re-review's render, or an active run's single-pass "
                      "render,\n  has no `reported` claim", self.skill)
        self.assertIn("For `handoff`, return the fix list (claim ids)", self.skill)
        self.assertIn("Claude's adapters are `<plugin-dir>/bin/task`", self.skill)

    def test_rereview_passes_snapshot_since_and_delta(self):
        text = self.skill
        flat = " ".join(text.split())
        start = flat.index("### 2. Start the slate")
        find = flat.index("### 3. Find, refute, cut")
        self.assertIn("In an active run, add `--snapshot --pass <n>` to `init`; for `<n>` ≥ 2, "
                      "also add `--since <run-id>-review-<n-1>`.", flat[start:find])
        self.assertIn("If `init` refuses a `--since` check, keep `--pass <n>` and stop: have "
                      "`execute` run `resolve` for the baseline this pass reviews against",
                      flat[start:find])
        self.assertIn("`init` carries no other baseline, so the decision is one of: rerun "
                      "`init` without `--since`, reviewing the full change as a recorded "
                      "widening; or stop the review `blocked`. Record that decision, then act "
                      "on it.", flat[start:find])
        self.assertIn("Also add `--project-root <repo root>` to `init`, where `<repo root>` is the top "
                      "level of the work tree holding the change under review", flat[start:find])
        self.assertIn("Right after `init` succeeds, record the slate so `execute` prunes its "
                      "snapshot however the review ends", flat[start:find])
        self.assertIn("Record the slate and snapshot through the public engine session command.",
                      flat[start:find])
        self.assertIn("For `<n>` ≥ 2, also give F the `git diff` command `init` printed and the "
                      "previous slate's `converge render` output as settled context. A claim "
                      "outside that diff is in scope only when the diff changes that code's "
                      "behaviour.", flat[find:flat.index("### 4. Gap hunt")])
        self.assertIn("Record the slate, converge directory, snapshot, and render counts", flat)

    def test_skill_holds_no_design_rationale_sections(self):
        self.assertNotIn("## Progressive disclosure", self.skill)
        self.assertNotIn("### 2. Verify each finding", self.skill)
        reference = (SKILL_DIR / "reference.md").read_text()
        self.assertIn("## Findings go through converge", reference)
        self.assertNotIn("## Verify before trusting a finding", reference)

    def test_angle_files_follow_converge_schema(self):
        ids = []
        for name in ANGLE_FILES:
            rows = yaml.safe_load((REFERENCES / name).read_text())
            self.assertIsInstance(rows, list, name)
            for row in rows:
                self.assertLessEqual(set(row), ANGLE_KEYS, row)
                self.assertRegex(row["id"], r"\A[a-z0-9]+(-[a-z0-9]+)*\Z")
                self.assertEqual(row["tag"], "find", row)
                self.assertTrue(row["tell"].strip(), row)
                self.assertTrue(row["asks"].strip(), row)
                if name == "design-patterns.yaml":
                    self.assertEqual(row["lens"], "architecture", row)
                    self.assertTrue(row["cost"].strip(), row)
                ids.append(row["id"])
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(len(yaml.safe_load((REFERENCES / ANGLE_FILES[0]).read_text())), 12)
        self.assertEqual(len(yaml.safe_load((REFERENCES / ANGLE_FILES[1]).read_text())), 39)

    def test_lenses_reference_covers_every_lens_and_design_meanings(self):
        lenses = (REFERENCES / "lenses.md").read_text()
        for lens in ("correctness", "security", "architecture", "tests",
                     "simplicity", "contract"):
            self.assertRegex(lenses, rf"\| `{lens}` \|")
        self.assertIn("`git log` churn", lenses)
        self.assertIn("Cost of reversal", lenses)
        self.assertIn("Cost scenario shown in this repo", lenses)
        self.assertIn("Fix effort now versus later", lenses)

    def test_manifest_declares_converge_dependency(self):
        manifest = json.loads((PLUGIN_DIR / ".claude-plugin" / "plugin.json").read_text())
        self.assertEqual(manifest["version"], "0.5.3")
        self.assertEqual(manifest["dependencies"], ["converge"])
        self.assertTrue(re.search(r"converge", manifest["description"]))


if __name__ == "__main__":
    unittest.main()
