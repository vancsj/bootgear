from __future__ import annotations

import shlex
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "plugins/cli/src"))

from bootgear_cli import runtime


@pytest.fixture(scope="session")
def shared_runtimes(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("gear-runtimes")
    environment = root / runtime.environment_path().name
    (environment / "bin").mkdir(parents=True)
    interpreter = environment / "bin/python"
    interpreter.write_text(f"#!/bin/sh\nexec {shlex.quote(sys.executable)} \"$@\"\n")
    interpreter.chmod(0o755)
    (environment / ".ready").touch()
    environment.with_suffix(".lock").touch()
    return root


@pytest.fixture(autouse=True)
def isolated_host_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shared_runtimes: Path) -> None:
    data = tmp_path / "data"
    (data / "bootgear").mkdir(parents=True)
    (data / "bootgear/python").write_text(f"{sys.executable}\n")
    (data / "bootgear/runtimes").symlink_to(shared_runtimes, target_is_directory=True)
    monkeypatch.setenv("XDG_DATA_HOME", str(data))
