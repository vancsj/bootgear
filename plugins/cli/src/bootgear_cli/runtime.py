"""Prepare the shared runtime and declared plugin dependencies."""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import os
import shutil
import sys
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import NoReturn

from bootgear_cli.native_process import SetupError, run

CLI_ROOT = Path(__file__).resolve().parents[2]


class RuntimeNotReady(Exception):
    """Explicit setup is required before running a provider."""


class SetupParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.exit(2, f"example: {self.prog} --help\ncommands: setup, session-start\ngear: {message}\n")


def data_root() -> Path:
    data = os.environ.get("XDG_DATA_HOME")
    return Path(data).expanduser() / "bootgear" if data else Path.home() / ".bootgear"


def interpreter_path() -> Path:
    return Path(sys.executable).resolve()


def environment_path(cli_root: Path = CLI_ROOT, *, interpreter: Path | None = None) -> Path:
    base = interpreter.resolve() if interpreter else interpreter_path()
    digest = hashlib.sha256()
    digest.update(os.fsencode(base))
    digest.update(b"\0")
    digest.update((cli_root / "uv.lock").read_bytes())
    return data_root() / "runtimes" / digest.hexdigest()[:20]


def record_interpreter() -> Path:
    base = interpreter_path()
    directory = data_root()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(f"{base}\n")
            stream.close()
            temporary.replace(directory / "python")
        finally:
            temporary.unlink(missing_ok=True)
    return base


@contextlib.contextmanager
def setup_lock() -> Iterator[None]:
    root = data_root()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (root / "setup.lock").open("a+b") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeNotReady("Another setup is running. Retry when it finishes.") from exc
        yield


def _python(environment: Path) -> Path:
    return environment / "bin" / "python"


def _ready(environment: Path) -> bool:
    return (environment / ".ready").is_file() and _python(environment).is_file()


def setup(cli_root: Path = CLI_ROOT, *, repair: bool = False) -> Path:
    environment = environment_path(cli_root)
    uv = os.environ.get("BOOTGEAR_SETUP_UV") or shutil.which("uv")
    if uv is None:
        raise RuntimeNotReady("uv is missing. Claude Code or Codex can help install uv. Then retry setup.")
    environment.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with environment.with_suffix(".lock").open("a+b") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            if not repair and _ready(environment):
                return environment
            raise RuntimeNotReady("A Gear command is using the runtime. Retry when it finishes.") from exc
        if _ready(environment) and not repair:
            return environment
        marker = environment / ".ready"
        marker.unlink(missing_ok=True)
        base_python = interpreter_path()
        installation = base_python.parent.parent
        env = {**os.environ, "UV_PROJECT_ENVIRONMENT": str(environment),
               "UV_PYTHON_INSTALL_DIR": str(installation.parent)}
        env.pop("VIRTUAL_ENV", None)
        command = [
            uv, "sync", "--locked", "--no-install-project", "--no-config", "--managed-python",
            "--no-python-downloads", "--project", str(cli_root), "--python", installation.name,
        ]
        if repair:
            command.append("--reinstall")
        try:
            run(command, env=env)
            base = run([
                str(_python(environment)), "-I", "-c",
                "import sys, yaml; print(sys._base_executable)",
            ], env=env).strip()
        except SetupError as exc:
            raise RuntimeNotReady(str(exc)) from exc
        if Path(base) != base_python:
            raise RuntimeNotReady("The provider runtime did not use the selected managed Python. Retry Repair.")
        pending = environment / ".ready.pending"
        try:
            pending.write_text("ready\n", encoding="utf-8")
            pending.replace(marker)
        finally:
            pending.unlink(missing_ok=True)
    return environment


@contextlib.contextmanager
def prepared(cli_root: Path = CLI_ROOT) -> Iterator[Path]:
    try:
        environment = environment_path(cli_root)
        lock = environment.with_suffix(".lock").open("rb")
    except FileNotFoundError as exc:
        raise RuntimeNotReady("Shared runtime is missing. Run cli:setup, then retry.") from exc
    with lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeNotReady("Shared runtime setup is in progress. Retry when it finishes.") from exc
        if not _ready(environment):
            raise RuntimeNotReady("Shared runtime is not ready. Run cli:setup, then retry.")
        yield _python(environment)
