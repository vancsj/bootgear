from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bootgear_cli import session_start

from .host_fixture import HOSTS, link_shared_runtime, query_count, write_fake_host

CLI_ROOT = Path(__file__).resolve().parents[1]
GEAR = CLI_ROOT / "bin" / "gear"


class SessionStartTests(unittest.TestCase):
    """`gear cli session-start` runs through fake hosts that log each plugin list query."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="gear-session-start-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.data = self.base / "data"
        link_shared_runtime(self.data)
        self.queries = self.base / "queries.log"
        self.lists = {
            "claude": '[{"enabled": true, "id": "cli@fixture", "installPath": "/missing"}]',
            "codex": '{"installed": [], "available": []}',
        }
        for host in HOSTS:
            (self.base / f"{host}-list.json").write_text(self.lists[host], encoding="utf-8")
            write_fake_host(self.bin, host)
        self.env = {
            "HOME": str(Path.home()),
            "XDG_DATA_HOME": str(self.data),
            "GEAR_TEST_QUERIES": str(self.queries),
            "GEAR_TEST_CLAUDE_LIST": str(self.base / "claude-list.json"),
            "GEAR_TEST_CODEX_LIST": str(self.base / "codex-list.json"),
            "PATH": os.pathsep.join((str(self.bin), str(Path(sys.executable).parent), "/usr/bin:/bin")),
            "LANG": "C.UTF-8",
        }

    def _session_start(self, host: str, payload: bytes, **extra: str) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [str(GEAR), "--host", host, "cli", "session-start"],
            cwd=self.base, env={**self.env, **extra}, input=payload,
            capture_output=True, timeout=30, check=False,
        )

    def _query_count(self, host: str) -> int:
        return query_count(self.queries, host)

    def _folder(self, host: str) -> Path:
        return self.data / "bootgear" / "host-plugins" / host

    @staticmethod
    def _payload(session: object, source: str = "startup") -> bytes:
        return json.dumps({"hook_event_name": "SessionStart", "session_id": session,
                           "source": source}).encode()

    def test_session_start_refreshes_the_stored_entry(self) -> None:
        for host in HOSTS:
            with self.subTest(host=host):
                entry = self._folder(host) / "session-1.json"
                entry.parent.mkdir(parents=True)
                entry.write_text('{"inventory": "stale"}', encoding="utf-8")

                result = self._session_start(host, self._payload("session-1", "resume"))

                self.assertEqual(result.returncode, 0, result.stderr.decode())
                self.assertEqual(result.stdout, b"")
                self.assertEqual(result.stderr, b"")
                self.assertEqual(self._query_count(host), 1)
                self.assertEqual(json.loads(entry.read_text(encoding="utf-8")),
                                 {"inventory": json.loads(self.lists[host])})

    def test_session_start_failure_keeps_the_session(self) -> None:
        for host in HOSTS:
            with self.subTest(host=host):
                failed = self._session_start(host, self._payload("session-1"), GEAR_TEST_HOST_FAIL="1")
                self.assertEqual(failed.returncode, 0, failed.stderr.decode())
                self.assertEqual(failed.stdout, b"")
                self.assertEqual(self._query_count(host), 1)

                self._folder(host).mkdir(parents=True)
                self._folder(host).chmod(0o500)
                self.addCleanup(self._folder(host).chmod, 0o700)
                unwritable = self._session_start(host, self._payload("session-1"))

                self.assertEqual(unwritable.returncode, 0, unwritable.stderr.decode())
                self.assertEqual(unwritable.stdout, b"")
                self.assertEqual(self._query_count(host), 2)
                self.assertEqual(list(self._folder(host).iterdir()), [])

    def test_session_start_without_a_safe_session_does_nothing(self) -> None:
        payloads = (b'{"hook_event_name": "SessionStart", "source": "startup"}',
                    self._payload("../x"), self._payload(7), b"not json")
        for host in HOSTS:
            for payload in payloads:
                with self.subTest(host=host, payload=payload):
                    result = self._session_start(host, payload)

                    self.assertEqual(result.returncode, 0, result.stderr.decode())
                    self.assertEqual(result.stdout, b"")
                    self.assertEqual(self._query_count(host), 0)
                    self.assertFalse((self.data / "bootgear" / "host-plugins").exists())


class SessionStartErrorTests(unittest.TestCase):
    """`session_start.main` in process, with a host query that raises."""

    def _main(self, error: BaseException) -> tuple[int, str]:
        stdin = io.TextIOWrapper(io.BytesIO(b'{"session_id": "session-1", "source": "startup"}'))
        stdout = io.StringIO()
        with (patch.dict(os.environ, {"BOOTGEAR_HOST": "codex"}),
              patch.object(session_start.hook_loader, "host_inventory", side_effect=error),
              patch.object(sys, "stdin", stdin), contextlib.redirect_stdout(stdout)):
            code = session_start.main()
        return code, stdout.getvalue()

    def test_query_and_store_failures_exit_0_without_output(self) -> None:
        for error in (OSError("denied"), ValueError("bad json"), TypeError("bad list"),
                      RuntimeError("host failed"), subprocess.TimeoutExpired(["codex"], 5)):
            with self.subTest(error=type(error).__name__):
                self.assertEqual(self._main(error), (0, ""))

    def test_a_code_error_is_not_hidden(self) -> None:
        with self.assertRaises(AttributeError):
            self._main(AttributeError("code bug"))


if __name__ == "__main__":
    unittest.main()
