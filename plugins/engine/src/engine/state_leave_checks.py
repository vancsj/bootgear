"""Resolve and execute guarded state-transition programs."""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import sys

from bootgear_cli.clikit import ENV_MODE
from bootgear_cli.gear import resolve_command

from engine.state_machine import LEAVE_CHECK_PLACEHOLDER_RE

LEAVE_ARG_RE = re.compile(r"\A(?P<name>[a-z_]+)=(?P<value>.*)\Z", re.DOTALL)
LEAVE_CHECK_TIMEOUT_ENV = "ENGINE_LEAVE_CHECK_TIMEOUT"
LEAVE_CHECK_DEFAULT_TIMEOUT = 120.0
LEAVE_CHECK_OUTPUT_TAIL_LINES = 40


def _parse_leave_args(raw: list[str]) -> tuple[dict[str, str], list[str]]:
    args: dict[str, str] = {}
    problems: list[str] = []
    for item in raw:
        m = LEAVE_ARG_RE.match(item)
        if not m:
            problems.append(f"--leave-arg '{item}' is not name=value with a "
                            f"name matching [a-z_]+")
            continue
        name, value = m.group("name"), m.group("value")
        if name in args:
            problems.append(f"--leave-arg '{name}' is given more than once")
        elif not value.strip():
            problems.append(f"--leave-arg '{name}' has an empty value")
        elif "\n" in value or "\r" in value:
            problems.append(f"--leave-arg '{name}' contains a line break")
        elif value.startswith("-"):
            problems.append(f"--leave-arg '{name}' starts with '-', which the "
                            f"leave_check program would read as an option")
        args[name] = value
    return args, problems


def _resolve_program(program: str) -> list[str] | None:
    """Resolve a registered Gear command, then fall back to PATH."""
    command = resolve_command(program)
    if command is not None:
        return command
    path_program = shutil.which(program)
    return [path_program] if path_program else None


def _leave_check_timeout() -> float:
    raw = os.environ.get(LEAVE_CHECK_TIMEOUT_ENV)
    if raw is None or raw == "":
        return LEAVE_CHECK_DEFAULT_TIMEOUT
    try:
        value = float(raw)
    except ValueError:
        value = 0.0
    if value <= 0:
        sys.exit(f"{LEAVE_CHECK_TIMEOUT_ENV}={raw!r} must be a positive "
                 f"number of seconds")
    return value


def _tail(output: str) -> str:
    lines = output.rstrip("\n").split("\n") if output.strip() else []
    tail = lines[-LEAVE_CHECK_OUTPUT_TAIL_LINES:]
    return "\n".join(f"  | {line}" for line in tail) if tail else "  | (no output)"


class LeaveRefused(Exception):
    """A leave_check program exited non-zero. `message` lists its output."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _run_leave_check(current: str, template: list[str],
                     raw_args: list[str], task_folder: str | None = None) -> list[str]:
    """Substitute --leave-arg values into `template`, run it without a
    shell, and return the executed argv. Exits with every argument problem
    listed; a non-zero check raises LeaveRefused."""
    leave_args, problems = _parse_leave_args(raw_args)
    if "task_folder" in leave_args:
        problems.append("task_folder is reserved; omit the caller override")
    if task_folder is not None:
        leave_args["task_folder"] = task_folder
    placeholders: list[str] = []
    for part in template:
        for m in LEAVE_CHECK_PLACEHOLDER_RE.finditer(part):
            if m.group("name") not in placeholders:
                placeholders.append(m.group("name"))
    for name in placeholders:
        if name not in leave_args:
            problems.append(f"leave_check placeholder '{{{name}}}' has no "
                            f"--leave-arg {name}=<value>")
    for name in leave_args:
        if name not in placeholders and name != "task_folder":
            problems.append(f"--leave-arg '{name}' matches no placeholder in "
                            f"'{current}''s leave_check")
    if problems:
        sys.exit(f"'{current}' has a leave_check and cannot be left: "
                 f"{len(problems)} problem(s) found:\n"
                 + "\n".join(f"  - {p}" for p in problems))

    argv = [LEAVE_CHECK_PLACEHOLDER_RE.sub(lambda m: leave_args[m.group("name")], part)
            for part in template]
    resolved = _resolve_program(argv[0])
    if resolved is None:
        sys.exit(f"leave_check program '{argv[0]}' not found — install the "
                 f"plugin that provides it")
    argv = [*resolved, *argv[1:]]
    timeout = _leave_check_timeout()
    shown = " ".join(argv)
    try:
        # The output tail is quoted in a refusal an LLM reads, so the check
        # prints prose even though its stdout is this pipe.
        proc = subprocess.Popen(argv, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL,
                                start_new_session=True,
                                env={**os.environ, ENV_MODE: "prose"})
    except OSError as e:
        sys.exit(f"'{current}' leave_check could not start: {shown}: {e}")
    try:
        out_bytes, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        # The check runs in its own session so its whole process group —
        # grandchildren holding the output pipe included — dies with it.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        out_bytes, _ = proc.communicate()
        output = out_bytes.decode(errors="replace")
        sys.exit(f"'{current}' leave_check timed out after {timeout:g}s: "
                 f"{shown}\nlast {LEAVE_CHECK_OUTPUT_TAIL_LINES} lines of "
                 f"output:\n{_tail(output)}")
    output = out_bytes.decode(errors="replace")
    if proc.returncode != 0:
        raise LeaveRefused(f"'{current}' leave_check exited {proc.returncode}: "
                           f"{shown}\nlast {LEAVE_CHECK_OUTPUT_TAIL_LINES} lines of "
                           f"output:\n{_tail(output)}")
    return argv
