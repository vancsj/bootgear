import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from bootgear_cli import runtime
from codex_contract_test_support import TASK, CodexPackageContractTestCase, _roles
from gear_commands import command as gear_command


class CodexPackageContractTest(CodexPackageContractTestCase):
    def test_advisor_startup_choice_validates_and_round_trips(self):
        for startup in ("direct", "deferred"):
            with self.subTest(startup=startup), tempfile.TemporaryDirectory() as tmp:
                settings = _roles("refuter").replace("  startup: direct\n", "") + f"  startup: {startup}\n"
                if startup == "deferred":
                    settings += "  launcher: start-advisor\n"
                settings += "converge_seats: {r2: advisor}\ndebate_party_config: {}\n"
                self.assertEqual(self._validate(settings).returncode, 0)
                root = Path(tmp)
                path = root / "settlement.yaml"
                path.write_text(self._settlement(settings, task_folder=root / "task"))
                init = subprocess.run([*TASK, "session", "init", "startup-run", "--dir", tmp,
                                       "--settlement-file", str(path)],
                                      capture_output=True, text=True, check=False)
                self.assertEqual(init.returncode, 0, init.stderr)
                read = subprocess.run([*TASK, "session", "read", "startup-run", "--dir", tmp,
                                       "--section", "settlement", "--json"],
                                      capture_output=True, text=True, check=True)
                self.assertIn(f"startup: {startup}", read.stdout)
                if startup == "deferred":
                    self.assertIn("launcher: start-advisor", read.stdout)

    def test_advisor_startup_requires_a_choice_and_a_deferred_launcher(self):
        for options, field in (("", "startup"), ("  startup: later\n", "startup"),
                               ("  startup: deferred\n", "launcher")):
            with self.subTest(options=options):
                settings = (_roles("refuter").replace("  startup: direct\n", "") + options
                            + "converge_seats: {r2: advisor}\ndebate_party_config: {}\n")
                result = self._validate(settings)
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn(f"advisor_roles.{field}", result.stderr)

    def test_shared_host_selects_user_config_and_explicit_path_wins(self):
        with tempfile.TemporaryDirectory(prefix="engine-host-config-") as tmp:
            root = Path(tmp)
            for host in ("claude", "codex"):
                folder = root / f".{host}"
                folder.mkdir()
                (folder / "profile.yaml").write_text(f"source: {host}\n")
            explicit = root / "explicit.yaml"
            explicit.write_text("source: explicit\n")
            data = root / "data"
            runtimes = data / "bootgear" / "runtimes"
            runtimes.parent.mkdir(parents=True)
            (runtimes.parent / "python").write_text(f"{sys.executable}\n")
            runtimes.symlink_to(runtime.environment_path().parent, target_is_directory=True)
            for host in ("claude", "codex"):
                for override in (False, True):
                    with self.subTest(host=host, override=override):
                        args = [*gear_command("engine", "task", host), "config", "resolve", "--name", "profile",
                                "--project-root", str(root), "--json"]
                        if override:
                            args.extend(("--user-config", str(explicit)))
                        result = subprocess.run(
                            args, env={**os.environ, "HOME": str(root), "XDG_DATA_HOME": str(data),
                                       "BOOTGEAR_HOST": host},
                            capture_output=True, text=True, check=True,
                        )
                        self.assertEqual(json.loads(result.stdout)["effective"]["source"],
                                         "explicit" if override else host)


if __name__ == "__main__":
    unittest.main()
