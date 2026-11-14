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

from bootgear_cli import gear, hook_loader, runtime


class DependencySetupTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="gear-dependencies-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.records: dict[str, list[dict]] = {"claude": [], "codex": []}
        self.refreshes: list[tuple[str, bool]] = []
        self.installs: list[list[str]] = []
        self.pending: dict[str, tuple[tuple[str, ...], bool]] = {}
        self.host = "codex"

    def _plugin(self, name: str, dependencies: tuple[str, ...] = (), *,
                enabled: bool = True, installed: bool = True) -> Path:
        if self.host == "codex":
            root = self.base / "codex" / "plugins" / "cache" / "bootgear" / name / "1.0.0"
            record = {"name": name, "marketplaceName": "bootgear", "version": "1.0.0",
                      "enabled": enabled, "installed": installed}
        else:
            root = self.base / "claude" / name
            record = {"id": f"{name}@bootgear", "installPath": str(root), "enabled": enabled}
        manifest = root / ".claude-plugin" / "plugin.json"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text(json.dumps({"name": name, "dependencies": list(dependencies)}))
        self.records[self.host] = [item for item in self.records[self.host]
                                   if item.get("name", item.get("id", "").split("@")[0]) != name]
        self.records[self.host].append(record)
        return root

    def _inventory(self, host: str, session: str | None, *, refresh: bool = False) -> tuple[object, bool]:
        self.refreshes.append((host, refresh))
        records = self.records[host]
        return ({"installed": records} if host == "codex" else records), False

    def _install(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        self.installs.append(command)
        self.assertEqual(command[:3], ["codex", "plugin", "add"])
        name = command[3].removesuffix("@bootgear")
        dependencies, enabled = self.pending[name]
        self._plugin(name, dependencies, enabled=enabled)
        return subprocess.CompletedProcess(command, 0, "installed", "")

    def _run(self, *arguments: str, inventory_error: str | None = None,
             install_error: str | None = None) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, {
                "BOOTGEAR_HOST": self.host, "CODEX_HOME": str(self.base / "codex"),
                "GEAR_ROOT": str(self.base / "source"), "GEAR_CALLER_CWD": str(self.base),
            }))
            stack.enter_context(patch.object(sys, "argv", ["setup", *arguments]))
            stack.enter_context(patch.object(runtime, "setup", return_value=self.base / "runtime"))
            stack.enter_context(patch("shutil.which", side_effect=lambda name: f"/bin/{name}"))
            inventory = stack.enter_context(patch.object(hook_loader, "host_inventory", side_effect=self._inventory))
            if inventory_error:
                inventory.side_effect = RuntimeError(inventory_error)
            install = stack.enter_context(patch("subprocess.run", side_effect=self._install))
            if install_error:
                install.side_effect = lambda command, **kwargs: subprocess.CompletedProcess(command, 1, "", install_error)
            stack.enter_context(contextlib.redirect_stdout(stdout))
            stack.enter_context(contextlib.redirect_stderr(stderr))
            try:
                result = runtime.main()
            except SystemExit as exc:
                if not isinstance(exc.code, int):
                    raise
                result = exc.code
        return result, stdout.getvalue(), stderr.getvalue()

    def test_no_target_only_prepares_runtime(self) -> None:
        result, stdout, stderr = self._run()
        self.assertEqual(result, 0, stderr)
        self.assertIn("Shared runtime ready", stdout)
        self.assertEqual(self.refreshes, [])
        self.assertEqual(self.installs, [])

    def test_missing_plugin_value_reports_a_valid_example(self) -> None:
        result, _, stderr = self._run("--plugin")
        self.assertEqual(result, 2)
        self.assertIn("expected one argument", stderr)
        self.assertIn("cli setup --help", stderr)
        self.assertIn("commands: setup, session-start", stderr)

    def test_both_hosts_check_transitive_skill_only_dependencies_once(self) -> None:
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                self.host = host
                self._plugin("engine", ("spec", "review"))
                self._plugin("spec", ("review",))
                self._plugin("review", ("engine",))
                self.refreshes.clear()
                result, stdout, stderr = self._run("--plugin", "engine", "--json")
                self.assertEqual(result, 0, stderr)
                self.assertEqual(json.loads(stdout)["plugins"], ["engine", "review", "spec"])
                self.assertEqual(self.refreshes, [(host, True)])
        self.assertEqual(self.installs, [])

    def test_codex_installs_nested_missing_dependencies_and_repeat_setup_rechecks(self) -> None:
        self._plugin("engine", ("spec", "review"))
        self.pending = {"spec": (("review",), True), "review": ((), True)}
        result, _, stderr = self._run("--plugin", "engine")
        self.assertEqual(result, 0, stderr)
        self.assertEqual(self.installs, [["codex", "plugin", "add", "spec@bootgear"],
                                        ["codex", "plugin", "add", "review@bootgear"]])
        self.assertEqual(self.refreshes, [("codex", True)] * 3)
        result, _, stderr = self._run("--plugin", "engine")
        self.assertEqual(result, 0, stderr)
        self.assertEqual(len(self.installs), 2)
        self.assertEqual(len(self.refreshes), 4)

    def test_codex_does_not_count_disabled_or_uninstalled_peers(self) -> None:
        for field in ("enabled", "installed"):
            with self.subTest(field=field):
                self._plugin("engine", ("spec",))
                self._plugin("spec", enabled=field != "enabled", installed=field != "installed")
                self.pending = {"spec": ((), True)}
                self.installs.clear()
                result, _, stderr = self._run("--plugin", "engine")
                self.assertEqual(result, 0, stderr)
                self.assertEqual(self.installs, [["codex", "plugin", "add", "spec@bootgear"]])

    def test_successful_install_requires_an_enabled_installed_root(self) -> None:
        self._plugin("engine", ("spec",))
        self.pending = {"spec": ((), False)}
        result, stdout, stderr = self._run("--plugin", "engine")
        self.assertEqual(result, 2)
        self.assertIn("spec", stderr)
        self.assertIn("enabled", stderr)
        self.assertNotIn("Shared runtime ready", stdout)

    def test_claude_reports_all_missing_dependencies_without_installing(self) -> None:
        self.host = "claude"
        self._plugin("engine", ("spec", "review"))
        self._plugin("spec", enabled=False)
        result, stdout, stderr = self._run("--plugin", "engine")
        self.assertEqual(result, 2)
        self.assertIn("spec", stderr)
        self.assertIn("review", stderr)
        self.assertEqual(self.installs, [])
        self.assertNotIn("Shared runtime ready", stdout)

    def test_repository_siblings_do_not_prove_host_installation(self) -> None:
        self.host = "claude"
        self._plugin("engine", ("spec",))
        manifest = self.base / "source" / "plugins" / "spec" / ".claude-plugin" / "plugin.json"
        manifest.parent.mkdir(parents=True)
        manifest.write_text(json.dumps({"name": "spec"}))
        result, _, stderr = self._run("--plugin", "engine")
        self.assertEqual(result, 2)
        self.assertIn("spec", stderr)

    def test_missing_target_does_not_install_it(self) -> None:
        result, _, stderr = self._run("--plugin", "engine")
        self.assertEqual(result, 2)
        self.assertIn("engine", stderr)
        self.assertIn("enabled installed root", stderr)
        self.assertEqual(self.installs, [])

    def test_failed_install_can_be_retried(self) -> None:
        self._plugin("engine", ("spec",))
        result, _, stderr = self._run("--plugin", "engine", install_error="marketplace unavailable")
        self.assertEqual(result, 2)
        self.assertIn("marketplace unavailable", stderr)
        self.pending = {"spec": ((), True)}
        result, _, stderr = self._run("--plugin", "engine")
        self.assertEqual(result, 0, stderr)
        self.assertEqual(self.installs, [["codex", "plugin", "add", "spec@bootgear"]])

    def test_inventory_failure_after_install_stops_setup(self) -> None:
        self._plugin("engine", ("spec",))
        self.pending = {"spec": ((), True)}
        original = self._inventory

        def query(host: str, session: str | None, *, refresh: bool = False) -> tuple[object, bool]:
            if self.installs:
                raise RuntimeError("refreshed inventory permission denied")
            return original(host, session, refresh=refresh)

        with patch.object(self, "_inventory", side_effect=query):
            result, stdout, stderr = self._run("--plugin", "engine")
        self.assertEqual(result, 2)
        self.assertIn("refreshed inventory permission denied", stderr)
        self.assertNotIn("Shared runtime ready", stdout)

    def test_inventory_and_install_errors_keep_the_real_diagnostic(self) -> None:
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                self.host = host
                result, _, stderr = self._run("--plugin", "engine", inventory_error="inventory permission denied")
                self.assertEqual(result, 2)
                self.assertIn("inventory permission denied", stderr)
        self.host = "codex"
        self._plugin("engine", ("spec",))
        result, _, stderr = self._run("--plugin", "engine", install_error="marketplace unavailable")
        self.assertEqual(result, 2)
        self.assertIn("marketplace unavailable", stderr)
        self.assertIn("codex plugin add spec@bootgear", stderr)


class SharedSourceDiscoveryTests(unittest.TestCase):
    def test_checkout_root_and_hook_find_gear_without_a_mirror_folder(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gear-source-") as directory:
            root = Path(directory).resolve()
            cli = root / "plugins" / "cli"
            executable = cli / "bin" / "gear"
            executable.parent.mkdir(parents=True)
            executable.touch()
            provider = root / "plugins" / "engine"
            provider.mkdir()
            with patch.object(gear, "CLI_ROOT", cli):
                self.assertEqual(gear._checkout_root(), root)
            for host in ("claude", "codex"):
                with self.subTest(host=host), patch.object(hook_loader, "host_inventory") as inventory:
                    self.assertEqual(hook_loader._find_gear(provider, host, "engine", None), executable)
                    inventory.assert_not_called()
