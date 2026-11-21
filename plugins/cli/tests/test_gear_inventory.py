from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from bootgear_cli import gear, hook_loader

from .gear_test_support import CLI_ROOT
from .host_fixture import HOSTS, link_shared_runtime, query_count, write_fake_host


class HostPluginStoreTests(unittest.TestCase):
    """An installed Gear copy routes through fake hosts that log each plugin list query."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="gear-store-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.bin = self.base / "bin"
        self.bin.mkdir()
        self.data = self.base / "data"
        self.homes = {"claude": self.base / "claude-config", "codex": self.base / "codex-home"}
        self.lists = {host: self.base / f"{host}-list.json" for host in HOSTS}
        self.records: dict[str, list[dict[str, object]]] = {host: [] for host in HOSTS}
        self.queries = self.base / "queries.log"
        for host in HOSTS:
            self._write_list(host)
            write_fake_host(self.bin, host)
        self.cli = self.base / "installed" / "cli"
        shutil.copytree(CLI_ROOT, self.cli, ignore=shutil.ignore_patterns("__pycache__", "tests"))
        self.env = {
            "HOME": str(Path.home()),
            "CODEX_HOME": str(self.homes["codex"]),
            "CLAUDE_CONFIG_DIR": str(self.homes["claude"]),
            "XDG_DATA_HOME": str(self.data),
            "GEAR_TEST_QUERIES": str(self.queries),
            "GEAR_TEST_CLAUDE_LIST": str(self.lists["claude"]),
            "GEAR_TEST_CODEX_LIST": str(self.lists["codex"]),
            "PATH": os.pathsep.join((str(self.bin), str(Path(sys.executable).parent), "/usr/bin:/bin")),
            "LANG": "C.UTF-8",
        }

    def _write_list(self, host: str) -> None:
        document: object = (self.records[host] if host == "claude"
                            else {"installed": self.records[host], "available": []})
        self.lists[host].write_text(json.dumps(document), encoding="utf-8")

    def _provider(self, host: str, name: str, message: str, *, version: str = "1.0.0",
                  command: str = "probe") -> Path:
        if host == "codex":
            root = self.homes["codex"] / "plugins" / "cache" / "fixture-marketplace" / name / version
            record: dict[str, object] = {"enabled": True, "installed": True, "name": name,
                                         "marketplaceName": "fixture-marketplace", "version": version}
        else:
            root = self.homes["claude"] / "plugins" / "cache" / name / version
            record = {"enabled": True, "id": f"{name}@fixture-marketplace", "installPath": str(root)}
        (root / "bin").mkdir(parents=True)
        (root / "bin" / "probe").write_text(f"#!/bin/sh\nprintf '%s\\n' '{message}'\n", encoding="utf-8")
        (root / "bin" / "probe").chmod(0o755)
        (root / "gear.toml").write_text(
            f'[plugin]\nname = "{name}"\n\n[commands.{command}]\nexec = ["./bin/probe"]\n', encoding="utf-8")
        self.records[host].append(record)
        self._write_list(host)
        return root

    def _gear(self, host: str, *route: str, **session: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(self.cli / "bin" / "gear"), "--host", host, *route],
            cwd=self.base, env={**self.env, **session}, stdin=subprocess.DEVNULL,
            capture_output=True, text=True, timeout=30, check=False,
        )

    def _query_count(self, host: str) -> int:
        return query_count(self.queries, host)

    def _folder(self, host: str) -> Path:
        return self.data / "bootgear" / "host-plugins" / host

    def _entry(self, host: str, session: str) -> Path:
        return self._folder(host) / f"{session}.json"

    def test_installed_route_reads_the_store_after_the_first_query(self) -> None:
        for host in HOSTS:
            with self.subTest(host=host):
                self._provider(host, "provider", f"{host}-ran")
                for _ in range(2):
                    result = self._gear(host, "provider", "probe", BOOTGEAR_SESSION_ID="session-1")
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, f"{host}-ran\n")
                self.assertEqual(self._query_count(host), 1)
                self.assertTrue(self._entry(host, "session-1").is_file())

    def test_codex_cold_route_uses_dynamic_marketplaces_without_remote_catalog(self) -> None:
        self._provider("codex", "first", "first-ran")
        self._provider("codex", "second", "second-ran")
        old = self.homes["codex"] / "plugins" / "cache" / "fixture-marketplace" / "second"
        new = old.parents[1] / "another-marketplace" / "second"
        new.parent.mkdir(parents=True)
        old.rename(new)
        self.records["codex"][1]["marketplaceName"] = "another-marketplace"
        self._write_list("codex")
        marketplaces = self.base / "marketplaces.json"
        marketplaces.write_text(json.dumps({"marketplaces": [
            {"name": name, "root": str(self.base / name)}
            for name in ("fixture-marketplace", "another-marketplace")]}))
        self.env.update({"GEAR_TEST_CODEX_MARKETPLACES": str(marketplaces),
                         "GEAR_TEST_CODEX_UNSCOPED_FAIL": "1"})
        app = self.homes["codex"] / "plugins" / "cache" / "remote-apps" / "calendar" / "1.0"
        app.mkdir(parents=True)
        (app / "bundle.json").write_text("{}")

        for name in ("first", "second"):
            result = self._gear("codex", name, "probe", BOOTGEAR_SESSION_ID="cold-session")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, f"{name}-ran\n")
        self.assertEqual(self.queries.read_text().splitlines(), [
            "codex plugin marketplace list --json",
            "codex plugin list --marketplace fixture-marketplace --json",
            "codex plugin list --marketplace another-marketplace --json"])

    def test_codex_remote_registration_requires_authoritative_enabled_inventory(self) -> None:
        self._provider("codex", "local", "local-ran")
        old = self._provider("codex", "remote", "remote-ran")
        new = old.parents[2] / "remote-catalog" / "remote" / "1.0.0"
        new.parent.mkdir(parents=True)
        old.rename(new)
        self.records["codex"][-1].update({"marketplaceName": "remote-catalog", "enabled": False})
        self._write_list("codex")

        result = self._gear("codex", "list", BOOTGEAR_SESSION_ID="remote-session")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("local probe", result.stdout)
        self.assertNotIn("remote probe", result.stdout)
        self.assertEqual(self.queries.read_text().splitlines(), [
            "codex plugin marketplace list --json", "codex plugin list --json"])

        self.records["codex"][-1]["enabled"] = True
        self._write_list("codex")
        enabled = self._gear("codex", "remote", "probe", BOOTGEAR_SESSION_ID="enabled-remote")

        self.assertEqual(enabled.returncode, 0, enabled.stderr)
        self.assertEqual(enabled.stdout, "remote-ran\n")
        self.assertEqual(self.queries.read_text().splitlines()[-2:], [
            "codex plugin marketplace list --json", "codex plugin list --json"])

    def test_codex_empty_marketplaces_do_not_query_remote_catalog(self) -> None:
        marketplaces = self.base / "marketplaces.json"
        marketplaces.write_text('{"marketplaces": []}')
        self.env.update({"GEAR_TEST_CODEX_MARKETPLACES": str(marketplaces),
                         "GEAR_TEST_CODEX_UNSCOPED_FAIL": "1"})

        result = self._gear("codex", "list", BOOTGEAR_SESSION_ID="empty-session")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertEqual(self.queries.read_text().splitlines(), ["codex plugin marketplace list --json"])

    def test_codex_remote_catalog_name_is_not_a_local_marketplace_query(self) -> None:
        self._provider("codex", "local", "local-ran")
        marketplaces = self.base / "marketplaces.json"
        marketplaces.write_text(json.dumps({"marketplaces": [
            {"name": name, "root": str(self.base / name)}
            for name in ("fixture-marketplace", "openai-curated-remote")]}))
        self.env["GEAR_TEST_CODEX_MARKETPLACES"] = str(marketplaces)

        result = self._gear("codex", "local", "probe", BOOTGEAR_SESSION_ID="reserved-name")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "local-ran\n")
        self.assertEqual(self.queries.read_text().splitlines(), [
            "codex plugin marketplace list --json",
            "codex plugin list --marketplace fixture-marketplace --json"])

    def test_codex_scoped_query_timeout_names_the_failed_command(self) -> None:
        marketplace = subprocess.CompletedProcess([], 0, json.dumps({"marketplaces": [
            {"name": "fixture-marketplace", "root": str(self.base)}]}), "")
        command = ["codex", "plugin", "list", "--marketplace", "fixture-marketplace", "--json"]
        timeout = subprocess.TimeoutExpired(command, 5)
        with (patch.dict(os.environ, self.env, clear=True),
              patch.object(hook_loader.subprocess, "run", side_effect=[marketplace, timeout]),
              self.assertRaisesRegex(RuntimeError,
                                     "could not query codex plugin list --marketplace fixture-marketplace --json")):
            hook_loader.host_inventory("codex", None)

    def test_route_miss_after_a_stored_read_queries_once(self) -> None:
        for host in HOSTS:
            with self.subTest(host=host):
                self._provider(host, "first", "first-ran")
                first = self._gear(host, "first", "probe", BOOTGEAR_SESSION_ID="session-1")
                self.assertEqual(first.stdout, "first-ran\n", first.stderr)
                self._provider(host, "second", "second-ran")

                result = self._gear(host, "second", "probe", BOOTGEAR_SESSION_ID="session-1")

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "second-ran\n")
                self.assertEqual(self._query_count(host), 2)

    def test_gone_stored_folder_refreshes_to_the_new_version(self) -> None:
        old = self._provider("codex", "provider", "old-release", version="1.0.0")
        first = self._gear("codex", "provider", "probe", BOOTGEAR_SESSION_ID="session-1")
        self.assertEqual(first.stdout, "old-release\n", first.stderr)
        shutil.rmtree(old)
        self.records["codex"].clear()
        self._provider("codex", "provider", "new-release", version="1.0.1")

        result = self._gear("codex", "provider", "probe", BOOTGEAR_SESSION_ID="session-1")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "new-release\n")
        self.assertNotIn("missing", result.stderr)
        self.assertEqual(self._query_count("codex"), 2)

    def test_persistently_missing_folder_does_not_force_queries(self) -> None:
        self.records["codex"].append({"enabled": True, "installed": True, "name": "notion",
                                      "marketplaceName": "fixture-marketplace", "version": "1.0.0"})
        self.records["codex"].append({"enabled": True, "installed": True, "name": "unversioned",
                                      "marketplaceName": "fixture-marketplace"})
        self._provider("codex", "provider", "provider-ran")

        first = self._gear("codex", "provider", "probe", BOOTGEAR_SESSION_ID="session-1")
        second = self._gear("codex", "provider", "probe", BOOTGEAR_SESSION_ID="session-1")

        self.assertEqual(first.stdout, "provider-ran\n", first.stderr)
        self.assertIn("installed plugin notion is missing", first.stderr)
        self.assertIn("installed plugin has incomplete cache identity", first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(second.stdout, "provider-ran\n")
        self.assertEqual(second.stderr, "")
        self.assertEqual(self._query_count("codex"), 1)

    def test_silent_failing_host_query_names_the_command_once(self) -> None:
        for host, source in (("claude", "Claude"), ("codex", "Codex")):
            with self.subTest(host=host):
                (self.bin / host).write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")

                result = self._gear(host, "list", BOOTGEAR_SESSION_ID="session-1")

                command = f"{host} plugin " + ("marketplace list --json" if host == "codex" else "list --json")
                self.assertIn(f"gear: {source}: {command} failed: exit code 1\n",
                              result.stderr)
                self.assertEqual(result.stderr.count(f"{command} failed"), 1, result.stderr)

    def test_host_query_with_invalid_json_names_the_command_once(self) -> None:
        for host, source in (("claude", "Claude"), ("codex", "Codex")):
            with self.subTest(host=host):
                (self.bin / host).write_text("#!/bin/sh\necho 'not json'\n", encoding="utf-8")

                result = self._gear(host, "list", BOOTGEAR_SESSION_ID="session-1")

                command = f"{host} plugin " + ("marketplace list --json" if host == "codex" else "list --json")
                self.assertIn(f"gear: {source}: {command} returned invalid JSON: ",
                              result.stderr)
                self.assertEqual(result.stderr.count(command), 1, result.stderr)

    def test_without_session_every_call_queries(self) -> None:
        for host in HOSTS:
            with self.subTest(host=host):
                self._provider(host, "provider", "provider-ran")
                for _ in range(2):
                    result = self._gear(host, "provider", "probe")
                    self.assertEqual(result.stdout, "provider-ran\n", result.stderr)
                self.assertEqual(self._query_count(host), 2)
                self.assertFalse(self._folder(host).exists())

    def test_reconcile_builtin_always_queries(self) -> None:
        for host in HOSTS:
            with self.subTest(host=host):
                self._provider(host, "provider", "provider-ran")
                warm = self._gear(host, "provider", "probe", BOOTGEAR_SESSION_ID="session-1")
                self.assertEqual(warm.stdout, "provider-ran\n", warm.stderr)
                for expected in (2, 3):
                    result = self._gear(host, "reconcile", BOOTGEAR_SESSION_ID="session-1")
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn("provider probe", result.stdout)
                    self.assertEqual(self._query_count(host), expected)

    def test_resolve_command_refreshes_once_on_a_stored_miss(self) -> None:
        empty = self.base / "empty-root"
        empty.mkdir()
        for host, variable in (("claude", "CLAUDE_CODE_SESSION_ID"), ("codex", "CODEX_SESSION_ID")):
            with self.subTest(host=host), patch.dict(os.environ, {
                **self.env, "GEAR_ROOT": str(empty), "BOOTGEAR_HOST": host, variable: "session-1",
            }, clear=True):
                self._provider(host, "alpha", "alpha-ran", command="alpha-command")
                found = gear.resolve_command("alpha-command")
                self.assertEqual((found or [])[-2:], ["alpha", "alpha-command"])
                self.assertEqual(self._query_count(host), 1)

                self._provider(host, "beta", "beta-ran", command="beta-command")
                added = gear.resolve_command("beta-command")
                self.assertEqual((added or [])[-2:], ["beta", "beta-command"])
                self.assertEqual(self._query_count(host), 2)

                self.assertIsNone(gear.resolve_command("unknown-command"))
                self.assertEqual(self._query_count(host), 3)
        for host in HOSTS:
            with self.subTest(host=host, session=None), patch.dict(os.environ, {
                **self.env, "GEAR_ROOT": str(empty), "BOOTGEAR_HOST": host,
            }, clear=True):
                before = self._query_count(host)
                self.assertIsNone(gear.resolve_command("unknown-command"))
                self.assertEqual(self._query_count(host) - before, 1)

    def test_installed_session_start_prints_nothing_and_queries_once(self) -> None:
        link_shared_runtime(self.data)
        self.records["claude"].append({"enabled": True, "id": "notion@fixture-marketplace",
                                       "installPath": str(self.base / "gone" / "notion")})
        self.records["codex"].append({"enabled": True, "installed": True, "name": "notion",
                                      "marketplaceName": "fixture-marketplace", "version": "1.0.0"})
        for host in HOSTS:
            self._write_list(host)
        failing = self.bin / "failing"
        failing.mkdir()
        for host in HOSTS:
            (failing / host).write_text(
                "#!/bin/sh\nprintf '%s %s\\n' \"$(basename \"$0\")\" \"$*\" >> \"$GEAR_TEST_QUERIES\"\n"
                "echo 'host down' >&2\nexit 1\n", encoding="utf-8")
            (failing / host).chmod(0o755)
        for host in HOSTS:
            for case, path in (("missing-folder", self.env["PATH"]),
                               ("failing-host", os.pathsep.join((str(failing), self.env["PATH"])))):
                with self.subTest(host=host, case=case):
                    session = f"{host}-{case}"
                    before = self._query_count(host)
                    result = subprocess.run(
                        [str(self.cli / "bin" / "gear"), "--host", host, "cli", "session-start"],
                        cwd=self.base, env={**self.env, "PATH": path, "BOOTGEAR_SESSION_ID": session},
                        input=json.dumps({"session_id": session, "source": "startup"}),
                        capture_output=True, text=True, timeout=30, check=False)

                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual((result.stdout, result.stderr), ("", ""))
                    self.assertEqual(self._query_count(host) - before, 1)

    def test_event_refreshes_once_when_a_plugin_with_a_reminder_joins(self) -> None:
        for host in HOSTS:
            with self.subTest(host=host):
                self._provider(host, "first", "first-ran")
                warm = self._gear(host, "first", "probe", BOOTGEAR_SESSION_ID=f"{host}-event")
                self.assertEqual(warm.stdout, "first-ran\n", warm.stderr)
                root = self._provider(host, "reminding", "reminder-ran")
                with (root / "gear.toml").open("a", encoding="utf-8") as registration:
                    registration.write('\n[reminders.post-tool-use]\nexec = ["./bin/probe"]\n')

                result = self._gear(host, "event", "post-tool-use", BOOTGEAR_SESSION_ID=f"{host}-event")

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "reminder-ran\n")
                self.assertEqual(self._query_count(host), 2)

    def test_session_key_follows_the_environment_chain(self) -> None:
        for host, variable in (("claude", "CLAUDE_CODE_SESSION_ID"), ("codex", "CODEX_SESSION_ID")):
            with self.subTest(host=host):
                self._provider(host, "provider", "provider-ran")
                for _ in range(2):
                    result = self._gear(host, "provider", "probe", **{variable: f"{host}-session"})
                    self.assertEqual(result.stdout, "provider-ran\n", result.stderr)
                self.assertEqual(self._query_count(host), 1)
                self.assertEqual(sorted(path.name for path in self._folder(host).iterdir()),
                                 [f"{host}-session.json"])

    def test_bad_store_entry_is_replaced(self) -> None:
        for host in HOSTS:
            with self.subTest(host=host):
                self._provider(host, "provider", "provider-ran")
                self._folder(host).mkdir(parents=True)
                self._entry(host, "bad-json").write_text("{not json", encoding="utf-8")
                self._entry(host, "no-inventory").write_text('{"other": []}', encoding="utf-8")
                for session in ("bad-json", "no-inventory", "bad-json", "no-inventory"):
                    result = self._gear(host, "provider", "probe", BOOTGEAR_SESSION_ID=session)
                    self.assertEqual(result.stdout, "provider-ran\n", result.stderr)
                self.assertEqual(self._query_count(host), 2)
                expected = json.loads(self.lists[host].read_text(encoding="utf-8"))
                for session in ("bad-json", "no-inventory"):
                    self.assertEqual(json.loads(self._entry(host, session).read_text(encoding="utf-8")),
                                     {"inventory": expected})

    def test_store_is_owner_only_and_unsafe_session_writes_nothing(self) -> None:
        for host in HOSTS:
            with self.subTest(host=host):
                self._provider(host, "provider", "provider-ran")
                stored = self._gear(host, "provider", "probe", BOOTGEAR_SESSION_ID="session-1")
                self.assertEqual(stored.stdout, "provider-ran\n", stored.stderr)
                self.assertEqual(stat.S_IMODE(self._folder(host).stat().st_mode), 0o700)
                self.assertEqual(stat.S_IMODE(self._entry(host, "session-1").stat().st_mode), 0o600)

                unsafe = self._gear(host, "provider", "probe", BOOTGEAR_SESSION_ID="../x")

                self.assertEqual(unsafe.stdout, "provider-ran\n", unsafe.stderr)
                self.assertEqual([path.name for path in self._folder(host).iterdir()], ["session-1.json"])
                self.assertFalse((self._folder(host).parent / "x.json").exists())

    def test_old_entries_are_pruned_on_fresh_write(self) -> None:
        now = time.time()
        for host in HOSTS:
            with self.subTest(host=host):
                self._folder(host).mkdir(parents=True)
                old = self._entry(host, "old-session")
                recent = self._entry(host, "recent-session")
                for path, age_days in ((old, 8), (recent, 1)):
                    path.write_text('{"inventory": []}', encoding="utf-8")
                    os.utime(path, (now - age_days * 86400, now - age_days * 86400))
                self._provider(host, "provider", "provider-ran")

                result = self._gear(host, "provider", "probe", BOOTGEAR_SESSION_ID="session-1")

                self.assertEqual(result.stdout, "provider-ran\n", result.stderr)
                self.assertFalse(old.exists())
                self.assertTrue(recent.exists())
                self.assertTrue(self._entry(host, "session-1").is_file())

    def test_store_write_failure_keeps_the_call(self) -> None:
        for host in HOSTS:
            with self.subTest(host=host):
                self._provider(host, "provider", "provider-ran")
                self._folder(host).mkdir(parents=True)
                self._folder(host).chmod(0o500)
                self.addCleanup(self._folder(host).chmod, 0o700)

                result = self._gear(host, "provider", "probe", BOOTGEAR_SESSION_ID="session-1")

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "provider-ran\n")
                self.assertNotIn("setup", result.stdout + result.stderr)
                self.assertFalse(self._entry(host, "session-1").exists())
