"""Run shared remedy cases against the bundled Converge source."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def test_shared_implementation_difficulty_cases() -> None:
    root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "plugins/converge/tests/test_effort.py",
         "plugins/converge/tests/test_config.py", "-k", "implementation", "-q"],
        cwd=root, env={**os.environ, "CONVERGE_SRC": str(root / "codex-plugins/engine/src")},
        capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
