"""Shared memory-ledger reminder policy without a host output envelope."""
from __future__ import annotations

import fcntl
import json
import re
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path

from .context import InvocationContext
from .doctor import capability_status

COOLDOWN_SECONDS = 300
SESSION_PATH_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,244}\Z")
NUDGE_MESSAGE = (
    "Before continuing: has this been settled in memory-ledger already? "
    "Invoke the `memory-ledger:ledger` skill to check, and to record "
    "anything durable found so far."
)


@dataclass(frozen=True)
class NudgeEvent:
    session_id: str
    cwd: Path
    event: str
    host: str

    @classmethod
    def from_payload(cls, payload: dict, *, host: str) -> NudgeEvent | None:
        session_id = payload.get("session_id")
        if not isinstance(session_id, str) or not SESSION_PATH_COMPONENT.fullmatch(session_id):
            return None
        if not isinstance(payload.get("tool_input") or {}, dict):
            return None
        cwd = payload.get("cwd") or str(Path.cwd())
        return cls(session_id, Path(cwd).expanduser().resolve(),
                   str(payload.get("hook_event_name") or ""), host)


@dataclass(frozen=True)
class NudgeResult:
    status: str
    message: str | None = None
    visible_status: bool = False


def _cooldown_path(session_id: str) -> Path:
    directory = Path.home() / ".memory-ledger" / ".nudge-state"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{session_id}.last"


def _in_cooldown(path: Path, now: float) -> bool:
    try:
        marker = json.loads(path.read_text(encoding="utf-8"))
        return isinstance(marker, dict) and now - path.stat().st_mtime < COOLDOWN_SECONDS
    except (OSError, ValueError):
        return False


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    lock = path.with_name(path.name + ".lock")
    with lock.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield


def _touch(path: Path, status: str, now: float) -> None:
    path.write_text(json.dumps({"at": now, "event": status}, separators=(",", ":")),
                    encoding="utf-8")


def record_lookup(session_id: str | None) -> None:
    if session_id is None or not SESSION_PATH_COMPONENT.fullmatch(session_id):
        return
    with suppress(OSError):
        path = _cooldown_path(session_id)
        with _locked(path):
            _touch(path, "ledger-used", time.time())


def evaluate(event: NudgeEvent, *, now: float | None = None) -> NudgeResult:
    if event.event != "PostToolUse":
        return NudgeResult("cooldown")
    context = InvocationContext(event.cwd, event.host, event.session_id)
    status = capability_status(context)
    if status != "configured":
        return NudgeResult(status, visible_status=True)

    path = _cooldown_path(event.session_id)
    current = time.time() if now is None else now
    with _locked(path):
        if _in_cooldown(path, current):
            return NudgeResult("cooldown")
        _touch(path, "nudged", current)
        return NudgeResult("nudged", NUDGE_MESSAGE)
