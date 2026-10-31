from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

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
            "MEMORY_LEDGER_SESSION_ID": "ledger-session",
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

    def test_memory_ledger_session_remains_a_lower_priority_fallback(self) -> None:
        context = self.context({"MEMORY_LEDGER_SESSION_ID": "ledger-session"}, host="codex")

        self.assertEqual(context.session_id, "ledger-session")
        self.assertEqual(resolve_identity(context), "codex:ledger-session")

    def test_bootgear_session_does_not_infer_a_host(self) -> None:
        context = self.context({"BOOTGEAR_SESSION_ID": "shared-session"})

        self.assertEqual(context.host, "standalone")
        self.assertEqual(context.session_id, "shared-session")
        self.assertEqual(resolve_identity(context), "shared-session")

    def test_missing_codex_session_keeps_a_clear_error(self) -> None:
        context = self.context({}, host="codex")

        with self.assertRaisesRegex(SystemExit, "Codex session_id is required"):
            resolve_identity(context)

    def test_missing_standalone_identity_keeps_a_clear_error(self) -> None:
        context = self.context({})

        with self.assertRaisesRegex(SystemExit, "session identity unset"):
            resolve_identity(context)


if __name__ == "__main__":
    unittest.main()
