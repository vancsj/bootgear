from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

from bootgear_cli import hook_loader

from .cli_integration_test_support import CLI_ROOT, GearIntegrationTestsCase
from .host_fixture import link_shared_runtime


class SessionStartTests(GearIntegrationTestsCase):
    def setUp(self) -> None:
        super().setUp()
        link_shared_runtime(self.data)

    def _start(self, host: str, source: str, session: str = "example") -> subprocess.CompletedProcess:
        payload = json.dumps({"hook_event_name": "SessionStart", "source": source,
                              "session_id": session, "cwd": str(self.base)})
        return subprocess.run(
            [str(CLI_ROOT / "hooks/gear"), "--host", host, "session-start"],
            input=payload, cwd=self.base, env=self.env,
            capture_output=True, text=True, timeout=15, check=False,
        )

    def test_startup_and_fork_share_the_first_scan_and_resume_refreshes(self) -> None:
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                for source in ("startup", "startup", "resume", "clear", "compact"):
                    result = self._start(host, source)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, "", result.stdout)
                for _ in range(2):
                    result = self._start(host, "fork", "new-fork")
                    self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(self._query_count(host), 5)

    def test_failed_resume_invalidates_old_inventory(self) -> None:
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                result = self._start(host, "startup")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.env["GEAR_TEST_HOST_FAIL"] = "1"
                try:
                    failed = self._start(host, "resume")
                finally:
                    self.env.pop("GEAR_TEST_HOST_FAIL")
                self.assertEqual(failed.returncode, 0, failed.stderr)
                self.assertIn("host failed", failed.stdout)
                with patch.dict("os.environ", self.env):
                    self.assertFalse(hook_loader.store_path(host, "example").exists())

    def test_unsafe_session_id_never_queries_inventory(self) -> None:
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                result = self._start(host, "startup", "../unsafe")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("fresh host session", result.stdout)
                self.assertEqual(self._query_count(host), 0)
