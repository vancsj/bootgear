"""Prepare the shared runtime and declared plugin dependencies."""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import NoReturn

CLI_ROOT = Path(__file__).resolve().parents[2]
PYTHON_VERSION = "3.12"


class RuntimeNotReady(Exception):
    """Explicit setup is required before running a provider."""


class SetupParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.exit(2, f"example: {self.prog} --help\ncommands: setup, session-start\ngear: {message}\n")


def environment_path(cli_root: Path = CLI_ROOT) -> Path:
    digest = hashlib.sha256(PYTHON_VERSION.encode() + (cli_root / "uv.lock").read_bytes()).hexdigest()[:20]
    data = os.environ.get("XDG_DATA_HOME")
    root = Path(data).expanduser() / "bootgear" if data else Path.home() / ".bootgear"
    return root / "runtimes" / digest


def _python(environment: Path) -> Path:
    return environment / "bin" / "python"


def _ready(environment: Path) -> bool:
    return (environment / ".ready").is_file() and _python(environment).is_file()


def setup(cli_root: Path = CLI_ROOT) -> Path:
    environment = environment_path(cli_root)
    if _ready(environment):
        return environment
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeNotReady("uv is missing. Install uv, then run cli:setup.")
    environment.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with environment.with_suffix(".lock").open("a+b") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if _ready(environment):
            return environment
        found = subprocess.run(
            [uv, "python", "find", "--system", "--no-project", "--no-python-downloads", "--no-config", PYTHON_VERSION],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, check=False,
        )
        if found.returncode:
            raise RuntimeNotReady(found.stderr.strip() or "Python 3.12 is missing. Install it, then run cli:setup.")
        env = os.environ.copy()
        env["UV_PROJECT_ENVIRONMENT"] = str(environment)
        result = subprocess.run(
            [uv, "sync", "--locked", "--no-install-project", "--no-config", "--project", str(cli_root),
             "--python", found.stdout.strip()],
            env=env, stdin=subprocess.DEVNULL, check=False,
        )
        if result.returncode:
            raise RuntimeNotReady(f"uv setup failed with exit code {result.returncode}; retry cli:setup.")
        temporary = environment / ".ready.tmp"
        temporary.write_text("ready\n", encoding="utf-8")
        temporary.replace(environment / ".ready")
    return environment


@contextlib.contextmanager
def prepared(cli_root: Path = CLI_ROOT) -> Iterator[Path]:
    environment = environment_path(cli_root)
    try:
        lock = environment.with_suffix(".lock").open("rb")
    except FileNotFoundError as exc:
        raise RuntimeNotReady("Shared runtime is missing. Run cli:setup, then retry.") from exc
    with lock:
        fcntl.flock(lock, fcntl.LOCK_SH)
        if not _ready(environment):
            raise RuntimeNotReady("Shared runtime is not ready. Run cli:setup, then retry.")
        yield _python(environment)


def main() -> int:
    from bootgear_cli import clikit, dependencies

    program = clikit.current_program("cli", "setup")
    parser = SetupParser(prog=program, description=__doc__,
                         epilog=f"example: {program} --plugin engine",
                         formatter_class=argparse.RawDescriptionHelpFormatter)
    flags = parser.add_mutually_exclusive_group()
    flags.add_argument("--json", action="store_true")
    flags.add_argument("--prose", action="store_true")
    parser.add_argument("--plugin", help="installed provider name from gear list; prepare its declared sibling dependencies")
    args = parser.parse_args()
    mode = clikit.resolve_mode(args.json, args.prose)
    try:
        environment = setup()
        plugins = dependencies.prepare(args.plugin) if args.plugin else ()
    except (OSError, RuntimeNotReady, dependencies.DependencySetupError) as exc:
        error = json.dumps({"error": str(exc)}) if mode == "json" else f"gear: {exc}"
        print(error, file=sys.stderr)
        return 2
    result: dict[str, object] = {"runtime": str(environment)}
    prose = f"Shared runtime ready: {environment}"
    if args.plugin:
        result["plugins"] = list(plugins)
        prose += f"\nRequired plugin installations verified: {', '.join(plugins)}"
    next_step = ("Return to the calling skill." if args.plugin else
                 "Use cli:gear to get the Gear path, then run a registered command.")
    if clikit.host() == "codex":
        result["activation"] = "unverified"
        prose += "\nPlugin activation is unverified. Setup did not check hook trust or session loading."
        next_step = (
            "Ask the user to review and trust new or changed plugin hooks in /hooks. "
            "Restart Codex first if the new hooks are not listed. "
            "Then ask them to start a fresh Codex session before continuing the workflow."
        )
    clikit.emit(mode, result, prose, next=next_step)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
