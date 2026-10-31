from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

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
                       if key not in {"BOOTGEAR_SESSION_ID", "CLAUDE_CODE_SESSION_ID"}}
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
        self.assertIn("--session shared-session", json.loads(result.stdout)["next"])

    def test_missing_session_keeps_a_clear_required_option_error(self) -> None:
        result = self.run_channel("register", "--role", "listener")

        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stderr)["error"], "the following arguments are required: --session")


if __name__ == "__main__":
    unittest.main()
