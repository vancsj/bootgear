import json
import subprocess
import tempfile
import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
TASK = PLUGIN_DIR / "bin" / "task"


class ClaudePackageContractTest(unittest.TestCase):
    def test_debate_party_config_merges_stable_ids(self):
        with tempfile.TemporaryDirectory(prefix="engine-debate-config-") as tmp:
            root = Path(tmp)
            user = root / "user.yaml"
            project = root / "project.yaml"
            task = root / "task.yaml"
            user.write_text("defaults:\n  model: base-model\n")
            project.write_text(
                "parties:\n  independent-reviewer:\n    model: project-model\n"
            )
            task.write_text(
                "parties:\n  independent-reviewer:\n    profile: reviewer\n"
                "    label: Independent reviewer\n"
                "    prompt: Verify the proposal independently.\n"
                "    enabled: true\n"
            )
            result = subprocess.run(
                [str(TASK), "config", "resolve", "--name", "debate-parties",
                 "--project-root", str(root), "--user-config", str(user),
                 "--project-config", str(project), "--task-config-file", str(task),
                 "--report", "models", "--json"],
                capture_output=True, text=True, check=True,
            )
            payload = json.loads(result.stdout)
            party = payload["effective"]["parties"]["independent-reviewer"]
            self.assertEqual(party["model"], "project-model")
            self.assertEqual(party["profile"], "reviewer")
            self.assertEqual(party["label"], "Independent reviewer")
            self.assertEqual(party["prompt"], "Verify the proposal independently.")
            self.assertTrue(party["enabled"])

    def test_debate_contract_uses_stable_ids_and_host_adapters(self):
        clarify = (PLUGIN_DIR / "skills" / "clarify" / "SKILL.md").read_text()
        debate = (PLUGIN_DIR / "skills" / "debate" / "SKILL.md").read_text()
        self.assertIn("config resolve --name debate-parties", clarify)
        self.assertIn("main-agent", clarify)
        self.assertIn("debate_roster", debate)
        self.assertIn("host-supported mechanism", debate)
        self.assertIn("<plugin-dir>/bin/task", debate[debate.index("## Host mechanics"):])


    def _validate(self, extra: str):
        settlement = (
            "task_type: ticket-to-pr\napproach: fixture\nprinciples: none\n"
            "goal:\n  succeeded: done\n  failed: never\n"
            "state_machine: |\n  name: smoke\n  nodes:\n    clarify:\n"
            "      next: [succeeded]\n    succeeded:\n      terminal: true\n"
            "    failed:\n      terminal: true\n"
            "request_assessment: fixture\nsource_of_truth:\n  scope: fixture\n"
            "debate_threshold: fixture\ndebate_round_cap: 1\n"
            "convergence_policy: unanimous\nconsented_stop_allowed: true\n"
            "spec_skill: spec\ntest_skill: test\nreview_skill: review\n"
            "review_fix_mode: accepted_only\n"
            "autonomy:\n  no_further_questions: true\n  permitted_mutations: [run tests]\n"
            "debate_roster: [main-agent, independent-reviewer, adversarial-reviewer, critic]\n"
            + extra
        )
        with tempfile.TemporaryDirectory(prefix="engine-debate-mechanism-") as tmp:
            path = Path(tmp) / "settlement.txt"
            path.write_text(f"{settlement}session_dir: {Path(tmp).resolve()}\n")
            return subprocess.run(
                [str(TASK), "session", "validate", "mech-run", "--dir", tmp,
                 "--settlement-file", str(path), "--prose"],
                capture_output=True, text=True, check=False,
            )

    def _party(self, mechanism: str) -> str:
        return ("debate_parties:\n  - id: critic\n    label: Critic\n"
                f"    prompt: Find counterexamples.\n    mechanism: {mechanism}\n")

    def test_resolved_party_config_with_models_validates_in_settlement(self):
        with tempfile.TemporaryDirectory(prefix="engine-debate-config-") as tmp:
            root = Path(tmp)
            task = root / "task.yaml"
            task.write_text(
                "defaults:\n  model: base-model\n"
                "parties:\n  independent-reviewer:\n    model: party-model\n"
                "    profile: reviewer\n    label: Independent reviewer\n"
                "    enabled: true\n"
            )
            result = subprocess.run(
                [str(TASK), "config", "resolve", "--name", "debate-parties",
                 "--project-root", str(root), "--user-config", str(root / "none.yaml"),
                 "--project-config", str(root / "none.yaml"),
                 "--task-config-file", str(task), "--report", "models", "--json"],
                capture_output=True, text=True, check=True,
            )
            payload = json.loads(result.stdout)
        self.assertEqual(payload["model_report"][1]["model"], "party-model")
        config = payload["debate_party_config"]
        self.assertEqual(config, {"parties": {"independent-reviewer": {
            "label": "Independent reviewer", "enabled": True}}})
        result = self._validate(
            f"debate_party_config: {json.dumps(config)}\n" + self._party("advisor"))
        self.assertEqual(result.returncode, 0, result.stderr)

    def _resolve_parties(self, parties_yaml: str) -> dict:
        with tempfile.TemporaryDirectory(prefix="engine-debate-config-") as tmp:
            root = Path(tmp)
            task = root / "task.yaml"
            task.write_text(parties_yaml)
            result = subprocess.run(
                [str(TASK), "config", "resolve", "--name", "debate-parties",
                 "--project-root", str(root), "--user-config", str(root / "none.yaml"),
                 "--project-config", str(root / "none.yaml"),
                 "--task-config-file", str(task), "--json"],
                capture_output=True, text=True, check=True,
            )
        return json.loads(result.stdout)

    def test_resolved_party_config_keeps_misspelt_fields_for_validation(self):
        payload = self._resolve_parties(
            "parties:\n  adversarial-reviewer:\n    enable: false\n    model: m\n")
        config = payload["debate_party_config"]
        self.assertEqual(config, {"parties": {"adversarial-reviewer": {"enable": False}}})
        result = self._validate(f"debate_party_config: {json.dumps(config)}\n" + self._party("advisor"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("contains unsupported fields", result.stderr)

    def test_resolved_party_config_json_names_the_next_step(self):
        payload = self._resolve_parties("parties:\n  critic:\n    label: Critic\n")
        self.assertIn("debate_party_config", payload["next"])
        self.assertIn("report-only", payload["next"])

    def test_bad_mechanism_reported_alongside_type_error(self):
        config = ("debate_party_config:\n  parties:\n    adversarial-reviewer:\n"
                  "      mechanism: bogus\n      label: 3\n")
        result = self._validate(config + self._party("advisor"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("values must be strings or booleans", result.stderr)
        self.assertIn("adversarial-reviewer.mechanism", result.stderr)

    def test_claude_accepts_advisor_and_native_subagent_mechanisms(self):
        config = ("debate_party_config:\n  parties:\n    adversarial-reviewer:\n"
                  "      mechanism: advisor\n")
        for mechanism in ("advisor", "native_subagent"):
            result = self._validate(config + self._party(mechanism))
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_claude_refuses_unknown_mechanism(self):
        result = self._validate("debate_party_config: {}\n" + self._party("codex"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("debate_parties.mechanism", result.stderr)

    def test_claude_refuses_unknown_mechanism_in_party_config(self):
        config = ("debate_party_config:\n  parties:\n    adversarial-reviewer:\n"
                  "      mechanism: bogus\n")
        result = self._validate(config + self._party("advisor"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("debate_party_config.parties.adversarial-reviewer.mechanism", result.stderr)

    def test_claude_adversarial_reviewer_defaults_to_advisor(self):
        debate = (PLUGIN_DIR / "skills" / "debate" / "SKILL.md").read_text()
        host = " ".join(debate[debate.index("## Host mechanics"):].split())
        self.assertIn("`independent-reviewer` runs as a fresh sub-agent", host)
        self.assertIn("`adversarial-reviewer` defaults to the `advisor` skill with "
                      "`--mode asking`, direct communication", host)
        self.assertIn("mechanism is `native_subagent` runs as a sub-agent", host)
        flat = " ".join(debate.split())
        self.assertNotIn("Codex CLI fails", flat)
        self.assertIn("missing `advisor` skill", flat)

    def test_debate_refuses_facts_and_runs_an_angle_round(self):
        debate = (PLUGIN_DIR / "skills" / "debate" / "SKILL.md").read_text()
        intake = debate.index("## Intake")
        self.assertLess(intake, debate.index("## Before debating"))
        self.assertLess(intake, debate.index("## Question id"))
        self.assertIn("Refuse it without calling\n  `record-decision`", debate)
        self.assertIn("`converge` skill", debate)
        self.assertIn("report it to the caller as\n  `inconclusive`", debate)
        self.assertIn("## Settled facts", debate)
        self.assertIn("converge render", debate)
        self.assertIn("Parties argue only the choice", debate)
        self.assertIn("### Angle round", debate)
        self.assertIn("public `converge` command", debate)
        self.assertIn("at least two of those angles that no party has used", debate)
        self.assertIn("`angles: <ids>`", debate)
        self.assertIn(
            "Record `unanimous_convergence` only if that round changes nothing", debate
        )
        self.assertLess(debate.index("### Angle round"),
                        debate.index("## Recording"))

    def test_debate_convergence_checks_the_current_goal(self):
        raw = (PLUGIN_DIR / "skills" / "debate" / "SKILL.md").read_text()
        debate = " ".join(raw.split())
        ending = debate[debate.index("## Ending a round"):debate.index("## Recording")]
        self.assertIn("`AMENDMENT goal`", ending)
        self.assertIn("`goal: kept`", ending)
        self.assertIn("`goal: narrowed <what>`", ending)
        self.assertIn("angles: <id>,<id>; goal: kept; <position", ending)
        degraded = debate[debate.index("After every owed retry has passed"):
                          debate.index("## Ending a round")]
        self.assertIn("`goal: kept` or `goal: narrowed <what>`", degraded)
        self.assertIn("`round_cap:` summary naming the narrowing", degraded)
        self.assertIn("in its position in the last retry round", degraded)
        self.assertIn("A late round-N response does not count", degraded)
        self.assertIn("Brief every party in that round to state `goal: kept`", debate)

    def test_debate_reference_matches_codex_copy(self):
        claude = (PLUGIN_DIR / "skills" / "debate" / "reference.md").read_bytes()
        codex = (PLUGIN_DIR.parents[1] / "codex-plugins" / "engine" / "skills"
                 / "debate" / "reference.md").read_bytes()
        self.assertEqual(claude, codex)
        self.assertIn(b"## Facts versus choices", claude)

    def test_manifest_declares_required_peer_dependencies(self):
        manifest = json.loads(
            (PLUGIN_DIR / ".claude-plugin" / "plugin.json").read_text()
        )
        self.assertEqual(manifest["version"], "0.16.1")
        self.assertEqual(manifest["dependencies"], ["converge", "spec", "test", "review", "advisor", "memory-ledger"])
    def test_compaction_recall_uses_session_start_compact(self):
        hooks = json.loads((PLUGIN_DIR / "hooks" / "hooks.json").read_text())["hooks"]
        self.assertNotIn("PostCompact", hooks)
        self.assertEqual(
            [(entry["matcher"], [h["command"] for h in entry["hooks"]])
             for entry in hooks["SessionStart"]],
            [("compact",
              ["python3 ${CLAUDE_PLUGIN_ROOT}/hooks/session_start_recall.py"])],
        )

    def test_clarify_lists_leave_check_commands_for_approval(self):
        clarify = (PLUGIN_DIR / "skills" / "clarify" / "SKILL.md").read_text()
        for text in ("reminder.leave_check", "tier it came from", "command -v <argv[0]>",
                     "the user's confirmation approves them"):
            self.assertIn(text, clarify)


    def test_state_machine_amendment_goes_through_state_amend(self):
        skills = PLUGIN_DIR / "skills"
        execute = (skills / "execute" / "SKILL.md").read_text()
        recall = (skills / "recall" / "SKILL.md").read_text()
        clarify = (skills / "clarify" / "SKILL.md").read_text()
        self.assertIn("task state amend <run-id> --dir <session-dir> --machine-file", execute)
        self.assertIn("<plugin-dir>/bin/task", execute[execute.index("## Host mechanics"):])
        self.assertIn("never `record-decision`", execute)
        self.assertIn("Then transition to the current node's `fix` branch and apply the "
                      "remaining claim ids there; with none remaining, take the branch that "
                      "matches the review without them.", " ".join(execute.split()))
        self.assertIn("On `comment_only`, report the claims and take the branch that matches "
                      "the reported outcome.", " ".join(execute.split()))
        self.assertIn("task state current <run-id> --dir <session-dir>", recall)
        self.assertIn("Skip `AMENDMENT state_machine` in this scan", recall)
        self.assertIn("For `pr-review` of a PR the user did not author, remove the `fix` node",
                      clarify)


    def test_domain_skills_are_invoked_by_plugin_qualified_name(self):
        skills = PLUGIN_DIR / "skills"
        execute = (skills / "execute" / "SKILL.md").read_text()
        reference = " ".join((skills / "execute" / "reference.md").read_text().split())
        recall = (skills / "recall" / "reference.md").read_text()
        self.assertIn("`spec:spec`, `test:test` and `review:review`", execute)
        self.assertIn("`spec:spec`, `test:test`, and `review:review`", recall)
        self.assertIn("a bare name fails when another installed plugin ships a skill "
                      "of the same name", reference)
        self.assertNotIn("bare name", execute)

    def test_failed_needs_no_confirm_leave(self):
        execute = " ".join((PLUGIN_DIR / "skills" / "execute" / "SKILL.md").read_text().split())
        self.assertIn("`--to failed` needs no `--confirm-leave`, from any node.", execute)

    def test_execute_scope_checks_review_fixes_and_prunes_snapshots(self):
        execute = (PLUGIN_DIR / "skills" / "execute" / "SKILL.md").read_text()
        flat = " ".join(execute.split())
        delegating = flat[flat.index("## Delegating to"):flat.index("## Checking and recording")]
        handoff = delegating.index("outcome of `handoff`, stay at `review`")
        scope = delegating.index("fix that adds a mechanism the signed-off spec does not name "
                                 "(a command, flag, check, guard, node or file), run `resolve` "
                                 "in the `scope and outcome` domain, with the spec as the scope "
                                 "source, or else the ticket or PR. On a settled rejection, the "
                                 "fix is out of scope: do not build it. On an undecided "
                                 "`resolve`, go to `review-debate`.")
        self.assertLess(handoff, scope)
        self.assertLess(scope, delegating.index("Then transition to the current node's `fix` branch"))
        ending = flat[flat.index("## Ending the run"):]
        prune = ending.index("converge prune <slate> [<slate>...] --project-root <repo root>")
        self.assertIn("Before `close`, succeeded or failed, delete this run's review snapshots, "
                      "naming each slate of a `review slate <slate> ...` decision once", ending)
        self.assertLess(prune, ending.index("session close <run-id>"))


if __name__ == "__main__":
    unittest.main()
