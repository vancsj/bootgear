from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from bootgear_cli import clikit

PLUGIN = Path(__file__).resolve().parents[1]
CHANNEL = PLUGIN / "skills" / "advisor" / "scripts" / "channel.py"


class SessionIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="advisor-session-id-")
        self.root = Path(self.temp.name) / "advisor"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def run_channel(self, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
        process_env = {key: value for key, value in os.environ.items()
                       if key not in {"BOOTGEAR_SESSION_ID", "CLAUDE_CODE_SESSION_ID", "CODEX_SESSION_ID"}}
        process_env.update(env or {})
        return subprocess.run(
            [sys.executable, str(CHANNEL), "--root", str(self.root), *args, "--json"],
            capture_output=True, text=True, check=False, env=process_env,
        )

    def owner(self) -> str:
        record = json.loads((self.root / "channels" / "0001" / "channel.json").read_text())
        return record["listener_owner"]

    def test_explicit_session_wins_over_environment(self) -> None:
        result = self.run_channel(
            "register", "--role", "listener", "--session", "explicit-session",
            env={"BOOTGEAR_SESSION_ID": "shared-session", "CLAUDE_CODE_SESSION_ID": "claude-session"},
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.owner(), "explicit-session")

    def test_bootgear_session_is_the_default(self) -> None:
        result = self.run_channel(
            "register", "--role", "listener",
            env={"BOOTGEAR_SESSION_ID": "shared-session", "CLAUDE_CODE_SESSION_ID": "claude-session"},
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.owner(), "shared-session")

    def test_claude_session_is_the_fallback(self) -> None:
        result = self.run_channel(
            "register", "--role", "listener", env={"CLAUDE_CODE_SESSION_ID": "claude-session"},
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.owner(), "claude-session")

    def test_live_list_uses_the_default_session_in_its_follow_up(self) -> None:
        result = self.run_channel(
            "list", "--live-for", "asker", env={"BOOTGEAR_SESSION_ID": "shared-session"},
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        follow_up = json.loads(result.stdout)["next"]
        self.assertIn("list --live-for asker --wait 120", follow_up)
        self.assertNotIn("--session", follow_up)

    def test_explicit_session_that_differs_stays_in_next(self) -> None:
        env = {"CODEX_SESSION_ID": "codex-session"}
        listed = self.run_channel("list", "--live-for", "asker", "--session", "other-session", env=env)
        registered = self.run_channel("register", "--role", "listener", "--session", "other-session", env=env)

        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertIn("list --live-for asker --session other-session --wait 120",
                      json.loads(listed.stdout)["next"])
        self.assertEqual(registered.returncode, 0, registered.stderr)
        self.assertTrue(json.loads(registered.stdout)["next"].endswith(
            "heartbeat --channel 0001 --role listener --session other-session"))

    def test_register_next_heartbeat_omits_the_environment_session(self) -> None:
        env = {"CODEX_SESSION_ID": "codex-session"}
        for label, extra in (("environment", ()), ("same explicit", ("--session", "codex-session"))):
            with self.subTest(session=label):
                result = self.run_channel("register", "--role", "listener", *extra, env=env)

                self.assertEqual(result.returncode, 0, result.stderr)
                follow_up = json.loads(result.stdout)["next"]
                self.assertRegex(follow_up, r" heartbeat --channel [0-9]{4} --role listener$")

    def test_codex_session_variable_alone_gives_the_owner(self) -> None:
        result = self.run_channel(
            "register", "--role", "listener", env={"CODEX_SESSION_ID": "codex-session"},
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.owner(), "codex-session")

    def test_declared_host_picks_its_session_variable(self) -> None:
        for host, expected in (("codex", "codex-session"), ("claude", "claude-session")):
            with self.subTest(host=host):
                self.root = Path(self.temp.name) / host
                result = self.run_channel(
                    "register", "--role", "listener",
                    env={"BOOTGEAR_HOST": host, "CLAUDE_CODE_SESSION_ID": "claude-session",
                         "CODEX_SESSION_ID": "codex-session"},
                )

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self.owner(), expected)

    def test_missing_session_names_the_environment_and_the_override(self) -> None:
        result = self.run_channel("register", "--role", "listener")

        self.assertEqual(result.returncode, 2)
        error = json.loads(result.stderr)
        self.assertEqual(error["error"], clikit.missing_session("--session"))
        self.assertIn("example", error)
        self.assertIn("commands", error)

    def test_missing_session_next_tells_the_caller_to_stop_and_tell_the_user(self) -> None:
        for command in (("register", "--role", "listener"), ("whoami",),
                        ("list", "--live-for", "asker"),
                        ("heartbeat", "--channel", "0001", "--role", "listener")):
            with self.subTest(command=command[0]):
                result = self.run_channel(*command)

                self.assertEqual(result.returncode, 2, result.stdout)
                error = json.loads(result.stderr)
                self.assertEqual(error["error"], clikit.missing_session("--session"))
                self.assertNotIn("--session", error["example"])
                self.assertEqual(error["next"], "stop and tell the user that this session has "
                                                "no session id in the environment")


if __name__ == "__main__":
    unittest.main()
