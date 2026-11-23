from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bootgear_cli import gear, hook_loader, native_setup


class DependencySetupTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="bootgear setup ")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()

    def _catalog(self, directory: str, versions: dict[str, tuple[str, list[str]]]) -> Path:
        root = self.base / directory
        entries = []
        for name, (version, dependencies) in versions.items():
            manifest = root / name / ".claude-plugin/plugin.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(json.dumps({"name": name, "version": version, "dependencies": dependencies}))
            entries.append({"name": name, "source": f"./{name}"})
        for path in native_setup.CATALOGS.values():
            index = root / path
            index.parent.mkdir(parents=True, exist_ok=True)
            index.write_text(json.dumps({"name": "bootgear", "plugins": entries}))
        return root

    def test_registered_catalog_controls_choices_versions_and_dependencies(self) -> None:
        downloaded = self._catalog("downloaded", {"engine": ("2.0", ["new"]), "new": ("2.0", [])})
        registered = self._catalog("registered", {"engine": ("1.0", ["cli"]), "cli": ("1.0", [])})
        records = [{"name": name, "root": registered / name, "enabled": True} for name in ("engine", "cli")]
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                app = native_setup.Setup(host, self.base, downloaded, False)
                with (patch.object(app, "registered", return_value=native_setup.Catalog(registered, False)),
                      patch.object(app, "_records", return_value=records), patch.object(app, "_update") as update):
                    self.assertEqual([item["name"] for item in app.choices()], ["engine", "cli"])
                    _, ready, _ = app.packages("install", ("engine",))
                    self.assertEqual(ready, {"engine", "cli"})
                    update.assert_not_called()

    def test_unknown_targets_are_grouped_before_native_writes(self) -> None:
        checkout = self._catalog("checkout", {"cli": ("1.0", [])})
        app = native_setup.Setup("codex", self.base, checkout, True)
        with patch.object(app, "registered", return_value=None), patch.object(app, "_native") as native:
            with self.assertRaisesRegex(native_setup.SetupError, "absent, also-absent"):
                app.packages("install", ("absent", "also-absent"))
            native.assert_not_called()

    def test_registered_source_mismatch_stops_before_package_writes(self) -> None:
        checkout = self._catalog("checkout", {"cli": ("1.0", [])})
        home = self.base / "claude profile"
        home.mkdir()
        with patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(home)}):
            app = native_setup.Setup("claude", self.base, checkout, True)
        response = [{"name": "bootgear", "source": "directory", "path": str(self.base / "other"),
                     "installLocation": str(self.base / "other")}]
        with patch.object(app, "_native", return_value=response) as native:
            with self.assertRaisesRegex(native_setup.SetupError, "marketplace points"):
                app.packages("install", ("cli",))
            native.assert_called_once_with("marketplace", "list")

    def test_installed_cli_can_use_a_verified_local_registration(self) -> None:
        checkout = self._catalog("checkout", {"cli": ("1.0", [])})
        records = [{"name": "cli", "root": checkout / "cli", "enabled": True}]
        sources = {
            "claude": [{"name": "bootgear", "source": "directory", "path": str(checkout),
                        "installLocation": str(checkout)}],
            "codex": {"marketplaces": [{"name": "bootgear", "root": str(checkout),
                                        "marketplaceSource": {"sourceType": "local", "source": str(checkout)}}]},
        }
        for host, response in sources.items():
            with self.subTest(host=host):
                app = native_setup.Setup(host, self.base, None, False)
                app.profile = self.base
                with (patch.object(app, "_native", return_value=response),
                      patch.object(app, "_records", return_value=records),
                      patch.object(app, "_update") as update):
                    for operation in ("install", "repair", "configure"):
                        with self.subTest(operation=operation):
                            self.assertEqual(app.packages(operation, ("cli",))[1], {"cli"})
                    update.assert_not_called()

    def test_setup_keeps_the_native_caller_and_isolates_python_imports(self) -> None:
        plugin = gear._load_plugin(gear.CLI_ROOT / "gear.toml", repository_root=gear.DEFAULT_ROOT)
        with (patch.dict(os.environ, {"PYTHONPATH": "."}),
              patch.object(gear, "_invoke", return_value=0) as invoke):
            gear._run(plugin, plugin.commands["setup"], context={"COMMAND": "setup"}, caller_cwd=self.base)
        command = invoke.call_args.args[0]
        env = invoke.call_args.kwargs["env"]
        self.assertEqual(command[1:3], ("-P", "-m"))
        self.assertEqual(invoke.call_args.kwargs["cwd"], self.base)
        self.assertEqual(env["GEAR_CALLER_CWD"], str(self.base))
        self.assertEqual(env["PYTHONPATH"], str(gear.CLI_ROOT / "src"))

    def test_full_repair_can_prepare_runtime_with_cli_disabled(self) -> None:
        root = self._catalog("registered", {"converge": ("1.0", ["cli"]), "cli": ("1.0", [])})
        records = [{"name": "converge", "root": root / "converge", "enabled": True},
                   {"name": "cli", "root": root / "cli", "enabled": False}]
        for host in ("claude", "codex"):
            with self.subTest(host=host):
                app = native_setup.Setup(host, self.base, root, True)
                app.profile = self.base / "profile"
                catalog = native_setup.Catalog(root, True)
                with (patch.object(app, "registered", return_value=catalog),
                      patch.object(app, "_records", return_value=records),
                      patch.object(app, "_refresh", return_value=catalog),
                      patch.object(app, "_update") as update):
                    installed, packages, _ = app.packages("repair", ())
                    self.assertEqual(packages, {"cli", "converge"})
                    self.assertFalse(installed["cli"]["enabled"])
                    update.assert_not_called()

    def test_existing_defaults_keep_bytes_and_mode(self) -> None:
        path = self.base / "converge.yaml"
        path.write_bytes(b"custom: true\n")
        path.chmod(0o640)
        created = native_setup.seed_defaults(self.base, {"engine", "converge"})
        self.assertEqual({Path(item).name for item in created}, {"converge-seats.yaml", "debate-parties.yaml"})
        self.assertEqual(path.read_bytes(), b"custom: true\n")
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o640)

    def test_checkout_root_and_hook_find_shared_gear(self) -> None:
        cli = self.base / "plugins" / "cli"
        executable = cli / "bin" / "gear"
        executable.parent.mkdir(parents=True)
        executable.touch()
        provider = self.base / "plugins" / "engine"
        provider.mkdir()
        with patch.object(gear, "CLI_ROOT", cli):
            self.assertEqual(gear._checkout_root(), self.base)
        for host in ("claude", "codex"):
            self.assertEqual(hook_loader._find_gear(provider, host, "engine", [], self.base), executable)
