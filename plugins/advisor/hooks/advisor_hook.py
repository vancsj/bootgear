#!/usr/bin/env python3
"""Claude Code and Codex hook for advisor seats: stamps the session's seat on SessionStart
(compact), PostToolUse, UserPromptSubmit and Stop, reminds the session to restart a stopped
heartbeat, and restores the channel status after compaction. Every failure exits 0 silently."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "advisor" / "scripts" / "channel.py"
REMINDER_EVENTS = {"PostToolUse", "UserPromptSubmit"}


def load_channel():
    spec = importlib.util.spec_from_file_location("advisor_channel", SCRIPT)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def output(event: str, text: str) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}},
                     separators=(",", ":")))


def engine_run(channel, session: str) -> str | None:
    """`engine run: <session>` when this session has an engine ledger."""
    if not channel.safe_name(session):
        return None
    ledger = Path.home() / ".bootgear" / "session" / f"{session}.md"
    return f"engine run: {session}" if ledger.is_file() else None


def main() -> None:
    payload = json.loads(sys.stdin.read())
    if not isinstance(payload, dict):
        return
    session, event = payload.get("session_id"), payload.get("hook_event_name")
    if not (isinstance(session, str) and session and isinstance(event, str) and event):
        return
    compact = event == "SessionStart" and payload.get("source") == "compact"
    if not (compact or event in REMINDER_EVENTS or event == "Stop"):
        return
    channel = load_channel()
    configured = os.environ.get("BOOTGEAR_ADVISOR_DIR")
    root = channel.caller_path(configured) if configured else channel.DEFAULT_ROOT
    due = channel.hook_touch(root, session, time.time(), remind=event in REMINDER_EVENTS and not payload.get("agent_id"))
    if payload.get("agent_id"):
        return
    if compact:
        statuses = [channel.channel_status(root, record, role) for record, role in channel.owned_channels(root, session)]
        if statuses:
            run = engine_run(channel, session)
            output(event, "\n".join(filter(None, [run, channel.render_status(statuses)])))
    elif event in REMINDER_EVENTS and due:
        output(event, "\n".join(
            f"advisor: your heartbeat for channel {record['channel']} ({role}) is not running; start it in a new "
            f"background session: {channel.heartbeat_command(channel_seat(record, role), root, str(record['channel']))}"
            for record, role in due))


def channel_seat(record: dict[str, object], role: str) -> argparse.Namespace:
    return argparse.Namespace(root=None, role=role, session=str(record[f"{role}_owner"]))


if __name__ == "__main__":
    try:
        main()
    except BaseException:  # noqa: BLE001
        sys.exit(0)
