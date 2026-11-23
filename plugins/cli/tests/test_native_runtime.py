from __future__ import annotations

import os
import signal
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bootgear_cli import native_process, runtime


class NativeRuntimeTests(unittest.TestCase):
    def test_runtime_key_uses_resolved_interpreter_and_lockfile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lockfile = root / "uv.lock"
            lockfile.write_text("lock")
            first = root / "python-3.12.15"
            first.touch()
            second = root / "python-3.12.16"
            second.touch()
            alias = root / "python"
            alias.symlink_to(first)
            with patch.dict(os.environ, {"XDG_DATA_HOME": str(root / "data")}):
                path = runtime.environment_path(root, interpreter=first)
                self.assertEqual(path, runtime.environment_path(root, interpreter=alias))
                self.assertNotEqual(path, runtime.environment_path(root, interpreter=second))
                lockfile.write_text("new lock")
                self.assertNotEqual(path, runtime.environment_path(root, interpreter=first))

    def test_routine_inventory_miss_does_not_query_native_plugins(self) -> None:
        from bootgear_cli import hook_loader

        with (tempfile.TemporaryDirectory() as directory,
              patch.dict(os.environ, {"XDG_DATA_HOME": directory}),
              patch.object(hook_loader, "_codex_inventory") as query):
            with self.assertRaisesRegex(RuntimeError, "fresh.*session"):
                hook_loader.host_inventory("codex", "missing-inventory")
            query.assert_not_called()

    def test_sync_uses_the_managed_installation_key_and_isolated_probe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "uv/python/cpython-3.12.16-macos-aarch64-none/bin/python3.12"
            with (patch.dict(os.environ, {"XDG_DATA_HOME": directory, "BOOTGEAR_SETUP_UV": "uv"}),
                  patch.object(runtime, "interpreter_path", return_value=base),
                  patch.object(runtime, "run", side_effect=["", str(base)]) as run):
                environment = runtime.environment_path()
                environment.mkdir(parents=True)
                self.assertEqual(runtime.setup(), environment)
            sync, verify = run.call_args_list
            self.assertEqual(sync.args[0][-2:], ["--python", base.parent.parent.name])
            self.assertEqual(sync.kwargs["env"]["UV_PYTHON_INSTALL_DIR"], str(base.parents[2]))
            self.assertEqual(verify.args[0][1:3], ["-I", "-c"])

    def test_interruption_stops_the_setup_child_group(self) -> None:
        with (patch.object(native_process.subprocess, "Popen") as popen,
              patch.object(native_process.os, "killpg") as kill_group):
            child = popen.return_value.__enter__.return_value
            child.pid = 101
            child.communicate.side_effect = [KeyboardInterrupt(), ("", "")]
            with self.assertRaises(KeyboardInterrupt):
                native_process.run(["uv", "sync"])
            kill_group.assert_called_once_with(child.pid, signal.SIGKILL)
            self.assertEqual(child.communicate.call_count, 2)

    def test_interrupted_readiness_write_leaves_no_ready_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / "uv/python/cpython-3.12.16-macos-aarch64-none/bin/python3.12"
            with (patch.dict(os.environ, {"XDG_DATA_HOME": directory, "BOOTGEAR_SETUP_UV": "uv"}),
                  patch.object(runtime, "interpreter_path", return_value=base),
                  patch.object(runtime, "run", side_effect=["", str(base)])):
                environment = runtime.environment_path()
                environment.mkdir(parents=True)

                def interrupted_write(path: Path, *_args, **_kwargs) -> int:
                    path.touch()
                    raise OSError("write was interrupted")

                with (patch.object(Path, "write_text", interrupted_write),
                      self.assertRaisesRegex(OSError, "write was interrupted")):
                    runtime.setup()
            self.assertEqual(list(environment.iterdir()), [])
