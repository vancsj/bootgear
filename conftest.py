from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent / "plugins/cli/src"))

from bootgear_cli import runtime


@pytest.fixture(scope="session")
def shared_runtimes() -> Path:
    return runtime.environment_path().parent.resolve()


@pytest.fixture(autouse=True)
def isolated_host_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shared_runtimes: Path) -> None:
    data = tmp_path / "data"
    (data / "bootgear").mkdir(parents=True)
    (data / "bootgear/runtimes").symlink_to(shared_runtimes, target_is_directory=True)
    monkeypatch.setenv("XDG_DATA_HOME", str(data))
