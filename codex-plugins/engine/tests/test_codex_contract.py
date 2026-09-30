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
EXPECTED_SKILLS = {
    "clarify", "converge", "debate", "execute", "recall", "resolve", "review", "spec",
    "start", "test",
}


class CodexPackageContractTest(unittest.TestCase):
    def test_manifest_and_hooks_are_codex_package_shape(self):
        manifest = json.loads(MANIFEST.read_text())
        self.assertEqual(manifest["name"], "engine")
        self.assertEqual(manifest["version"], "0.14.0")
        self.assertIn("converge", manifest["description"])
        self.assertNotIn("hooks", manifest)

        hooks = json.loads(HOOKS.read_text())["hooks"]
        session_start = hooks["SessionStart"][0]
        self.assertEqual(session_start["matcher"], "^(startup|resume|compact)$")
        self.assertIn("${PLUGIN_ROOT}", session_start["hooks"][0]["command"])
        stop = hooks["Stop"][0]["hooks"][0]
        self.assertIn("${PLUGIN_ROOT}/hooks/stop_recall_reminder.py", stop["command"])
        post_tool_commands = [
            hook["command"]
            for group in hooks["PostToolUse"]
            for hook in group["hooks"]
        ]
        self.assertTrue(
            any("${PLUGIN_ROOT}/hooks/stop_recall_reminder.py" in command
                for command in post_tool_commands)
        )

    def test_engine_bundles_all_public_workflow_skills(self):
        skill_dirs = {
            path.parent.name for path in (PLUGIN_DIR / "skills").glob("*/SKILL.md")
        }
        self.assertEqual(skill_dirs, EXPECTED_SKILLS)
        for name in EXPECTED_SKILLS:
            self.assertTrue((PLUGIN_DIR / "skills" / name / "SKILL.md").is_file())

        for name in ("spec", "test", "review"):
            text = (PLUGIN_DIR / "skills" / name / "SKILL.md").read_text()
            self.assertIn("<plugin-root>/scripts/task", text)
            self.assertNotIn("engine-plugin-dir", text)
            self.assertNotIn("../../engine/", text)

    def test_skills_do_not_carry_claude_or_legacy_invocation_contracts(self):
        for path in (PLUGIN_DIR / "skills").glob("*/SKILL.md"):
            text = path.read_text()
            self.assertNotIn("CLAUDE", text.upper(), path)
            self.assertNotIn("Skill tool", text, path)
            self.assertNotIn("disable-model-invocation", text, path)
            self.assertNotIn("opus", text.lower(), path)

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

    def test_converge_runs_bundled_script_with_native_subagents(self):
        text = (PLUGIN_DIR / "skills" / "converge" / "SKILL.md").read_text()
        mechanics = text[text.index("## Host mechanics"):]
        self.assertIn("separate fresh native subagent with `spawn_agent`", mechanics)
        self.assertIn("continue that same subagent", mechanics)
        self.assertIn("`<plugin-root>/scripts/converge`", mechanics)
        self.assertIn("fresh approval request", mechanics)
        self.assertIn("outcome `blocked`", mechanics)
        self.assertNotIn("Agent tool", text)
        self.assertNotIn("SendMessage", text)
        self.assertNotIn("bin/", mechanics)

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

    def test_review_runs_converge_through_codex_paths(self):
        text = (PLUGIN_DIR / "skills" / "review" / "SKILL.md").read_text()
        self.assertIn("Read `reference.md` § `Findings go through converge`", text)
        self.assertIn("Run every `converge` action below", text)
        self.assertIn("`converge` skill", text)
        self.assertNotIn("converge:converge", text)
        self.assertIn("`cutoff: {report_rules: [<every rule ID whose severity is at or above", text)
        self.assertIn("--config <converge-dir>/<slate>.yaml", text)
        self.assertIn("Spawn one finder, F", text)
        self.assertNotIn("docs/engine.md", text)
        self.assertIn("<plugin-root>/scripts/task", text[text.index("## Host mechanics"):])
        self.assertIn("<plugin-root>/scripts/converge", text[text.index("## Host mechanics"):])
        for name in ("find-angles.yaml", "design-patterns.yaml", "lenses.md"):
            self.assertTrue((PLUGIN_DIR / "skills" / "review" / "references" / name).is_file())

    def test_debate_maps_builtin_parties_to_native_subagents(self):
        text = (PLUGIN_DIR / "skills" / "debate" / "SKILL.md").read_text()
        self.assertIn("host-supported mechanism", text)
        self.assertIn("stable ID", text)
        self.assertIn("debate_party_config.parties.<id>", text)
        self.assertIn("Record `UNAVAILABLE`", text)
        self.assertIn("<plugin-root>/scripts/task", text[text.index("## Host mechanics"):])

    def test_codex_accepts_only_native_subagent_mechanism(self):
        base = (
            "task_type: ticket-to-pr\napproach: fixture\nprinciples: none\n"
            "goal:\n  succeeded: done\n  failed: never\n"
            "state_machine: |\n  name: smoke\n  nodes:\n    clarify:\n"
            "      next: [succeeded]\n    succeeded:\n      terminal: true\n"
            "    failed:\n      terminal: true\n"
            "request_assessment: fixture\nsource_of_truth:\n  scope: fixture\n"
            "debate_threshold: fixture\ndebate_round_cap: 1\n"
            "convergence_policy: unanimous\nconsented_stop_allowed: true\n"
            "debate_party_config: {}\n"
            "spec_skill: spec\ntest_skill: test\nreview_skill: review\n"
            "review_fix_mode: accepted_only\n"
            "autonomy:\n  no_further_questions: true\n  permitted_mutations: [run tests]\n"
            "debate_roster: [main-agent, critic]\n"
            "debate_parties:\n  - id: critic\n    label: Critic\n"
            "    prompt: Find counterexamples.\n"
        )
        cases = (("native_subagent", "", 0), ("advisor", "", 1),
                 ("native_subagent", "advisor", 1))
        for mechanism, config_mechanism, code in cases:
            config = ("debate_party_config: {}\n" if not config_mechanism else
                      "debate_party_config:\n  parties:\n    critic:\n"
                      f"      mechanism: {config_mechanism}\n")
            with tempfile.TemporaryDirectory(prefix="engine-debate-mechanism-") as tmp:
                path = Path(tmp) / "settlement.txt"
                settlement = base.replace("debate_party_config: {}\n", config)
                path.write_text(f"{settlement}    mechanism: {mechanism}\n"
                                f"session_dir: {Path(tmp).resolve()}\n")
                result = subprocess.run(
                    [str(TASK), "session", "validate", "mech-run", "--dir", tmp,
                     "--settlement-file", str(path), "--prose"],
                    capture_output=True, text=True, check=False,
                )
            self.assertEqual(result.returncode, code, result.stderr)
            if code:
                self.assertIn("mechanism", result.stderr)
                self.assertIn("native_subagent", result.stderr)

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
        reference = (PLUGIN_DIR / "skills" / "debate" / "reference.md").read_text()
        self.assertIn("## Facts versus choices", reference)

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

    def test_debate_dispatch_is_layered_configuration(self):
        clarify = (PLUGIN_DIR / "skills" / "clarify" / "SKILL.md").read_text()
        self.assertIn("config resolve --name debate-parties", clarify)
        self.assertIn("debate_party_config", clarify)

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

    def test_clarify_lists_leave_check_commands_for_approval(self):
        clarify = (PLUGIN_DIR / "skills" / "clarify" / "SKILL.md").read_text()
        for text in ("reminder.leave_check", "tier it came from", "command -v <argv[0]>",
                     "the user's confirmation approves them"):
            self.assertIn(text, clarify)
        # Codex resolves argv[0] from <plugin-root>/scripts/ before PATH, and
        # scripts/ is not on PATH, so command -v alone shows the wrong program.
        self.assertIn("`<plugin-root>/scripts/<argv[0]>` when that file exists and is executable, "
                      "else `command -v <argv[0]>`", clarify)


    def test_review_hands_fixing_to_a_fix_node(self):
        text = (PLUGIN_DIR / "skills" / "review" / "SKILL.md").read_text()
        self.assertIn("public engine state\ninterface", text)
        self.assertIn("In an active run, apply no claim in any mode; fixing happens only "
                      "in the `fix` node.", text)
        self.assertIn("When `machine.nodes[current].next` includes `fix` and the mode would "
                      "apply at least one claim, end the iteration after sub-task 5 with "
                      "outcome `handoff`", text)
        self.assertIn("the ids of those claims; `execute` applies them in the `fix` node.", text)
        self.assertIn("includes `fix` and the fix list is empty, end with the outcome the "
                      "render gives below: `clean`, `below_cutoff`, or `blocked`.", text)
        self.assertIn("- **`handoff`:** In an active run, the current node has a `fix` edge "
                      "and the\n  mode would apply at least one claim", text)
        self.assertIn("Otherwise, end the iteration after sub-task 5 with outcome "
                      "`comment_only`: report every surviving claim and apply none, "
                      "whatever `review_fix_mode` says.", text)
        self.assertIn("- **`comment_only`:** In an active run, the current node has no "
                      "`fix` edge.", text)
        self.assertIn("For `comment_only`, report every\nsurviving claim as a comment", text)
        self.assertNotIn("current node has no `fix` edge — or any", text)
        self.assertIn("- **`clean`:** A re-review's render, or an active run's single-pass "
                      "render,\n  has no `reported` claim", text)
        self.assertIn("For `handoff`, return the fix list (claim ids)", text)

    def test_review_rereview_passes_snapshot_since_and_delta(self):
        text = (PLUGIN_DIR / "skills" / "review" / "SKILL.md").read_text()
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
        self.assertIn("Record the slate, converge directory, snapshot, and render counts",
                      flat)

    def test_domain_skills_are_invoked_by_their_bundled_names(self):
        skills = PLUGIN_DIR / "skills"
        texts = {name: (skills / name).read_text() for name in (
            "execute/SKILL.md", "execute/reference.md", "recall/reference.md")}
        self.assertIn("`engine:spec`, `engine:test` and `engine:review`", texts["execute/SKILL.md"])
        self.assertIn("`engine:spec`, `engine:test`, and `engine:review`",
                      texts["recall/reference.md"])
        self.assertIn("`engine:spec`, `engine:test` and `engine:review`",
                      " ".join(texts["execute/reference.md"].split()))
        self.assertNotIn("bare name", texts["execute/SKILL.md"])
        self.assertNotIn("by its public name", texts["execute/reference.md"])
        for name, text in texts.items():
            for wrong in ("spec:spec", "test:test", "review:review"):
                self.assertNotIn(wrong, text, name)

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

    def test_state_machine_amendment_goes_through_state_amend(self):
        skills = PLUGIN_DIR / "skills"
        execute = (skills / "execute" / "SKILL.md").read_text()
        recall = (skills / "recall" / "SKILL.md").read_text()
        clarify = (skills / "clarify" / "SKILL.md").read_text()
        self.assertIn("task state amend <run-id> --dir <session-dir> --machine-file", execute)
        self.assertIn("<plugin-root>/scripts/task", execute[execute.index("## Host mechanics"):])
        self.assertIn("never `record-decision`", execute)
        self.assertIn("Then transition to the current node's `fix` branch and apply the "
                      "remaining claim ids there; with none remaining, take the branch that "
                      "matches the review without them.", " ".join(execute.split()))
        self.assertIn("On `comment_only`, report the claims and take the branch that matches "
                      "the reported outcome.", " ".join(execute.split()))
        self.assertIn("task state current <run-id> --dir <session-dir>", recall)
        self.assertIn("<plugin-root>/scripts/task", recall[recall.index("## Host mechanics"):])
        self.assertIn("Skip `AMENDMENT state_machine` in this scan", recall)
        self.assertIn("For `pr-review` of a PR the user did not author, remove the `fix` node",
                      clarify)


if __name__ == "__main__":
    unittest.main()
