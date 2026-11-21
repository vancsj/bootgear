import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from bootgear_cli import clikit, host_context

from .clikit_test_support import (
    ENDLESS_CHAIN_PS,
    FAILING_PS,
    HOST_CHAIN_PS,
    INIT_PARENT_PS,
    SESSION_VARIABLES,
)


class SessionContextTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        for name in (*SESSION_VARIABLES, "BOOTGEAR_HOST"):
            os.environ.pop(name, None)
        bin_dir = tempfile.TemporaryDirectory(prefix="clikit-fake-ps-")
        self.addCleanup(bin_dir.cleanup)
        self.ps = Path(bin_dir.name) / "ps"
        self.fake_ps(FAILING_PS)
        os.environ["PATH"] = os.pathsep.join([bin_dir.name, os.environ.get("PATH", "")])

    def fake_ps(self, script: str) -> None:
        self.ps.write_text(script)
        self.ps.chmod(0o755)

    def test_both_session_variables_use_the_declared_host(self):
        self.fake_ps(HOST_CHAIN_PS)
        os.environ.update({"CLAUDE_CODE_SESSION_ID": "claude-id", "CODEX_SESSION_ID": "codex-id"})
        for declared, expected in (("codex", "codex-id"), ("claude", "claude-id")):
            with self.subTest(host=declared):
                os.environ["BOOTGEAR_HOST"] = declared
                self.assertEqual(clikit.host(), declared)
                self.assertEqual(clikit.session_id(), expected)

    def test_ancestor_host_finds_the_nearest_host_process(self):
        self.fake_ps(HOST_CHAIN_PS)
        self.assertEqual(host_context._ancestor_host(), "codex")

    def test_ancestor_host_gives_none_when_ps_fails(self):
        self.assertIsNone(host_context._ancestor_host())

    def test_ancestor_host_stops_after_the_step_limit(self):
        calls = Path(self.ps.parent) / "calls"
        self.fake_ps(ENDLESS_CHAIN_PS.format(calls=calls))
        self.assertIsNone(host_context._ancestor_host())
        self.assertEqual(len(calls.read_text().splitlines()), host_context.ANCESTOR_STEPS)

    def test_ancestor_host_gives_none_on_a_ps_timeout(self):
        timeout = host_context.subprocess.TimeoutExpired(["ps"], host_context.PS_TIMEOUT)
        with mock.patch.object(host_context.subprocess, "run", side_effect=timeout) as run:
            self.assertIsNone(host_context._ancestor_host())
        self.assertEqual(run.call_args.kwargs["timeout"], host_context.PS_TIMEOUT)

    def test_ancestor_host_ignores_a_host_line_from_a_failed_ps(self):
        self.fake_ps('#!/bin/sh\necho "    1 /usr/local/bin/claude"\nexit 1\n')
        self.assertIsNone(host_context._ancestor_host())

    def test_ancestor_host_stops_at_pid_1(self):
        calls = Path(self.ps.parent) / "calls"
        self.fake_ps(INIT_PARENT_PS.format(calls=calls))
        self.assertIsNone(host_context._ancestor_host())
        self.assertEqual(len(calls.read_text().splitlines()), 1)

    def test_session_id_with_both_variables_and_no_host_uses_the_ancestor(self):
        self.fake_ps(HOST_CHAIN_PS)
        os.environ.update({"CLAUDE_CODE_SESSION_ID": "claude-id", "CODEX_SESSION_ID": "codex-id"})
        self.assertEqual(clikit.host(), "codex")
        self.assertEqual(clikit.session_id(), "codex-id")

    def test_session_id_uses_the_host_keyword_over_the_ancestor(self):
        self.fake_ps(HOST_CHAIN_PS)
        os.environ.update({"CLAUDE_CODE_SESSION_ID": "claude-id", "CODEX_SESSION_ID": "codex-id"})
        self.assertEqual(clikit.session_id(host="claude"), "claude-id")
        self.fake_ps(FAILING_PS)
        self.assertEqual(clikit.session_id(host="codex"), "codex-id")

    def test_session_id_prefers_explicit_then_environment_order(self):
        self.assertIsNone(clikit.session_id())
        os.environ["CODEX_SESSION_ID"] = "codex-id"
        self.assertEqual(clikit.session_id(), "codex-id")
        os.environ["CLAUDE_CODE_SESSION_ID"] = "claude-id"
        self.assertEqual(clikit.session_id(), "claude-id")  # both set, no host ancestor
        os.environ["BOOTGEAR_SESSION_ID"] = "shared-id"
        self.assertEqual(clikit.session_id(), "shared-id")
        self.assertEqual(clikit.session_id("explicit-id"), "explicit-id")

    def test_session_id_skips_empty_values(self):
        os.environ.update({"BOOTGEAR_SESSION_ID": "", "CLAUDE_CODE_SESSION_ID": "",
                           "CODEX_SESSION_ID": "codex-id"})
        self.assertEqual(clikit.session_id(), "codex-id")
        os.environ["CODEX_SESSION_ID"] = ""
        self.assertIsNone(clikit.session_id())

    def test_missing_session_names_the_override(self):
        self.assertEqual(
            clikit.missing_session("--session"),
            "no session id found in the environment; run inside a Claude Code or Codex "
            "session, or pass --session")

    def test_host_prefers_explicit_then_bootgear_host_then_the_session_variable(self):
        self.assertIsNone(clikit.host())
        os.environ["CODEX_SESSION_ID"] = "codex-id"
        self.assertEqual(clikit.host(), "codex")
        os.environ["BOOTGEAR_HOST"] = ""
        self.assertEqual(clikit.host(), "codex")
        del os.environ["CODEX_SESSION_ID"]
        os.environ["CLAUDE_CODE_SESSION_ID"] = "claude-id"
        self.assertEqual(clikit.host(), "claude")
        os.environ["CODEX_SESSION_ID"] = "codex-id"
        self.assertEqual(clikit.host(), "claude")  # both set, no host ancestor
        os.environ["BOOTGEAR_HOST"] = "codex"
        self.assertEqual(clikit.host(), "codex")
        self.assertEqual(clikit.host("claude"), "claude")
