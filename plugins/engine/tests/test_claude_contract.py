import json
import subprocess
import tempfile
import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
TASK = PLUGIN_DIR / "bin" / "task"
ROSTER = "[main-agent, independent-reviewer, adversarial-reviewer, critic]"
ADVISOR_PARTY = ("debate_party_config:\n  parties:\n    adversarial-reviewer:\n"
                 "      mechanism: advisor\n")
ALL_NATIVE = ("converge_seats: {main: native_subagent, finder: native_subagent, "
              "r1: native_subagent, r2: native_subagent, cutter: native_subagent}\n")


def _roles(*roles: str) -> str:
    return f"advisor_roles:\n  roles: [{', '.join(roles)}]\n  brief: Act only in these roles.\n"


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

    def _settlement(self, extra: str, roster: str = ROSTER) -> str:
        return (
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
            f"debate_roster: {roster}\n"
            + extra
        )

    def _validate(self, extra: str, roster: str = ROSTER):
        settlement = self._settlement(extra, roster)
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

    def _machine_validate(self, nodes: str, skills: str):
        settlement = (
            "task_type: pr-review\napproach: fixture\nprinciples: none\n"
            "goal:\n  succeeded: done\n  failed: never\n"
            f"state_machine: |\n  name: fixture\n  nodes:\n{nodes}"
            "request_assessment: fixture\nsource_of_truth:\n  scope: fixture\n"
            "debate_threshold: fixture\ndebate_round_cap: 1\n"
            "convergence_policy: unanimous\nconsented_stop_allowed: true\n"
            "debate_party_config: {}\n"
            f"{skills}"
            "review_fix_mode: accepted_only\n"
            "autonomy:\n  no_further_questions: true\n  permitted_mutations: [run tests]\n"
            f"debate_roster: {ROSTER}\n"
        )
        with tempfile.TemporaryDirectory(prefix="engine-skill-fields-") as tmp:
            path = Path(tmp) / "settlement.txt"
            path.write_text(f"{settlement}session_dir: {Path(tmp).resolve()}\n")
            return subprocess.run(
                [str(TASK), "session", "validate", "skill-run", "--dir", tmp,
                 "--settlement-file", str(path), "--prose"],
                capture_output=True, text=True, check=False,
            )

    def test_strict_validation_requires_skill_fields_only_for_nodes_present(self):
        review_only = (
            "    clarify:\n      next: [review]\n"
            "    review:\n      next: [succeeded]\n"
            "    succeeded:\n      terminal: true\n"
            "    failed:\n      terminal: true\n"
        )
        result = self._machine_validate(review_only, "review_skill: review\n")
        self.assertEqual(result.returncode, 0, result.stderr)

        spec_node = (
            "    clarify:\n      next: [spec]\n"
            "    spec:\n      next: [succeeded]\n"
            "    succeeded:\n      terminal: true\n"
            "    failed:\n      terminal: true\n"
        )
        result = self._machine_validate(spec_node, "review_skill: review\n")
        self.assertEqual(result.returncode, 1)
        self.assertIn("spec_skill", result.stderr)

    def test_strict_validation_requires_test_skill_for_triage_node(self):
        triage_node = (
            "    clarify:\n      next: [triage]\n"
            "    triage:\n      next: [succeeded]\n"
            "    succeeded:\n      terminal: true\n"
            "    failed:\n      terminal: true\n"
        )
        result = self._machine_validate(triage_node, "review_skill: review\n")
        self.assertEqual(result.returncode, 1)
        self.assertIn("test_skill", result.stderr)

        result = self._machine_validate(triage_node, "test_skill: test\nreview_skill: review\n")
        self.assertEqual(result.returncode, 0, result.stderr)

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

    def test_refused_mechanism_names_the_party_and_the_bad_value(self):
        result = self._validate("debate_party_config: {}\n" + self._party("codex"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("critic", result.stderr)
        self.assertIn("codex", result.stderr)

    def test_refused_mechanism_in_party_config_names_the_bad_value(self):
        config = ("debate_party_config:\n  parties:\n    adversarial-reviewer:\n"
                  "      mechanism: bogus\n")
        result = self._validate(config + self._party("advisor"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("bogus", result.stderr)

    def test_claude_refuses_unknown_mechanism_in_party_config(self):
        config = ("debate_party_config:\n  parties:\n    adversarial-reviewer:\n"
                  "      mechanism: bogus\n")
        result = self._validate(config + self._party("advisor"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("debate_party_config.parties.adversarial-reviewer.mechanism", result.stderr)

    def test_settlement_accepts_consistent_advisor_roles_and_seats(self):
        for extra in (
            "debate_party_config: {}\n" + ALL_NATIVE,
            "debate_party_config: {}\n",
            "debate_party_config: {}\ncodex_role: adversarial reviewer\n",
            _roles("adversarial-reviewer", "refuter", "gap-hunter")
            + "converge_seats: {r2: advisor}\n" + ADVISOR_PARTY,
            "debate_party_config: {}\nconverge_seats: {r2: advisor}\n",
        ):
            result = self._validate(extra)
            self.assertEqual(result.returncode, 0, f"{extra}\n{result.stderr}")

    def test_settlement_refuses_advisor_role_without_its_seat_or_party(self):
        party = "debate_party_config:\n  parties:\n    {role}:\n      {field}\n"
        cases = (
            (_roles("refuter") + "converge_seats: {r2: native_subagent}\n"
             "debate_party_config: {}\n", ROSTER,
             ("advisor_roles", "names refuter but converge_seats.r2 is native_subagent",
              "set converge_seats.r2: advisor")),
            (_roles("gap-hunter") + "debate_party_config: {}\n", ROSTER,
             ("names gap-hunter but converge_seats.r2 is native_subagent",)),
            (_roles("adversarial-reviewer")
             + party.format(role="adversarial-reviewer", field="label: Adversary"), ROSTER,
             ("debate_party_config.parties.adversarial-reviewer.mechanism",
              "set debate_party_config.parties.adversarial-reviewer.mechanism: advisor")),
            (_roles("independent-reviewer")
             + party.format(role="independent-reviewer", field="mechanism: native_subagent"),
             ROSTER,
             ("debate_party_config.parties.independent-reviewer.mechanism",
              "mechanism is native_subagent")),
            (_roles("adversarial-reviewer") + ADVISOR_PARTY, "[main-agent, critic]",
             ("debate_roster", "add adversarial-reviewer to debate_roster")),
            (_roles("adversarial-reviewer") + ADVISOR_PARTY + "      enabled: false\n", ROSTER,
             ("debate_party_config.parties.adversarial-reviewer.enabled",
              "remove enabled: false")),
        )
        for extra, roster, fragments in cases:
            result = self._validate(extra, roster)
            self.assertEqual(result.returncode, 1, f"{extra}\n{result.stderr}")
            for fragment in fragments:
                self.assertIn(fragment, result.stderr)

    def test_settlement_refuses_every_advisor_seat_but_r2(self):
        for seat in ("main", "finder", "r1", "cutter"):
            for seats in (f"{{{seat}: advisor}}", f"{{{seat}: advisor, r2: advisor}}"):
                result = self._validate(f"debate_party_config: {{}}\nconverge_seats: {seats}\n")
                self.assertEqual(result.returncode, 1, f"{seats}\n{result.stderr}")
                self.assertIn(f"converge_seats.{seat}", result.stderr)
                self.assertIn("only r2 may be advisor", result.stderr)
                self.assertIn(f"set converge_seats.{seat}: native_subagent", result.stderr)

    def test_settlement_lists_every_seat_problem_in_one_refusal(self):
        result = self._validate(
            "advisor_roles:\n  roles: [bogus, refuter, refuter]\n"
            "converge_seats: {r9: advisor, r1: robot, main: advisor}\n"
            "debate_party_config: {}\n")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr.count("session validate refused"), 1, result.stderr)
        for fragment in ("unknown role 'bogus'", "duplicate roles refuter", "advisor_roles.brief",
                         "unknown seat 'r9'", "unknown mechanism 'robot'",
                         "converge_seats.main", "only r2 may be advisor"):
            self.assertIn(fragment, result.stderr)

    def test_session_init_refuses_mismatched_seats_and_writes_no_ledger(self):
        with tempfile.TemporaryDirectory(prefix="engine-seat-init-") as tmp:
            path = Path(tmp) / "settlement.txt"
            path.write_text(self._settlement(
                _roles("refuter") + "converge_seats: {r2: native_subagent}\n"
                "debate_party_config: {}\n"))
            result = subprocess.run(
                [str(TASK), "session", "init", "seat-run", "--dir", tmp,
                 "--settlement-file", str(path), "--prose"],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn("session init refused", result.stderr)
            self.assertIn("set converge_seats.r2: advisor", result.stderr)
            self.assertFalse((Path(tmp) / "seat-run.md").exists())

    def _resolve_seats_output(self, user: str | None, project: str | None,
                              task: str | None, *extra: str) -> str:
        with tempfile.TemporaryDirectory(prefix="engine-seat-config-") as tmp:
            root = Path(tmp)
            args = [str(TASK), "config", "resolve", "--name", "converge-seats",
                    "--project-root", str(root)]
            for flag, text in (("--user-config", user), ("--project-config", project),
                               ("--task-config-file", task)):
                path = root / f"{flag.strip('-')}.yaml"
                if text is not None:
                    path.write_text(text)
                args += [flag, str(path)]
            return subprocess.run([*args, *extra], capture_output=True, text=True,
                                  check=True).stdout

    def _resolve_seats(self, *, user: str | None = None, project: str | None = None,
                       task: str | None = None) -> dict:
        return json.loads(self._resolve_seats_output(user, project, task, "--json"))

    def test_converge_seats_resolve_to_all_five_seats(self):
        payload = self._resolve_seats(task="seats: {r2: advisor}\n")
        self.assertEqual(payload["converge_seats"], {
            "main": "native_subagent", "finder": "native_subagent", "r1": "native_subagent",
            "r2": "advisor", "cutter": "native_subagent"})
        self.assertIn("write `converge_seats` into settlement verbatim", payload["next"])
        self.assertIn("advisor_roles", payload["next"])
        self.assertIn("only `r2` may be `advisor`", payload["next"])
        prose = self._resolve_seats_output(None, None, "seats: {r2: advisor}\n")
        self.assertIn("SEAT      r2 advisor\n", prose)
        self.assertIn("SEAT      main native_subagent\n", prose)
        self.assertTrue(prose.rstrip("\n").splitlines()[-1].startswith("next: write `converge_seats`"))
        empty = self._resolve_seats()
        self.assertEqual(set(empty["converge_seats"].values()), {"native_subagent"})
        self.assertEqual(len(empty["converge_seats"]), 5)

    def test_resolved_converge_seats_validate_in_settlement(self):
        unknown = self._resolve_seats(task="seats: {r9: advisor}\n")["converge_seats"]
        self.assertEqual(unknown["r9"], "advisor")
        refused = self._validate(f"debate_party_config: {{}}\nconverge_seats: {json.dumps(unknown)}\n")
        self.assertEqual(refused.returncode, 1)
        self.assertIn("unknown seat 'r9'", refused.stderr)
        seats = self._resolve_seats(task="seats: {r2: advisor}\n")["converge_seats"]
        accepted = self._validate(_roles("refuter", "gap-hunter") + "debate_party_config: {}\n"
                                  f"converge_seats: {json.dumps(seats)}\n")
        self.assertEqual(accepted.returncode, 0, accepted.stderr)

    def test_task_layer_seats_override_user_and_project_layers(self):
        native = "seats: {main: native_subagent, finder: native_subagent, r1: native_subagent, " \
                 "r2: native_subagent, cutter: native_subagent}\n"
        payload = self._resolve_seats(user="seats: {r2: advisor}\n",
                                      project="seats: {r2: advisor}\n", task=native)
        self.assertEqual(payload["converge_seats"]["r2"], "native_subagent")

    def test_manifest_declares_required_peer_dependencies(self):
        manifest = json.loads(
            (PLUGIN_DIR / ".claude-plugin" / "plugin.json").read_text()
        )
        self.assertEqual(manifest["dependencies"],
                         ["converge", "spec", "test", "review", "advisor", "memory-ledger", "deputy"])

    def test_compaction_recall_uses_session_start_compact(self):
        hooks = json.loads((PLUGIN_DIR / "hooks" / "hooks.json").read_text())["hooks"]
        self.assertEqual(
            [(entry["matcher"], [h["command"] for h in entry["hooks"]])
             for entry in hooks["SessionStart"]],
            [("compact",
              ["python3 ${CLAUDE_PLUGIN_ROOT}/hooks/adapter.py --handler session_recall --matcher-pattern compact"])],
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
            'python3 ${CLAUDE_PLUGIN_ROOT}/hooks/adapter.py --handler stop_reminder --matcher-pattern ""',
        )
        post_tool_commands = [
            hook["command"]
            for group in hooks["PostToolUse"]
            for hook in group["hooks"]
        ]
        self.assertEqual(
            post_tool_commands,
            ["python3 ${CLAUDE_PLUGIN_ROOT}/hooks/adapter.py --handler state_nudge --matcher-pattern '.*'"],
        )
        self.assertEqual(
            [entry["matcher"] for entry in hooks["PostToolUse"]],
            [".*"],
        )

    def test_spec_review_settlement_fields_are_optional_and_shaped(self):
        accepted = self._validate(
            "spec_review_skill: spec-review\nspec_review_override: spec-review\n"
            "spec_debate_mode: threshold\ndebate_party_config: {}\n"
        )
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        refused = self._validate("spec_debate_mode: later\n")
        self.assertEqual(refused.returncode, 1)
        self.assertIn("spec_debate_mode", refused.stderr)

    def test_spec_review_angles_resolve_as_find_angles(self):
        angle_file = (PLUGIN_DIR.parents[1] / "plugins" / "spec" / "skills" /
                      "spec-review" / "references" / "find-angles.yaml")
        result = subprocess.run(
            [str(PLUGIN_DIR.parents[1] / "plugins" / "converge" / "bin" / "converge"),
             "angles", "--tag", "find", "--angles", str(angle_file), "--json"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(json.loads(result.stdout)["angles"]), 8)

if __name__ == "__main__":
    unittest.main()
