"""Resolve a Bootgear host and session from the caller environment."""

from __future__ import annotations

import os
import subprocess

HOST_SESSION_ENV = {"claude": "CLAUDE_CODE_SESSION_ID", "codex": "CODEX_SESSION_ID"}

HOST_PROCESS = {"claude", "codex"}

ANCESTOR_STEPS = 32

PS_TIMEOUT = 2

def _host_sessions() -> dict[str, str]:
    """Each host whose session variable is set and non-empty, with its value."""
    return {name: value for name, variable in HOST_SESSION_ENV.items()
            if (value := os.environ.get(variable))}

def session_id(explicit: str | None = None, *, host: str | None = None) -> str | None:
    """`explicit` when given, else $BOOTGEAR_SESSION_ID, else the session variable of
    `host` (default: `host()`), else the other one; empty values count as absent."""
    if explicit is not None:
        return explicit
    if value := os.environ.get("BOOTGEAR_SESSION_ID"):
        return value
    sessions = _host_sessions()
    if len(sessions) > 1:
        chosen = host if host is not None else _environment_host()
        return sessions.get(chosen or "", next(iter(sessions.values())))
    return next(iter(sessions.values()), None)

def host(explicit: str | None = None) -> str | None:
    """`explicit` when given, else a non-empty $BOOTGEAR_HOST, else the host whose
    session variable is set. With both set, the nearest host ancestor process, else
    `claude`. None when neither is set."""
    return explicit if explicit is not None else _environment_host()

def _environment_host() -> str | None:
    if value := os.environ.get("BOOTGEAR_HOST"):
        return value
    sessions = _host_sessions()
    if len(sessions) > 1:
        return _ancestor_host() or "claude"
    return next(iter(sessions), None)

def _ancestor_host() -> str | None:
    """The nearest parent process named `claude` or `codex`, found through `ps`.

    None after ANCESTOR_STEPS steps, at pid 1, or when `ps` fails, times out or prints no pair."""
    pid = os.getppid()
    for _ in range(ANCESTOR_STEPS):
        if pid <= 1:
            return None
        try:
            result = subprocess.run(["ps", "-o", "ppid=,comm=", "-p", str(pid)],
                                    capture_output=True, text=True, timeout=PS_TIMEOUT,
                                    stdin=subprocess.DEVNULL, check=False)
        except (OSError, subprocess.SubprocessError):
            return None
        fields = result.stdout.split(None, 1)
        if result.returncode != 0 or len(fields) != 2 or not fields[0].isdigit():
            return None
        name = os.path.basename(fields[1].strip())
        if name in HOST_PROCESS:
            return name
        pid = int(fields[0])
    return None

def missing_session(override: str) -> str:
    """The refusal text for a command that found no session id."""
    return ("no session id found in the environment; run inside a Claude Code or Codex "
            f"session, or pass {override}")
