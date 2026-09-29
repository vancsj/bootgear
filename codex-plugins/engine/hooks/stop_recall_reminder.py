#!/usr/bin/env python3
"""Remind the next Codex turn to recall an active engine run."""
from __future__ import annotations

import fcntl
import json
import os
import re
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_CLOSED_HEADING_RE = re.compile(r"(?m)^## closed\s*$")
_RAPID_SECONDS = 30
_MAX_NUDGES = 1
_MAX_TURNS = 32

REMINDER_MESSAGE = (
    "An engine run is active in this session ({run_id}). Before treating "
    "this as a natural stopping point, call `recall` to re-read the "
    "settlement and open todos from the ledger, and check state against "
    "`/goal`'s succeeded/failed conditions — don't rely on this turn's own "
    "memory of them."
)


def _ledger_path(hook_input: dict) -> tuple[str, Path] | None:
    run_id = hook_input.get("session_id")
    if not isinstance(run_id, str) or not run_id:
        return None
    ledger_path = Path.home() / ".bootgear" / "session" / f"{run_id}.md"
    if not ledger_path.is_file():
        return None
    try:
        text = ledger_path.read_text()
    except OSError:
        return None
    if _CLOSED_HEADING_RE.search(text):
        return None
    return run_id, ledger_path


def _marker_path(ledger_path: Path, run_id: str) -> Path:
    return ledger_path.parent / f".{run_id}.stop_reminder_state"


@contextmanager
def _marker_lock(marker_path: Path) -> Iterator[None]:
    lock_path = marker_path.with_name(f"{marker_path.name}.lock")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _read_state(marker_path: Path) -> dict:
    try:
        data = json.loads(marker_path.read_text())
    except (OSError, ValueError, json.JSONDecodeError):
        return {"turns": [], "nudge_count": 0, "last_nudge_at": 0.0}
    if not isinstance(data, dict):
        return {"turns": [], "nudge_count": 0, "last_nudge_at": 0.0}
    turns = data.get("turns")
    if not isinstance(turns, list):
        turns = []
    data["turns"] = [
        turn for turn in turns
        if isinstance(turn, dict) and isinstance(turn.get("turn_id"), str)
    ][-_MAX_TURNS:]
    return data


def _write_atomic(path: Path, text: str) -> None:
    fd, tmp_name = tempfile.mkstemp(
        prefix=f"{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "w") as tmp:
            tmp.write(text)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def _should_nudge(state: dict, now: float) -> bool:
    nudge_count = state.get("nudge_count", 0)
    last_nudge_at = state.get("last_nudge_at", 0.0)
    if not isinstance(nudge_count, int) or not isinstance(last_nudge_at, (int, float)):
        nudge_count, last_nudge_at = 0, 0.0

    if now - last_nudge_at >= _RAPID_SECONDS:
        state["nudge_count"] = 1
        state["last_nudge_at"] = now
        return True
    if nudge_count >= _MAX_NUDGES:
        state["nudge_count"] = 0
        return False
    state["nudge_count"] = nudge_count + 1
    state["last_nudge_at"] = now
    return True


def _turn(state: dict, turn_id: str) -> dict | None:
    for turn in reversed(state["turns"]):
        if turn["turn_id"] == turn_id:
            return turn
    return None


def _process(hook_input: dict, run_id: str, ledger_path: Path) -> bool:
    event = hook_input["hook_event_name"]
    turn_id = hook_input["turn_id"]
    marker_path = _marker_path(ledger_path, run_id)
    now = time.time()

    with _marker_lock(marker_path):
        state = _read_state(marker_path)
        turns = state["turns"]
        current = _turn(state, turn_id)
        should_emit = False

        if event == "Stop":
            if current is None:
                current = {"turn_id": turn_id, "stop_seen": False,
                           "fallback_reminded": False}
                turns.append(current)
            current["stop_seen"] = True
            if hook_input.get("stop_hook_active") is not True:
                should_emit = _should_nudge(state, now)
        else:
            if current is None:
                previous = turns[-1] if turns else None
                current = {"turn_id": turn_id, "stop_seen": False,
                           "fallback_reminded": False}
                turns.append(current)
                if (previous is not None
                        and not previous.get("stop_seen", False)
                        and not previous.get("fallback_reminded", False)):
                    previous["fallback_reminded"] = True
                    should_emit = _should_nudge(state, now)

        state["turns"] = turns[-_MAX_TURNS:]
        _write_atomic(marker_path, json.dumps(state))

    return should_emit


def main() -> None:
    try:
        hook_input = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return
    if not isinstance(hook_input, dict):
        return
    event = hook_input.get("hook_event_name")
    if event not in {"Stop", "PostToolUse"}:
        return
    if not all(
        isinstance(hook_input.get(field), str) and hook_input[field]
        for field in ("session_id", "cwd", "turn_id")
    ):
        return
    active = _ledger_path(hook_input)
    if active is None:
        return
    run_id, ledger_path = active
    try:
        should_emit = _process(hook_input, run_id, ledger_path)
    except OSError:
        return
    if should_emit:
        message = REMINDER_MESSAGE.format(run_id=run_id)
        if event == "Stop":
            print(json.dumps({"decision": "block", "reason": message}))
            return
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": event,
                "additionalContext": message,
            }
        }))


if __name__ == "__main__":
    main()
