from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cli import gear

GEAR = Path(__file__).parents[1] / "gear.py"


REPO = Path(__file__).parents[2]


class RepoRegistrationTests(unittest.TestCase):
    def test_repo_registers_converge_and_advisor(self) -> None:
        plugins = gear.discover(REPO)

        self.assertEqual(set(plugins["converge"].commands), {"converge"})
        self.assertEqual(set(plugins["advisor"].commands), {"channel"})

    def test_routed_child_follows_caller_stdout(self) -> None:
        # gear.py sets no output mode: both sinks default to prose.
        machine = REPO / "plugins" / "engine" / "state-machines" / "pr-review.yaml"
        argv = [sys.executable, str(GEAR), "engine", "task", "state", "validate", str(machine)]
        env = {k: v for k, v in os.environ.items() if k not in ("BOOTGEAR_OUTPUT", "VIRTUAL_ENV")}

        piped = subprocess.run(argv, capture_output=True, text=True, env=env, check=True)
        self.assertEqual(piped.stdout.strip(), f"{machine}: ok")

        json_piped = subprocess.run([*argv, "--json"], capture_output=True, text=True,
                                    env=env, check=True)
        self.assertEqual(json.loads(json_piped.stdout)["ok"], True)

        with tempfile.TemporaryFile("w+") as out:
            subprocess.run(argv, stdout=out, text=True, env=env, check=True)
            out.seek(0)
            self.assertEqual(out.read().strip(), f"{machine}: ok")


class GearTests(unittest.TestCase):
    def make_plugin(self, root: Path, name: str, registration: str, scripts: dict[str, str]) -> None:
        plugin = root / "plugins" / name
        plugin.mkdir(parents=True)
        (plugin / "gear.toml").write_text(registration)
        for path, text in scripts.items():
            target = plugin / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)

    def test_discovers_commands_and_reminders(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_plugin(root, "demo", """
[plugin]
name = "demo"

[commands.probe]
exec = ["python3", "probe.py"]

[reminders.after_compaction]
exec = ["python3", "remind.py"]
""", {"probe.py": "", "remind.py": ""})

            plugins = gear.discover(root)

            self.assertEqual(set(plugins), {"demo"})
            self.assertEqual(set(plugins["demo"].commands), {"probe"})
            self.assertEqual(plugins["demo"].reminders[0].event, "after_compaction")

    def test_routes_arguments_and_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_plugin(root, "demo", f"""
[plugin]
name = "demo"

[commands.probe]
exec = [{json.dumps(sys.executable)}, "probe.py"]
""", {"probe.py": """
import json
import os
import sys

print(json.dumps({
    "args": sys.argv[1:],
    "plugin": os.environ["GEAR_PLUGIN"],
    "command": os.environ["GEAR_COMMAND"],
                "plugin_root": os.environ["GEAR_PLUGIN_ROOT"],
                "root": os.environ["GEAR_ROOT"],
                "caller_cwd": os.environ["GEAR_CALLER_CWD"],
            }))
"""})

            result = subprocess.run(
                [sys.executable, str(GEAR), "--root", str(root), "demo", "probe", "one", "two"],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), {
                "args": ["one", "two"],
                "plugin": "demo",
                "command": "probe",
                "plugin_root": str((root / "plugins" / "demo").resolve()),
                "root": str(root.resolve()),
                "caller_cwd": str(Path.cwd().resolve()),
            })

    def test_routes_event_and_preserves_reminder_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_plugin(root, "demo", f"""
[plugin]
name = "demo"

[reminders.after_compaction]
exec = [{json.dumps(sys.executable)}, "remind.py"]
""", {"remind.py": "print('remember me')\n"})

            result = subprocess.run(
                [sys.executable, str(GEAR), "--root", str(root), "event", "after_compaction"],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "remember me\n")

    def test_rejects_duplicate_plugin_names(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("one", "two"):
                self.make_plugin(root, name, """
[plugin]
name = "same"
""", {})

            with self.assertRaises(gear.GearError):
                gear.discover(root)

    def test_retries_missing_route_after_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_plugin(root, "demo", """
[plugin]
name = "demo"

[commands.probe]
exec = ["python3", "probe.py"]
""", {"probe.py": ""})
            refreshes = []

            def refresh() -> dict[str, gear.Plugin]:
                refreshes.append(True)
                return gear.discover(root)

            result = gear.route_command({}, "demo", "probe", [], refresh=refresh)

            self.assertEqual(result, 0)
            self.assertEqual(refreshes, [True])

    def test_route_miss_reconciles_only_once(self) -> None:
        refreshes = []

        def refresh() -> dict[str, gear.Plugin]:
            refreshes.append(True)
            return {}

        with self.assertRaises(gear.GearError):
            gear.route_command({}, "missing", "probe", [], refresh=refresh)

        self.assertEqual(refreshes, [True])

    def test_reconcile_adds_host_plugin_and_prefers_local_registration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_plugin(root, "local", """
[plugin]
name = "same"
""", {})
            installed = root / "installed" / "same"
            installed.mkdir(parents=True)
            (installed / "gear.toml").write_text("""
[plugin]
name = "same"
""")

            with patch.object(gear, "_host_plugin_roots", return_value=((installed,), ())):
                report = gear.reconcile(root)

            self.assertEqual(report.warnings, ())
            self.assertEqual(report.plugins["same"].root, (root / "plugins" / "local").resolve())


if __name__ == "__main__":
    unittest.main()
