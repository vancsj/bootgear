from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from .gear_test_support import GEAR


class SetupBootstrapTests(unittest.TestCase):
    def test_missing_uv_stops_before_python(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gear setup ") as directory:
            home = Path(directory)
            bin_dir = home / "bin"
            bin_dir.mkdir()
            (bin_dir / "bash").symlink_to("/bin/bash")
            python = bin_dir / "python3"
            python.write_text("#!/bin/sh\nprintf 'unexpected Python start\\n' >&2\nexit 99\n")
            python.chmod(0o755)

            result = subprocess.run(
                [str(GEAR), "--host", "codex", "cli", "setup"],
                cwd=home, env={**os.environ, "HOME": str(home), "PATH": str(bin_dir),
                               "XDG_DATA_HOME": str(home / "data")},
                capture_output=True, text=True, check=False, timeout=15,
            )

            self.assertEqual(result.returncode, 2, result.stderr)
            self.assertIn("uv is missing", result.stderr)
            self.assertIn("Claude Code or Codex", result.stderr)
            self.assertIn("retry", result.stderr)
            self.assertNotIn("unexpected Python start", result.stderr)

    def test_uv_provisions_python_before_backend_without_python3_on_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gear setup ") as directory:
            home = Path(directory)
            bin_dir = home / "bin"
            bin_dir.mkdir()
            (bin_dir / "bash").symlink_to("/bin/bash")
            wrapper = bin_dir / "gear"
            shutil.copy2(GEAR, wrapper)
            shutil.copy2(GEAR.with_name("setup-deadline.sh"), bin_dir)
            marker = home / "installed"
            managed_python = home / "managed python"
            managed_python.symlink_to(sys.executable)
            uv = bin_dir / "uv"
            uv.write_text(
                '#!/bin/sh\ncase "$1 $2" in\n'
                '    "python find") [ -f "$INSTALLED" ] && printf "%s\\n" "$MANAGED_PYTHON" ;;\n'
                '    "python install") printf "installed\\n" > "$INSTALLED" ;;\n'
                '    *) exit 98 ;;\nesac\n'
            )
            uv.chmod(0o755)
            (home / "bootstrap.py").write_text(
                "import os, sys\nfrom pathlib import Path\n"
                "assert Path(os.environ['INSTALLED']).exists()\n"
                "print(sys.executable)\n"
            )

            result = subprocess.run(
                [str(wrapper), "cli", "setup"], cwd=home,
                env={**os.environ, "HOME": str(home), "PATH": str(bin_dir),
                     "XDG_DATA_HOME": str(home / "data"), "INSTALLED": str(marker),
                     "MANAGED_PYTHON": str(managed_python)},
                capture_output=True, text=True, check=False, timeout=15,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(Path(result.stdout.strip()), Path(sys.executable).resolve())

    def test_setup_requires_absolute_uv_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            tools = home / "tools"
            tools.mkdir()
            (tools / "uv").symlink_to("/usr/bin/true")
            for host in ("claude", "codex"):
                with self.subTest(host=host):
                    result = subprocess.run(
                        [str(GEAR), "--host", host, "cli", "setup"], cwd=home,
                        env={**os.environ, "BASH_ENV": "", "PATH": "tools:/bin"}, capture_output=True,
                        text=True, check=False, timeout=15,
                    )
                    self.assertEqual(result.returncode, 2, result.stderr)
                    self.assertIn("absolute directory", result.stderr)

    def test_gear_launches_recorded_interpreter_without_python_on_path(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gear setup ") as directory:
            home = Path(directory)
            data = home / "data"
            record = data / "bootgear" / "python"
            record.parent.mkdir(parents=True)
            record.write_text(f"{Path(sys.executable).resolve()}\n")
            (home / "bash").symlink_to("/bin/bash")

            result = subprocess.run(
                [str(GEAR), "--help"], cwd=home,
                env={**os.environ, "HOME": str(home), "PATH": str(home), "XDG_DATA_HOME": str(data)},
                capture_output=True, text=True, check=False, timeout=15,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("usage: gear", result.stdout)
