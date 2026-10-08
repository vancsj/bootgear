import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
MANIFEST = PLUGIN_DIR / ".codex-plugin" / "plugin.json"
HOOKS = PLUGIN_DIR / "hooks" / "hooks.json"
TASK = PLUGIN_DIR / "scripts" / "task"
CONVERGE = PLUGIN_DIR / "scripts" / "converge"
ROSTER = "[main-agent, independent-reviewer, adversarial-reviewer, critic]"
ADVISOR_PARTY = ("debate_party_config:\n  parties:\n    adversarial-reviewer:\n"
                 "      mechanism: advisor\n")
ALL_NATIVE = ("converge_seats: {main: native_subagent, finder: native_subagent, "
              "r1: native_subagent, r2: native_subagent, cutter: native_subagent}\n")
EXPECTED_SKILLS = {
    "clarify", "converge", "debate", "execute", "recall", "resolve", "review", "spec",
    "start", "spec-review", "test",
}


def _roles(*roles: str) -> str:
    return f"advisor_roles:\n  roles: [{', '.join(roles)}]\n  brief: Act only in these roles.\n"


class CodexPackageContractTest(unittest.TestCase):
    def test_manifest_and_hooks_are_codex_package_shape(self):
        manifest = json.loads(MANIFEST.read_text())
        self.assertEqual(manifest["name"], "engine")
        self.assertIn("converge", manifest["description"])
        self.assertNotIn("hooks", manifest)

        hooks = json.loads(HOOKS.read_text())["hooks"]
        session_start = hooks["SessionStart"][0]
        self.assertEqual(session_start["matcher"], "^(startup|resume|compact)$")
        self.assertIn("${PLUGIN_ROOT}", session_start["hooks"][0]["command"])
        self.assertIn("--handler session_recall", session_start["hooks"][0]["command"])
        stop = hooks["Stop"][0]["hooks"][0]
        self.assertIn("${PLUGIN_ROOT}/hooks/adapter.py", stop["command"])
        self.assertIn("--handler stop_reminder", stop["command"])
        post_tool_commands = [
            hook["command"]
            for group in hooks["PostToolUse"]
            for hook in group["hooks"]
        ]
        self.assertTrue(
            any("--handler stop_reminder" in command
                for command in post_tool_commands)
        )
        self.assertTrue(
            any("--handler state_nudge" in command for command in post_tool_commands)
        )
        for event in ("PreCompact", "PostCompact"):
            self.assertEqual(hooks[event][0]["matcher"], "manual|auto")
            self.assertIn(
                "--handler compaction_observe",
                hooks[event][0]["hooks"][0]["command"],
            )

    def test_engine_bundles_all_public_workflow_skills(self):
        skill_dirs = {
            path.parent.name for path in (PLUGIN_DIR / "skills").glob("*/SKILL.md")
        }
        self.assertEqual(skill_dirs, EXPECTED_SKILLS)
        for name in EXPECTED_SKILLS:
            self.assertTrue((PLUGIN_DIR / "skills" / name / "SKILL.md").is_file())

    def test_start_is_explicit_only(self):
        metadata = (PLUGIN_DIR / "skills" / "start" / "agents" / "openai.yaml").read_text()
        self.assertIn("allow_implicit_invocation: false", metadata)
        self.assertIn("$engine:start", metadata)

    def test_runtime_resolves_installed_root_and_reports_missing_uv(self):
        text = TASK.read_text()
        self.assertIn('PLUGIN_ROOT=${PLUGIN_ROOT:-', text)
        self.assertIn('uv run --project "$PLUGIN_ROOT"', text)

        env = {
            "PATH": "/usr/bin:/bin",
            "PLUGIN_ROOT": str(PLUGIN_DIR),
            "HOME": tempfile.mkdtemp(prefix="engine-contract-home-"),
        }
        result = subprocess.run(
            [str(TASK), "--help"],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        self.assertEqual(result.returncode, 127)
        self.assertIn("uv is required", result.stderr)

    def test_converge_wrapper_runs_bundled_script(self):
        script = CONVERGE.read_text()
        self.assertTrue(os.access(CONVERGE, os.X_OK))
        self.assertIn('PLUGIN_ROOT=${PLUGIN_ROOT:-', script)
        self.assertIn("export CONVERGE_HOST=codex", script)
        self.assertIn('uv run --project "$PLUGIN_ROOT" -m converge.cli', script)

    def test_converge_script_reports_missing_uv(self):
        result = subprocess.run(
            [str(CONVERGE), "--help"],
            capture_output=True,
            text=True,
            env={
                "PATH": "/usr/bin:/bin",
                "PLUGIN_ROOT": str(PLUGIN_DIR),
                "HOME": tempfile.mkdtemp(prefix="converge-contract-home-"),
            },
            check=False,
        )
        self.assertEqual(result.returncode, 127)
        self.assertIn("uv is required", result.stderr)

    def test_wrappers_default_prose_and_name_themselves(self):
        for wrapper in (TASK, CONVERGE):
            script = wrapper.read_text()
            self.assertIn('export BOOTGEAR_OUTPUT="${BOOTGEAR_OUTPUT:-prose}"', script)
            self.assertIn('export BOOTGEAR_PROG="$0"', script)
            self.assertLess(script.index("BOOTGEAR_PROG"), script.index("exec "))

        machine = PLUGIN_DIR / "state-machines" / "ticket-writing.yaml"
        env = {k: v for k, v in os.environ.items()
               if k not in ("BOOTGEAR_OUTPUT", "BOOTGEAR_PROG", "VIRTUAL_ENV")}

        def validate(*extra, **more):
            return subprocess.run([str(TASK), "state", "validate", str(machine), *extra],
                                  capture_output=True, text=True, check=False,
                                  env={**env, **more})

        prose = validate()
        self.assertEqual(prose.returncode, 0, prose.stderr)
        self.assertEqual(prose.stdout, f"{machine}: ok\n")
        for result in (validate("--json"), validate(BOOTGEAR_OUTPUT="json")):
            self.assertEqual(json.loads(result.stdout),
                             {"path": str(machine), "ok": True, "problems": []})

        refused = subprocess.run([str(TASK), "state", "validate"], capture_output=True,
                                 text=True, check=False, env=env)
        self.assertEqual(refused.returncode, 2)
        self.assertIn(f"\nexample: {TASK} state validate <machine.yaml>\n", refused.stderr)
        self.assertIn(f"\n  {TASK} session recall <run-id> --dir <session-dir>\n",
                      refused.stderr)

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
        with tempfile.TemporaryDirectory(prefix="engine-debate-mechanism-") as tmp:
            path = Path(tmp) / "settlement.txt"
            path.write_text(f"{self._settlement(extra, roster)}session_dir: {Path(tmp).resolve()}\n")
            return subprocess.run(
                [str(TASK), "session", "validate", "mech-run", "--dir", tmp,
                 "--settlement-file", str(path), "--prose"],
                capture_output=True, text=True, check=False,
            )

    def test_codex_accepts_advisor_and_native_subagent_mechanisms(self):
        party = ("debate_parties:\n  - id: critic\n    label: Critic\n"
                 "    prompt: Find counterexamples.\n    mechanism: {mechanism}\n")
        config = "debate_party_config:\n  parties:\n    critic:\n      mechanism: {mechanism}\n"
        for mechanism in ("advisor", "native_subagent"):
            for extra in ("debate_party_config: {}\n" + party.format(mechanism=mechanism),
                          config.format(mechanism=mechanism)):
                result = self._validate(extra)
                self.assertEqual(result.returncode, 0, f"{extra}\n{result.stderr}")
        for extra in ("debate_party_config: {}\n" + party.format(mechanism="bogus"),
                      config.format(mechanism="bogus")):
            result = self._validate(extra)
            self.assertEqual(result.returncode, 1, extra)
            self.assertIn("mechanism", result.stderr)
            self.assertIn("must be one of: advisor, native_subagent", result.stderr)

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

    def test_resolved_party_config_strips_only_model_and_profile(self):
        with tempfile.TemporaryDirectory(prefix="engine-debate-config-") as tmp:
            root = Path(tmp)
            task = root / "task.yaml"
            task.write_text("parties:\n  critic:\n    enable: false\n    profile: p\n")
            result = subprocess.run(
                [str(TASK), "config", "resolve", "--name", "debate-parties",
                 "--project-root", str(root), "--user-config", str(root / "none.yaml"),
                 "--project-config", str(root / "none.yaml"),
                 "--task-config-file", str(task), "--json"],
                capture_output=True, text=True, check=True,
            )
            payload = json.loads(result.stdout)
        self.assertEqual(payload["debate_party_config"], {"parties": {"critic": {"enable": False}}})
        self.assertIn("debate_party_config", payload["next"])

    def test_resolved_party_config_with_models_validates_in_settlement(self):
        with tempfile.TemporaryDirectory(prefix="engine-debate-config-") as tmp:
            root = Path(tmp)
            task = root / "task.yaml"
            task.write_text(
                "defaults:\n  model: base-model\n"
                "parties:\n  critic:\n    model: party-model\n"
                "    profile: reviewer\n    label: Critic\n"
                "    mechanism: native_subagent\n    enabled: true\n"
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
            self.assertEqual(config, {"parties": {"critic": {
                "label": "Critic", "mechanism": "native_subagent", "enabled": True}}})
            settlement = (
                "task_type: ticket-to-pr\napproach: fixture\nprinciples: none\n"
                "goal:\n  succeeded: done\n  failed: never\n"
                "state_machine: |\n  name: smoke\n  nodes:\n    clarify:\n"
                "      next: [succeeded]\n    succeeded:\n      terminal: true\n"
                "    failed:\n      terminal: true\n"
                "request_assessment: fixture\nsource_of_truth:\n  scope: fixture\n"
                "debate_threshold: fixture\ndebate_round_cap: 1\n"
                "convergence_policy: unanimous\nconsented_stop_allowed: true\n"
                f"debate_party_config: {json.dumps(config)}\n"
                "spec_skill: spec\ntest_skill: test\nreview_skill: review\n"
                "review_fix_mode: accepted_only\n"
                "autonomy:\n  no_further_questions: true\n  permitted_mutations: [run tests]\n"
                "debate_roster: [main-agent, critic]\n"
                "debate_parties:\n  - id: critic\n    label: Critic\n"
                "    prompt: Find counterexamples.\n    mechanism: native_subagent\n"
                f"session_dir: {root.resolve()}\n"
            )
            path = root / "settlement.txt"
            path.write_text(settlement)
            result = subprocess.run(
                [str(TASK), "session", "validate", "cfg-run", "--dir", tmp,
                 "--settlement-file", str(path), "--prose"],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_config_cli_merges_reviewer_config_and_reports_models(self):
        with tempfile.TemporaryDirectory(prefix="engine-debate-config-") as tmp:
            root = Path(tmp)
            user = root / "user.yaml"
            project = root / "project.yaml"
            task = root / "task.yaml"
            user.write_text("defaults:\n  model: base-model\n")
            project.write_text(
                "defaults:\n  reasoning_effort: high\n"
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
                 "--project-root", str(root),
                 "--user-config", str(user),
                 "--project-config", str(project),
                 "--task-config-file", str(task), "--report", "models", "--json"],
                capture_output=True, text=True, check=True,
            )
            payload = json.loads(result.stdout)
            self.assertEqual(
                payload["effective"]["parties"]["independent-reviewer"]["profile"],
                "reviewer",
            )
            self.assertEqual(
                payload["effective"]["parties"]["independent-reviewer"]["label"],
                "Independent reviewer",
            )
            report = {entry["path"]: entry for entry in payload["model_report"]}
            self.assertEqual(report["parties.independent-reviewer"]["model"], "project-model")
            self.assertEqual(report["parties.independent-reviewer"]["profile"], "reviewer")
            self.assertEqual(report["defaults"]["model"], "base-model")

    def test_config_cli_merges_arbitrary_mapping_shapes(self):
        with tempfile.TemporaryDirectory(prefix="engine-config-") as tmp:
            root = Path(tmp)
            user = root / "user.yaml"
            project = root / "project.yaml"
            task = root / "task.yaml"
            user.write_text("scalar: user\nmapping:\n  keep: user\n  replace: user\nitems: [user]\n")
            project.write_text("mapping:\n  replace: project\nitems: [project]\n")
            task.write_text("scalar: task\nmapping:\n  add: task\n")
            result = subprocess.run(
                [str(TASK), "config", "resolve", "--name", "arbitrary",
                 "--project-root", str(root), "--user-config", str(user),
                 "--project-config", str(project), "--task-config-file", str(task),
                 "--json"], capture_output=True, text=True, check=True,
            )
            effective = json.loads(result.stdout)["effective"]
            self.assertEqual(effective["scalar"], "task")
            self.assertEqual(effective["mapping"], {
                "keep": "user", "replace": "project", "add": "task",
            })
            self.assertEqual(effective["items"], ["project"])

    def test_session_start_uses_hook_session_id(self):
        with tempfile.TemporaryDirectory(prefix="engine-session-id-") as tmp:
            root = Path(tmp)
            home = root / "home"
            cwd = root / "cwd"
            ledger_dir = home / ".bootgear" / "session"
            ledger_dir.mkdir(parents=True)
            cwd.mkdir()
            run_id = "codex-thread-123"
            (ledger_dir / f"{run_id}.md").write_text(
                "## settlement\n"
                "goal: succeeded when the test passes. failed when it cannot.\n"
            )
            result = subprocess.run(
                ["python3", str(PLUGIN_DIR / "hooks" / "session_start_recall.py")],
                input=json.dumps({
                    "session_id": run_id,
                    "cwd": str(cwd),
                    "source": "compact",
                }),
                capture_output=True,
                text=True,
                env={**os.environ, "HOME": str(home)},
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            output = json.loads(result.stdout)
            self.assertEqual(output["hookSpecificOutput"]["hookEventName"], "SessionStart")
            self.assertIn(f"Codex session_id: `{run_id}`", output["hookSpecificOutput"]["additionalContext"])
            self.assertIn("the test passes", output["hookSpecificOutput"]["additionalContext"])

    def test_spec_review_settlement_fields_are_optional_and_shaped(self):
        with tempfile.TemporaryDirectory(prefix="engine-spec-review-fields-") as tmp:
            root = Path(tmp)
            settlement = root / "settlement.txt"
            settlement.write_text(
                "task_type: ticket-to-pr\nrequest_assessment: fixture\n"
                "approach: fixture\nprinciples: none\nsource_of_truth:\n  scope: fixture\n"
                "debate_threshold: fixture\ndebate_round_cap: 1\n"
                "convergence_policy: unanimous\nconsented_stop_allowed: true\n"
                "debate_party_config: {}\ndebate_roster: [main-agent, independent-reviewer]\n"
                "spec_skill: spec\ntest_skill: test\nreview_skill: review\n"
                "spec_review_skill: spec-review\nspec_review_override: spec-review\n"
                "spec_debate_mode: threshold\nreview_fix_mode: accepted_only\n"
                "autonomy:\n  no_further_questions: true\n  permitted_mutations: [run tests]\n"
                "goal:\n  succeeded: done\n  failed: never\n"
                "state_machine: |\n  name: smoke\n  nodes:\n    clarify:\n      next: [succeeded]\n"
                "    succeeded:\n      terminal: true\n    failed:\n      terminal: true\n"
                f"session_dir: {root.resolve()}\n"
            )
            accepted = subprocess.run(
                [str(TASK), "session", "validate", "spec-review-fields", "--dir", tmp,
                 "--settlement-file", str(settlement), "--prose"],
                capture_output=True, text=True, check=False,
            )
        self.assertEqual(accepted.returncode, 0, accepted.stderr)

    def test_spec_review_angles_resolve_as_find_angles(self):
        angle_file = PLUGIN_DIR / "skills" / "spec-review" / "references" / "find-angles.yaml"
        result = subprocess.run(
            [str(CONVERGE), "angles", "--tag", "find", "--angles", str(angle_file), "--json"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(json.loads(result.stdout)["angles"]), 8)


if __name__ == "__main__":
    unittest.main()
