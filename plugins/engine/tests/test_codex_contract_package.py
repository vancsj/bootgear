import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml
from codex_contract_test_support import (
    CONVERGE,
    EXPECTED_SKILLS,
    HOOKS,
    MANIFEST,
    PLUGIN_DIR,
    TASK,
    TASK_DISPLAY,
    CodexPackageContractTestCase,
)
from gear_commands import GEAR


class CodexPackageContractTest(CodexPackageContractTestCase):
    def test_manifest_and_hooks_are_codex_package_shape(self):
        manifest = json.loads(MANIFEST.read_text())
        self.assertEqual(manifest["name"], "engine")
        self.assertTrue(manifest["description"].strip())
        self.assertEqual(manifest["hooks"], "./hooks/codex-hooks.json")

        hooks = json.loads(HOOKS.read_text())["hooks"]
        pre_tool_use = hooks["PreToolUse"][0]
        self.assertEqual(pre_tool_use["matcher"], "^request_user_input$")
        self.assertIn("--handler question_boundary", pre_tool_use["hooks"][0]["command"])
        session_start = hooks["SessionStart"][0]
        self.assertEqual(session_start["matcher"], "^(startup|resume|clear|compact|fork)$")
        self.assertIn('"${PLUGIN_ROOT}/hooks/gear" --host codex adapter',
                      session_start["hooks"][0]["command"])
        self.assertIn(
            "--matcher-pattern '^(startup|resume|clear|compact|fork)$'",
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

    def test_engine_ships_only_its_own_workflow_skills(self):
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
        self.assertIn("Claude Code or Codex", result.stderr)

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
            record = Path(tmp) / "xdg/bootgear/python"
            record.parent.mkdir(parents=True)
            record.write_text(f"{sys.executable}\n")
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
