from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bootgear_cli import clikit

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "scripts"))

from ledgerlib.context import InvocationContext
from ledgerlib.identity import resolve_identity


class SessionIdentityTests(unittest.TestCase):
    def context(self, env: dict[str, str], *, host: str | None = None,
                session_id: str | None = None) -> InvocationContext:
        with patch.dict(os.environ, env, clear=True):
            return InvocationContext.from_environment(host=host, session_id=session_id)

    def test_explicit_session_option_wins_over_environment(self) -> None:
        context = self.context({
            "BOOTGEAR_SESSION_ID": "shared-session",
            "CLAUDE_CODE_SESSION_ID": "claude-session",
        }, host="codex", session_id="explicit-session")

        self.assertEqual(context.session_id, "explicit-session")
        self.assertEqual(resolve_identity(context), "codex:explicit-session")

    def test_bootgear_session_precedes_claude_session(self) -> None:
        context = self.context({
            "BOOTGEAR_SESSION_ID": "shared-session",
            "CLAUDE_CODE_SESSION_ID": "claude-session",
        }, host="codex")

        self.assertEqual(context.session_id, "shared-session")
        self.assertEqual(resolve_identity(context), "codex:shared-session")

    def test_claude_session_is_the_fallback(self) -> None:
        context = self.context({"CLAUDE_CODE_SESSION_ID": "claude-session"}, host="codex")

        self.assertEqual(context.session_id, "claude-session")
        self.assertEqual(resolve_identity(context), "codex:claude-session")

    def test_shared_context_selects_codex_and_preserves_the_session(self) -> None:
        context = self.context({"BOOTGEAR_HOST": "codex", "BOOTGEAR_SESSION_ID": "shared-session",
                                "CLAUDE_CODE_SESSION_ID": "claude-session"})
        self.assertEqual(context.host, "codex")
        self.assertEqual(resolve_identity(context), "codex:shared-session")

    def test_explicit_host_wins_over_shared_context(self) -> None:
        context = self.context({"BOOTGEAR_HOST": "codex", "BOOTGEAR_SESSION_ID": "shared-session"},
                               host="claude")
        self.assertEqual(context.host, "claude")
        self.assertEqual(resolve_identity(context), "shared")

    def test_bootgear_session_does_not_infer_a_host(self) -> None:
        context = self.context({"BOOTGEAR_SESSION_ID": "shared-session"})

        self.assertEqual(context.host, "standalone")
        self.assertEqual(context.session_id, "shared-session")
        self.assertEqual(resolve_identity(context), "shared-session")

    def test_codex_host_reads_the_codex_session_variable(self) -> None:
        context = self.context({"CODEX_SESSION_ID": "codex-session"}, host="codex")

        self.assertEqual(context.session_id, "codex-session")
        self.assertEqual(resolve_identity(context), "codex:codex-session")

    def test_codex_session_variable_gives_the_codex_signer_without_a_host(self) -> None:
        context = self.context({"CODEX_SESSION_ID": "codex-session"})

        self.assertEqual(context.host, "codex")
        self.assertEqual(resolve_identity(context), "codex:codex-session")

    def test_declared_host_picks_its_session_variable(self) -> None:
        for host, expected in (("codex", "codex-session"), ("claude", "claude-session")):
            with self.subTest(host=host):
                context = self.context({"BOOTGEAR_HOST": host,
                                        "CLAUDE_CODE_SESSION_ID": "claude-session",
                                        "CODEX_SESSION_ID": "codex-session"})

                self.assertEqual(context.host, host)
                self.assertEqual(context.session_id, expected)
        self.assertEqual(resolve_identity(self.context({
            "BOOTGEAR_HOST": "codex", "CLAUDE_CODE_SESSION_ID": "claude-session",
            "CODEX_SESSION_ID": "codex-session"})), "codex:codex-session")

    def test_explicit_host_picks_its_session_variable(self) -> None:
        both = {"CLAUDE_CODE_SESSION_ID": "claude-session", "CODEX_SESSION_ID": "codex-session"}
        for host, ancestor in (("codex", "claude"), ("claude", "codex")):
            with self.subTest(host=host), patch.object(clikit, "_ancestor_host",
                                                       return_value=ancestor):
                context = self.context(both, host=host)

                self.assertEqual(context.session_id, f"{host}-session")
        with patch.object(clikit, "_ancestor_host", return_value="claude"):
            self.assertEqual(resolve_identity(self.context(both, host="codex")),
                             "codex:codex-session")

    def doctor(self, base: Path, extra_env: dict[str, str], *mode: str) -> str:
        roots = []
        for name in ("shared", "local"):
            if not (base / name).is_dir():
                subprocess.run(["git", "init", "-q", str(base / name)], check=True)
            roots.append(str(base / name))
        env = {key: value for key, value in os.environ.items()
               if key not in {"BOOTGEAR_HOST", "BOOTGEAR_SESSION_ID", "BOOTGEAR_OUTPUT",
                              "CLAUDE_CODE_SESSION_ID", "CODEX_SESSION_ID"}}
        env.update(HOME=str(base), **extra_env)
        result = subprocess.run(
            [sys.executable, str(PLUGIN / "scripts" / "ledger.py"), "--root", roots[0],
             "--local-root", roots[1], "doctor", *mode],
            cwd=base, env=env, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_doctor_reports_the_codex_session_without_a_claude_variable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            codex = {"CODEX_SESSION_ID": "codex-session"}
            warnings = json.loads(self.doctor(Path(tmp), codex, "--json"))["warnings"]
            self.assertFalse([w for w in warnings if "session identity unset" in w], warnings)
            self.assertRegex(self.doctor(Path(tmp), codex, "--prose"),
                             r"session id +codex session_id=codex-session\n")

    def test_doctor_without_a_session_names_both_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            warnings = json.loads(self.doctor(Path(tmp), {}, "--json"))["warnings"]
            self.assertIn("session identity unset — `sign` will refuse; pass --session-id or --as <id>",
                          "\n".join(warnings))

    def test_missing_codex_session_names_the_environment_and_the_override(self) -> None:
        context = self.context({}, host="codex")

        with self.assertRaises(SystemExit) as raised:
            resolve_identity(context)
        self.assertIn(clikit.missing_session("--session-id"), str(raised.exception.code))

    def test_missing_signer_names_the_environment_and_the_override(self) -> None:
        for host in (None, "claude"):
            with self.subTest(host=host):
                context = self.context({}, host=host)

                with self.assertRaises(SystemExit) as raised:
                    resolve_identity(context)
                self.assertEqual(str(raised.exception.code),
                                 "no signer: " + clikit.missing_session("--session-id or --as <id>"))


if __name__ == "__main__":
    unittest.main()
