import json
import subprocess

from claude_contract_test_support import PLUGIN_DIR, ClaudePackageContractTestCase
from gear_commands import CONVERGE


class ClaudePackageContractTest(ClaudePackageContractTestCase):
    def test_manifest_declares_required_peer_dependencies(self):
        manifest = json.loads(
            (PLUGIN_DIR / ".claude-plugin" / "plugin.json").read_text()
        )
        self.assertEqual(manifest["dependencies"],
                         ["cli", "converge", "spec", "test", "review", "advisor", "memory-ledger", "deputy"])

    def test_session_recall_runs_on_startup_clear_and_compact(self):
        hooks = json.loads((PLUGIN_DIR / "hooks" / "hooks.json").read_text())["hooks"]
        question_hook = hooks["PreToolUse"][0]
        self.assertEqual(question_hook["matcher"], "^AskUserQuestion$")
        self.assertEqual(question_hook["hooks"][0]["onFailure"], "block")
        self.assertIn("--handler question_boundary", question_hook["hooks"][0]["command"])
        self.assertEqual(
            [(entry["matcher"], [h["command"] for h in entry["hooks"]])
             for entry in hooks["SessionStart"]],
            [("startup|clear|compact",
              ['"${CLAUDE_PLUGIN_ROOT}/hooks/gear" --host claude adapter --handler session_recall --matcher-pattern \'startup|clear|compact\''])],
        )
        self.assertIn("PreCompact", hooks)
        self.assertIn("PostCompact", hooks)
        for event in ("PreCompact", "PostCompact"):
            self.assertEqual(hooks[event][0]["matcher"], "manual|auto")
            self.assertIn(
                "--handler compaction_observe --matcher-pattern 'manual|auto'",
                hooks[event][0]["hooks"][0]["command"],
            )
        self.assertEqual(
            hooks["Stop"][0]["hooks"][0]["command"],
            '"${CLAUDE_PLUGIN_ROOT}/hooks/gear" --host claude adapter --handler stop_reminder --matcher-pattern ""',
        )
        post_tool_commands = [
            hook["command"]
            for group in hooks["PostToolUse"]
            for hook in group["hooks"]
        ]
        self.assertEqual(
            post_tool_commands,
            ['"${CLAUDE_PLUGIN_ROOT}/hooks/gear" --host claude adapter --handler state_nudge --matcher-pattern \'.*\''],
        )
        self.assertEqual(
            [entry["matcher"] for entry in hooks["PostToolUse"]],
            [".*"],
        )

    def test_spec_review_settlement_fields_are_optional_and_shaped(self):
        accepted = self._validate(
            "spec_review_skill: spec-review\nspec_review_override: spec-review\n"
            "debate_mode: threshold\ndebate_party_config: {}\n"
        )
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        refused = self._validate("debate_mode: later\n")
        self.assertEqual(refused.returncode, 1)
        self.assertIn("debate_mode", refused.stderr)

    def test_spec_review_angles_resolve_as_find_angles(self):
        angle_file = (PLUGIN_DIR.parents[1] / "plugins" / "spec" / "skills" /
                      "spec-review" / "references" / "angles.yaml")
        result = subprocess.run(
            [*CONVERGE, "angles", "--tag", "find", "--angles", str(angle_file), "--json"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(json.loads(result.stdout)["angles"]), 14)

        attack = subprocess.run(
            [*CONVERGE, "angles", "--tag", "attack", "--angles", str(angle_file), "--json"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(attack.returncode, 0, attack.stderr)
        attack_ids = {row["id"] for row in json.loads(attack.stdout)["angles"]}
        self.assertEqual(len(attack_ids), 20)
        self.assertLessEqual(
            {"request-quote", "settled-elsewhere", "negative-oracle", "wrong-outcome-test", "style-not-defect"},
            attack_ids,
        )
