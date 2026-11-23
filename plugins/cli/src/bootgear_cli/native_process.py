"""Run an explicit setup command with a deadline."""

from __future__ import annotations

import os
import signal
import subprocess
from contextlib import suppress


class SetupError(Exception):
    """Setup could not complete an operation."""


def run(command: list[str], *, cwd=None, env=None, timeout: int = 120) -> str:
    label = " ".join(command)
    try:
        with subprocess.Popen(
            command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True,
        ) as process:
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except (subprocess.TimeoutExpired, KeyboardInterrupt, SystemExit) as exc:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                process.communicate()
                if isinstance(exc, subprocess.TimeoutExpired):
                    raise SetupError(f"{label} timed out after {timeout} seconds. Retry setup.") from exc
                raise
    except OSError as exc:
        raise SetupError(f"Could not run {label}: {exc}. Retry setup.") from exc
    if process.returncode:
        detail = stderr.strip() or stdout.strip() or f"exit {process.returncode}"
        raise SetupError(f"{label} failed: {detail}. Retry setup.")
    return stdout
