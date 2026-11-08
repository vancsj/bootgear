"""Shared memory-ledger reminder policy without a host output envelope."""
from __future__ import annotations

import fcntl
import json
import shlex
import time
from dataclasses import dataclass
from pathlib import Path

from .context import InvocationContext
from .doctor import capability_status

COOLDOWN_SECONDS = 300
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
    tool_name: str
    tool_input: dict
    host: str

    @classmethod
    def from_payload(cls, payload: dict, *, host: str) -> NudgeEvent | None:
        tool_input = payload.get("tool_input") or {}
        session_id = payload.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            return None
        if not isinstance(tool_input, dict):
            return None
        cwd = payload.get("cwd") or str(Path.cwd())
        return cls(session_id, Path(cwd).expanduser().resolve(),
                   str(payload.get("hook_event_name") or ""),
                   str(payload.get("tool_name") or ""), tool_input, host)


@dataclass(frozen=True)
class NudgeResult:
    status: str
    message: str | None = None
    visible_status: bool = False


def _is_ledger_invocation(tool_name: str, tool_input: dict) -> bool:
    if tool_name == "Bash":
        try:
            words = shlex.split(str(tool_input.get("command", "")))
        except ValueError:
            return False
        for index, word in enumerate(words):
            if Path(word).name != "gear":
                continue
            args = words[index + 1:]
            while args and args[0] in {"--host", "--root"}:
                args = args[2:]
            if args[:2] == ["memory-ledger", "ledger"]:
                return True
        return False
    if tool_name == "Skill":
        return str(tool_input.get("skill", "")) in ("ledger", "memory-ledger:ledger")
    return False


def _cooldown_path(session_id: str) -> Path:
    directory = Path.home() / ".memory-ledger" / ".nudge-state"
    directory.mkdir(parents=True, exist_ok=True)
    return directory / f"{session_id}.last"


def _in_cooldown(path: Path, now: float) -> bool:
    try:
        marker = json.loads(path.read_text(encoding="utf-8"))
        if marker.get("event") == "ledger-used":
            return False
        return now - path.stat().st_mtime < COOLDOWN_SECONDS
    except (OSError, json.JSONDecodeError, AttributeError):
        return False


def _locked(path: Path):
    lock = path.with_name(path.name + ".lock")
    handle = lock.open("a+")
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
    return handle


def _touch(path: Path, event: NudgeEvent, status: str, now: float) -> None:
    path.write_text(json.dumps({
        "at": now,
        "event": status,
        "hook_event": event.event,
        "tool": event.tool_name,
    }, separators=(",", ":")), encoding="utf-8")


def evaluate(event: NudgeEvent, *, now: float | None = None) -> NudgeResult:
    if event.event != "PostToolUse":
        return NudgeResult("cooldown")
    context = InvocationContext(event.cwd, event.host, event.session_id)
    status = capability_status(context)
    if status != "configured":
        return NudgeResult(status, visible_status=True)

    path = _cooldown_path(event.session_id)
    current = time.time() if now is None else now
    handle = _locked(path)
    try:
        if _is_ledger_invocation(event.tool_name, event.tool_input):
            _touch(path, event, "ledger-used", current)
            return NudgeResult("ledger-used")
        if _in_cooldown(path, current):
            return NudgeResult("cooldown")
        _touch(path, event, "nudged", current)
        return NudgeResult("nudged", NUDGE_MESSAGE)
    finally:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()
