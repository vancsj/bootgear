import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml
from gear_commands import CONVERGE, GEAR, TASK, display
from gear_commands import command as gear_command

PLUGIN_DIR = Path(__file__).resolve().parents[1]
MANIFEST = PLUGIN_DIR / ".codex-plugin" / "plugin.json"
HOOKS = PLUGIN_DIR / "hooks" / "hooks.json"
TASK_DISPLAY = display("engine", "task")
ROSTER = "[main-agent, independent-reviewer, adversarial-reviewer, critic]"
ADVISOR_PARTY = ("debate_party_config:\n  parties:\n    adversarial-reviewer:\n"
                 "      mechanism: advisor\n")
ALL_NATIVE = ("converge_seats: {main: native_subagent, finder: native_subagent, "
              "r1: native_subagent, r2: native_subagent, cutter: native_subagent}\n")
EXPECTED_SKILLS = {
    "clarify", "converge", "debate", "execute", "recall", "resolve", "review", "spec",
    "start", "spec-review", "self-review", "test",
}


def _roles(*roles: str) -> str:
    return f"advisor_roles:\n  roles: [{', '.join(roles)}]\n  brief: Act only in these roles.\n  startup: early\n"


class CodexPackageContractTest(unittest.TestCase):
    def test_advisor_startup_choice_validates_and_round_trips(self):
        for startup in ("early", "deferred"):
            with self.subTest(startup=startup), tempfile.TemporaryDirectory() as tmp:
                settings = _roles("refuter").replace("  startup: early\n", "") + f"  startup: {startup}\n"
                if startup == "deferred":
                    settings += "  launcher: start-advisor\n"
                settings += "converge_seats: {r2: advisor}\ndebate_party_config: {}\n"
                self.assertEqual(self._validate(settings).returncode, 0)
                root = Path(tmp)
                path = root / "settlement.yaml"
                path.write_text(self._settlement(settings, task_folder=root / "task"))
                init = subprocess.run([*TASK, "session", "init", "startup-run", "--dir", tmp,
                                       "--settlement-file", str(path)],
                                      capture_output=True, text=True, check=False)
                self.assertEqual(init.returncode, 0, init.stderr)
                read = subprocess.run([*TASK, "session", "read", "startup-run", "--dir", tmp,
                                       "--section", "settlement", "--json"],
                                      capture_output=True, text=True, check=True)
                self.assertIn(f"startup: {startup}", read.stdout)
                if startup == "deferred":
                    self.assertIn("launcher: start-advisor", read.stdout)

    def test_advisor_startup_requires_a_choice_and_a_deferred_launcher(self):
        for options, field in (("", "startup"), ("  startup: later\n", "startup"),
                               ("  startup: deferred\n", "launcher")):
            with self.subTest(options=options):
                settings = (_roles("refuter").replace("  startup: early\n", "") + options
                            + "converge_seats: {r2: advisor}\ndebate_party_config: {}\n")
                result = self._validate(settings)
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn(f"advisor_roles.{field}", result.stderr)

    def test_shared_host_selects_user_config_and_explicit_path_wins(self):
        with tempfile.TemporaryDirectory(prefix="engine-host-config-") as tmp:
            root = Path(tmp)
            for host in ("claude", "codex"):
                folder = root / f".{host}"
                folder.mkdir()
                (folder / "profile.yaml").write_text(f"source: {host}\n")
            explicit = root / "explicit.yaml"
            explicit.write_text("source: explicit\n")
            for host in ("claude", "codex"):
                for override in (False, True):
                    with self.subTest(host=host, override=override):
                        args = [*gear_command("engine", "task", host), "config", "resolve", "--name", "profile",
                                "--project-root", str(root), "--json"]
                        if override:
                            args.extend(("--user-config", str(explicit)))
                        result = subprocess.run(
                            args, env={**os.environ, "HOME": str(root), "BOOTGEAR_HOST": host},
                            capture_output=True, text=True, check=True,
                        )
                        self.assertEqual(json.loads(result.stdout)["effective"]["source"],
                                         "explicit" if override else host)

    def test_manifest_and_hooks_are_codex_package_shape(self):
        manifest = json.loads(MANIFEST.read_text())
        self.assertEqual(manifest["name"], "engine")
        self.assertIn("converge", manifest["description"])
        self.assertNotIn("hooks", manifest)

        hooks = json.loads(HOOKS.read_text())["hooks"]
        self.assertNotIn("PreToolUse", hooks)
        session_start = hooks["SessionStart"][0]
        self.assertEqual(session_start["matcher"], "^(startup|resume|compact)$")
        self.assertIn('"${PLUGIN_ROOT}/hooks/gear" --host codex adapter',
                      session_start["hooks"][0]["command"])
        self.assertIn(
            "--matcher-pattern '^(startup|resume|compact)$'",
            session_start["hooks"][0]["command"],
        )
        self.assertIn("${PLUGIN_ROOT}", session_start["hooks"][0]["command"])
        self.assertIn("--handler session_recall", session_start["hooks"][0]["command"])
        stop = hooks["Stop"][0]["hooks"][0]
        self.assertIn('"${PLUGIN_ROOT}/hooks/gear" --host codex adapter', stop["command"])
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

    def test_cli_setup_reports_missing_uv(self):
        with tempfile.TemporaryDirectory(prefix="engine-runtime-home-") as tmp:
            python_bin = str(Path(sys.executable).parent)
            env = {
                "PATH": os.pathsep.join((python_bin, "/usr/bin:/bin")),
                "HOME": str(Path(tmp) / "home"),
                "CODEX_HOME": str(Path(tmp) / "codex"),
                "CLAUDE_CONFIG_DIR": str(Path(tmp) / "claude"),
                "XDG_DATA_HOME": str(Path(tmp) / "xdg"),
                "THROTTLE_OFF": "1",
            }
            result = subprocess.run(
                [str(GEAR), "--host", "codex", "cli", "setup"],
                capture_output=True,
                text=True,
                env=env,
                check=False,
            )

        self.assertEqual(result.returncode, 2)
        self.assertIn("uv is missing", result.stderr)
        self.assertIn("run cli:setup", result.stderr)

    def test_converge_command_runs_through_gear(self):
        result = subprocess.run(
            [*CONVERGE, "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("usage:", result.stdout)

    def test_converge_without_runtime_reports_setup_guidance(self):
        with tempfile.TemporaryDirectory(prefix="converge-runtime-") as tmp:
            result = subprocess.run(
                [*CONVERGE, "--help"],
                capture_output=True,
                text=True,
                env={**os.environ, "XDG_DATA_HOME": str(Path(tmp) / "xdg")},
                check=False,
            )
        self.assertEqual(result.returncode, 2)
        self.assertIn("Shared runtime is missing", result.stderr)
        self.assertIn("Run cli:setup", result.stderr)

    def test_gear_defaults_to_prose_and_names_the_public_command(self):
        self.assertTrue(os.access(GEAR, os.X_OK))
        self.assertIn("/plugins/cli/bin/gear", str(GEAR))

        machine = PLUGIN_DIR / "state-machines" / "ticket-writing.yaml"
        nodes = yaml.safe_load(machine.read_text())["nodes"]
        self.assertNotIn("spec", nodes)
        for name, node in nodes.items():
            self.assertNotIn("spec", node.get("next", []), name)
            do = ((node.get("reminder") or {}).get("do") or "").split("Does not:")[0]
            self.assertIsNone(re.search(r"(?<![\w-])spec(?![\w-])", do), f"{name}: {do}")
        env = {k: v for k, v in os.environ.items()
               if k not in ("BOOTGEAR_OUTPUT", "BOOTGEAR_PROG", "VIRTUAL_ENV")}

        def validate(*extra, **more):
            return subprocess.run([*TASK, "state", "validate", str(machine), *extra],
                                  capture_output=True, text=True, check=False,
                                  env={**env, **more})

        prose = validate()
        self.assertEqual(prose.returncode, 0, prose.stderr)
        self.assertEqual(prose.stdout, f"{machine}: ok\n")
        for result in (validate("--json"), validate(BOOTGEAR_OUTPUT="json")):
            self.assertEqual(json.loads(result.stdout),
                             {"path": str(machine), "ok": True, "problems": []})

        refused = subprocess.run([*TASK, "state", "validate"], capture_output=True,
                                 text=True, check=False, env=env)
        self.assertEqual(refused.returncode, 2)
        self.assertTrue(
            refused.stderr.startswith(f"example: {TASK_DISPLAY} state validate <machine.yaml>\n"),
            refused.stderr)
        self.assertIn("error:", refused.stderr.splitlines()[-1])
        self.assertIn(
            f"\n  {TASK_DISPLAY} session recall --dir <session-dir>\n",
            refused.stderr,
        )

    def _settlement(self, extra: str, roster: str = ROSTER, *, task_folder: Path) -> str:
        return (
            "task_type: ticket-to-pr\napproach: fixture\nprinciples: none\n"
            f"task_folder: {task_folder.resolve()}\n"
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
            settlement = self._settlement(extra, roster, task_folder=Path(tmp) / "task")
            path.write_text(f"{settlement}session_dir: {Path(tmp).resolve()}\n")
            return subprocess.run(
                [*TASK, "session", "validate", "mech-run", "--dir", tmp,
                 "--settlement-file", str(path), "--prose"],
                capture_output=True, text=True, check=False,
            )

    def _machine_validate(self, nodes: str, skills: str):
        settlement = (
            "task_type: change-review\napproach: fixture\nprinciples: none\n"
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
            path.write_text(f"{settlement}session_dir: {Path(tmp).resolve()}\n"
                            f"task_folder: {(Path(tmp) / 'task').resolve()}\n")
            return subprocess.run(
                [*TASK, "session", "validate", "skill-run", "--dir", tmp,
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

    def test_codex_refused_mechanism_names_the_party_and_the_bad_value(self):
        party = ("debate_parties:\n  - id: critic\n    label: Critic\n"
                 "    prompt: Find counterexamples.\n    mechanism: bogus\n")
        result = self._validate("debate_party_config: {}\n" + party)
        self.assertEqual(result.returncode, 1)
        self.assertIn("critic", result.stderr)
        self.assertIn("bogus", result.stderr)

    def test_codex_refused_mechanism_in_party_config_names_the_bad_value(self):
        config = "debate_party_config:\n  parties:\n    critic:\n      mechanism: bogus\n"
        result = self._validate(config)
        self.assertEqual(result.returncode, 1)
        self.assertIn("bogus", result.stderr)

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
                "debate_party_config: {}\n", task_folder=Path(tmp) / "task"))
            result = subprocess.run(
                [*TASK, "session", "init", "seat-run", "--dir", tmp,
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
            args = [*TASK, "config", "resolve", "--name", "converge-seats",
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
                [*TASK, "config", "resolve", "--name", "debate-parties",
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
                [*TASK, "config", "resolve", "--name", "debate-parties",
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
                f"task_folder: {(root / 'task').resolve()}\n"
            )
            path = root / "settlement.txt"
            path.write_text(settlement)
            result = subprocess.run(
                [*TASK, "session", "validate", "cfg-run", "--dir", tmp,
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
                [*TASK, "config", "resolve", "--name", "debate-parties",
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
                [*TASK, "config", "resolve", "--name", "arbitrary",
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
                "debate_mode: threshold\nreview_fix_mode: accepted_only\n"
                "autonomy:\n  no_further_questions: true\n  permitted_mutations: [run tests]\n"
                "goal:\n  succeeded: done\n  failed: never\n"
                "state_machine: |\n  name: smoke\n  nodes:\n    clarify:\n      next: [succeeded]\n"
                "    succeeded:\n      terminal: true\n    failed:\n      terminal: true\n"
                f"session_dir: {root.resolve()}\n"
                f"task_folder: {(root / 'task').resolve()}\n"
            )
            accepted = subprocess.run(
                [*TASK, "session", "validate", "spec-review-fields", "--dir", tmp,
                 "--settlement-file", str(settlement), "--prose"],
                capture_output=True, text=True, check=False,
            )
        self.assertEqual(accepted.returncode, 0, accepted.stderr)

    def test_spec_review_angles_resolve_as_find_angles(self):
        angle_file = PLUGIN_DIR / "skills" / "spec-review" / "references" / "angles.yaml"
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


if __name__ == "__main__":
    unittest.main()
