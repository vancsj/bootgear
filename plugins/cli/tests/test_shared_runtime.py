from __future__ import annotations

import fcntl
import json
import os
import tempfile
from pathlib import Path
from textwrap import dedent
from unittest.mock import patch

from bootgear_cli import runtime

from .cli_integration_test_support import GearIntegrationTestsCase
from .host_fixture import link_shared_runtime


class SharedRuntimeTests(GearIntegrationTestsCase):
    def setUp(self) -> None:
        super().setUp()
        link_shared_runtime(self.data)

    def test_sdk_routes_sibling_commands_in_the_selected_root_and_caller(self) -> None:
        roots: dict[str, Path] = {}
        callers: dict[str, Path] = {}
        for host in ("claude", "codex"):
            root = self.base / f"sdk-root-{host}"
            base = root / "plugins"
            provider = base / "external-demo"
            sibling = base / "external-sibling"
            provider.mkdir(parents=True)
            sibling.mkdir(parents=True)
            (provider / "gear.toml").write_text(
                '[plugin]\nname = "external-demo"\n\n'
                '[commands.probe]\nexec = ["python3", "probe.py"]\n',
                encoding="utf-8",
            )
            (sibling / "gear.toml").write_text(
                '[plugin]\nname = "external-sibling"\n\n'
                '[commands.probe-only]\nexec = ["python3", "probe.py"]\n',
                encoding="utf-8",
            )
            (provider / "probe.py").write_text(dedent("""\
                import json
                import subprocess
                from bootgear_cli.gear import resolve_command

                route = resolve_command("probe-only")
                if route is None:
                    print(json.dumps({"route": None, "error": "SDK could not resolve the sibling route"}))
                else:
                    result = subprocess.run(route + ["from-provider"], capture_output=True,
                                            text=True, check=False)
                    print(json.dumps({"route": route, "returncode": result.returncode,
                                      "stdout": result.stdout, "stderr": result.stderr}))
            """), encoding="utf-8")
            (sibling / "probe.py").write_text(dedent("""\
                import json
                import os
                import sys
                from bootgear_cli.clikit import caller_path

                print(json.dumps({
                    "plugin": os.environ["GEAR_PLUGIN"],
                    "command": os.environ["GEAR_COMMAND"],
                    "root": os.environ["GEAR_ROOT"],
                    "caller_cwd": os.environ["GEAR_CALLER_CWD"],
                    "caller_path": str(caller_path("relative.txt")),
                    "args": sys.argv[1:],
                }))
            """), encoding="utf-8")
            caller = self.base / f"sdk-caller-{host}"
            caller.mkdir()
            (caller / "relative.txt").write_text("caller", encoding="utf-8")
            roots[host] = root
            callers[host] = caller

        for host in ("claude", "codex"):
            with self.subTest(host=host):
                result = self._run(
                    host, "--root", str(roots[host]), "external-demo", "probe", cwd=callers[host],
                )

                self.assertEqual(result.returncode, 0, result.stderr)
                data = json.loads(result.stdout)
                self.assertIsNotNone(data["route"], data.get("error"))
                self.assertIn("--root", data["route"])
                self.assertIn(str(roots[host].resolve()), data["route"])
                self.assertEqual(data["returncode"], 0, data["stderr"])
                sibling = json.loads(data["stdout"])
                self.assertEqual(sibling["plugin"], "external-sibling")
                self.assertEqual(sibling["command"], "probe-only")
                self.assertEqual(sibling["root"], str(roots[host].resolve()))
                self.assertEqual(sibling["caller_cwd"], str(callers[host].resolve()))
                self.assertEqual(sibling["caller_path"], str((callers[host] / "relative.txt").resolve()))
                self.assertEqual(sibling["args"], ["from-provider"])

    def test_provider_refuses_active_repair_without_waiting(self) -> None:
        with tempfile.TemporaryDirectory() as data, patch.dict(os.environ, {"XDG_DATA_HOME": data}):
            environment = runtime.environment_path()
            environment.parent.mkdir(parents=True)
            with environment.with_suffix(".lock").open("a+b") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                with self.assertRaisesRegex(runtime.RuntimeNotReady, "setup is in progress"), runtime.prepared():
                    self.fail("provider started during repair")

    def test_repair_keeps_ready_marker_when_a_provider_holds_the_lock(self) -> None:
        with tempfile.TemporaryDirectory() as data, patch.dict(os.environ, {
            "XDG_DATA_HOME": data, "BOOTGEAR_SETUP_UV": "uv",
        }):
            environment = runtime.environment_path()
            (environment / "bin").mkdir(parents=True)
            (environment / "bin/python").touch()
            marker = environment / ".ready"
            marker.touch()
            with environment.with_suffix(".lock").open("a+b") as lock:
                fcntl.flock(lock, fcntl.LOCK_SH)
                with patch.object(runtime, "run") as run:
                    with self.assertRaisesRegex(runtime.RuntimeNotReady, "using the runtime"):
                        runtime.setup(repair=True)
                    run.assert_not_called()
                self.assertTrue(marker.exists())
