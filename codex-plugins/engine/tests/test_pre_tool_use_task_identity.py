"""Tests for the Codex hook that adds the active session to Gear calls."""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
HOOK = PLUGIN_DIR / "hooks" / "pre_tool_use_task_identity.py"
HOOKS = PLUGIN_DIR / "hooks" / "hooks.json"
HOST = "codex"
TASK = PLUGIN_DIR / "scripts" / "task"


class PreToolUseTaskIdentityTest(unittest.TestCase):
    def _run(self, command: str, *, session_id: object = "thr_123", extra=None,
             env_extra=None):
        hook_input = {
            "session_id": session_id,
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": command},
        }
        if extra:
            hook_input.update(extra)
        env = dict(os.environ)
        env["PLUGIN_ROOT"] = str(PLUGIN_DIR)
        if env_extra:
            env.update(env_extra)
        result = subprocess.run(
            ["python3", str(HOOK), "--host", HOST],
            input=json.dumps(hook_input),
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout) if result.stdout.strip() else {}

    def _task(self, *args: str) -> str:
        return " ".join((shlex.quote(str(TASK)), *args))

    def test_pre_tool_use_hook_is_registered_for_bash(self):
        hooks = json.loads(HOOKS.read_text())["hooks"]
        groups = hooks["PreToolUse"]
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]["matcher"], "^Bash$")
        self.assertIn("pre_tool_use_task_identity.py", groups[0]["hooks"][0]["command"])
        self.assertIn("${PLUGIN_ROOT}", groups[0]["hooks"][0]["command"])

    def test_registered_task_command_is_allowed_with_hook_session_identity(self):
        original = self._task(
            "session", "record-pitch", "run-id", "--dir", "'/tmp/session dir'",
            "'a quoted pitch with spaces'",
        )
        output = self._run(original, env_extra={"BOOTGEAR_SESSION_ID": "inherited-id"})

        specific = output["hookSpecificOutput"]
        self.assertEqual(specific["hookEventName"], "PreToolUse")
        self.assertEqual(specific["permissionDecision"], "allow")
        rewritten = specific["updatedInput"]["command"]
        self.assertEqual(
            rewritten,
            f"export BOOTGEAR_HOST='{HOST}' BOOTGEAR_SESSION_ID='thr_123' && {original}",
        )
        self.assertIn("'/tmp/session dir'", rewritten)
        self.assertIn("'a quoted pitch with spaces'", rewritten)
        self.assertNotIn("CLAUDE_CODE_SESSION_ID", rewritten)

    def test_unrelated_argument_containing_registered_command_is_untouched(self):
        embedded = self._task("session", "recall", "some-run")
        output = self._run(f"printf '%s' {shlex.quote(embedded)}")
        self.assertEqual(output, {})

    def test_compound_calls_and_shell_operators_are_not_approved(self):
        task = self._task("session", "recall", "some-run")
        cases = (
            f"{task}; echo done",
            f"echo before && {task}",
            f"{task} || echo failed",
            f"{task} | cat",
            f"{task} &",
            f"{task} > /tmp/output",
            f"{task} 2>/tmp/error",
            f"{task} < /tmp/input",
            f"{task}\necho done",
            f"{task} $(echo another-command)",
            f"{task} `echo another-command`",
        )
        for command in cases:
            with self.subTest(command=command):
                self.assertEqual(self._run(command), {})

    def test_unknown_commands_and_unbundled_router_are_not_approved(self):
        self.assertEqual(self._run("gear.py absent task session recall run"), {})
        self.assertEqual(self._run(self._task("session", "unregistered", "run")), {})
        self.assertFalse((PLUGIN_DIR / "cli" / "gear.py").exists())
        router = Path(__file__).resolve().parents[3] / "cli" / "gear.py"
        self.assertEqual(
            self._run(f"{shlex.quote(str(router))} engine task session recall run"), {}
        )

    def test_registered_standalone_executable_is_allowed(self):
        with tempfile.TemporaryDirectory(prefix="gear-hook-registration-") as tmp:
            plugin = Path(tmp) / "sample-plugin"
            executable = plugin / "bin" / "report"
            executable.parent.mkdir(parents=True)
            executable.write_text("#!/bin/sh\nexit 0\n")
            executable.chmod(0o755)
            (plugin / "gear.toml").write_text(
                '[plugin]\nname = "sample-plugin"\n\n'
                '[commands.report]\nexec = ["./bin/report"]\n'
            )
            original = f"{shlex.quote(str(executable))} show report"
            output = self._run(original)
            self.assertEqual(
                output["hookSpecificOutput"]["updatedInput"]["command"],
                f"export BOOTGEAR_HOST='{HOST}' BOOTGEAR_SESSION_ID='thr_123' && {original}",
            )

    def test_bundled_task_executable_is_recognized_through_path(self):
        original = "task session read run-id"
        path = os.pathsep.join((str(PLUGIN_DIR / "scripts"), os.environ.get("PATH", "")))
        output = self._run(original, env_extra={"PATH": path})
        self.assertEqual(
            output["hookSpecificOutput"]["updatedInput"]["command"],
            f"export BOOTGEAR_HOST='{HOST}' BOOTGEAR_SESSION_ID='thr_123' && {original}",
        )

    def test_registered_executable_is_recognized_through_path(self):
        with tempfile.TemporaryDirectory(prefix="gear-hook-path-") as tmp:
            plugin = Path(tmp) / "sample-plugin"
            executable = plugin / "bin" / "report"
            executable.parent.mkdir(parents=True)
            executable.write_text("#!/bin/sh\nexit 0\n")
            executable.chmod(0o755)
            (plugin / "gear.toml").write_text(
                '[plugin]\nname = "sample-plugin"\n\n'
                '[commands.report]\nexec = ["./bin/report"]\n'
            )
            original = "report show report"
            path = os.pathsep.join((str(executable.parent), os.environ.get("PATH", "")))
            output = self._run(original, env_extra={"PATH": path})
            self.assertEqual(
                output["hookSpecificOutput"]["updatedInput"]["command"],
                f"export BOOTGEAR_HOST='{HOST}' BOOTGEAR_SESSION_ID='thr_123' && {original}",
            )

    def test_same_directory_path_alias_to_registered_executable_is_allowed(self):
        with tempfile.TemporaryDirectory(prefix="gear-hook-path-alias-") as tmp:
            plugin = Path(tmp) / "sample-plugin"
            executable = plugin / "bin" / "report"
            alias = plugin / "bin" / "report-alias"
            executable.parent.mkdir(parents=True)
            executable.write_text("#!/bin/sh\nexit 0\n")
            executable.chmod(0o755)
            alias.symlink_to(executable)
            (plugin / "gear.toml").write_text(
                '[plugin]\nname = "sample-plugin"\n\n'
                '[commands.report]\nexec = ["./bin/report"]\n'
            )
            original = "report-alias show report"
            path = os.pathsep.join((str(alias.parent), os.environ.get("PATH", "")))
            output = self._run(original, env_extra={"PATH": path})
            self.assertEqual(
                output["hookSpecificOutput"]["updatedInput"]["command"],
                f"export BOOTGEAR_HOST='{HOST}' BOOTGEAR_SESSION_ID='thr_123' && {original}",
            )

    def test_path_alias_outside_wrapper_directory_is_not_allowed(self):
        with tempfile.TemporaryDirectory(prefix="gear-hook-path-alias-") as tmp:
            root = Path(tmp)
            plugin = root / "sample-plugin"
            executable = plugin / "bin" / "report"
            alias = root / "aliases" / "report"
            executable.parent.mkdir(parents=True)
            alias.parent.mkdir(parents=True)
            executable.write_text("#!/bin/sh\nexit 0\n")
            executable.chmod(0o755)
            alias.symlink_to(executable)
            (plugin / "gear.toml").write_text(
                '[plugin]\nname = "sample-plugin"\n\n'
                '[commands.report]\nexec = ["./bin/report"]\n'
            )
            path = os.pathsep.join((str(alias.parent), os.environ.get("PATH", "")))
            self.assertEqual(self._run("report show report", env_extra={"PATH": path}), {})

    def test_unregistered_sibling_executable_is_not_allowed(self):
        with tempfile.TemporaryDirectory(prefix="gear-hook-registration-") as tmp:
            plugin = Path(tmp) / "sample-plugin"
            executable = plugin / "bin" / "unregistered"
            executable.parent.mkdir(parents=True)
            executable.write_text("#!/bin/sh\nexit 0\n")
            executable.chmod(0o755)
            (plugin / "gear.toml").write_text(
                '[plugin]\nname = "sample-plugin"\n\n'
                '[commands.report]\nexec = ["./bin/report"]\n'
            )
            self.assertEqual(self._run(f"{executable} show report"), {})

    def test_unreadable_command_registration_is_not_approved(self):
        with tempfile.TemporaryDirectory(prefix="gear-hook-registration-") as tmp:
            plugin = Path(tmp) / "sample-plugin"
            executable = plugin / "bin" / "report"
            executable.parent.mkdir(parents=True)
            executable.write_text("#!/bin/sh\nexit 0\n")
            executable.chmod(0o755)
            (plugin / "gear.toml").write_text("[commands.report\n")
            self.assertEqual(self._run(f"{executable} show report"), {})

    def test_missing_or_malformed_hook_session_id_is_not_approved(self):
        command = self._task("session", "recall", "some-run")
        for session_id in (None, "", 42, "bad id", "bad\nvalue", "bad' && echo unsafe"):
            with self.subTest(session_id=session_id):
                self.assertEqual(self._run(command, session_id=session_id), {})

    def test_non_bash_or_non_pre_tool_use_input_is_not_approved(self):
        command = self._task("session", "recall", "some-run")
        self.assertEqual(self._run(command, extra={"tool_name": "apply_patch"}), {})
        self.assertEqual(
            self._run(command, extra={"hook_event_name": "PostToolUse"}), {}
        )


if __name__ == "__main__":
    unittest.main()
