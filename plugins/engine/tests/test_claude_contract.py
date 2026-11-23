import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from bootgear_cli import runtime
from claude_contract_test_support import (
    ADVISOR_PARTY,
    ALL_NATIVE,
    ROSTER,
    ClaudePackageContractTestCase,
    _roles,
)
from gear_commands import TASK
from gear_commands import command as gear_command


class ClaudePackageContractTest(ClaudePackageContractTestCase):
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
            data = root / "data"
            runtimes = data / "bootgear" / "runtimes"
            runtimes.parent.mkdir(parents=True)
            (runtimes.parent / "python").write_text(f"{sys.executable}\n")
            runtimes.symlink_to(runtime.environment_path().parent, target_is_directory=True)
            for host in ("claude", "codex"):
                for override in (False, True):
                    with self.subTest(host=host, override=override):
                        args = [*gear_command("engine", "task", host), "config", "resolve", "--name", "profile",
                                "--project-root", str(root), "--json"]
                        if override:
                            args.extend(("--user-config", str(explicit)))
                        result = subprocess.run(
                            args, env={**os.environ, "HOME": str(root), "XDG_DATA_HOME": str(data),
                                       "BOOTGEAR_HOST": host},
                            capture_output=True, text=True, check=True,
                        )
                        self.assertEqual(json.loads(result.stdout)["effective"]["source"],
                                         "explicit" if override else host)

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
                [*TASK, "config", "resolve", "--name", "debate-parties",
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
                [*TASK, "config", "resolve", "--name", "debate-parties",
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

    def test_resolved_party_config_keeps_misspelt_fields_for_validation(self):
        payload = self._resolve_parties(
            "parties:\n  adversarial-reviewer:\n    enable: false\n    model: m\n")
        config = payload["debate_party_config"]
        self.assertEqual(config, {"parties": {"adversarial-reviewer": {"enable": False}}})
        result = self._validate(f"debate_party_config: {json.dumps(config)}\n" + self._party("advisor"))
        self.assertEqual(result.returncode, 1)
        self.assertIn("contains unsupported fields", result.stderr)

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

if __name__ == "__main__":
    unittest.main()
