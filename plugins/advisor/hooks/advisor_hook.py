#!/usr/bin/env python3
"""Guard listener turns, refresh seat activity, and restore channel guidance after compaction."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import time
from pathlib import Path

from bootgear_cli.clikit import event_help

SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "advisor" / "scripts" / "channel.py"
REMINDER_EVENTS = {"PostToolUse", "UserPromptSubmit"}


def load_channel():
    spec = importlib.util.spec_from_file_location("advisor_channel", SCRIPT)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    # Loading by path does not add the script's directory to the import path.
    sys.path.insert(0, str(SCRIPT.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.pop(0)
    return module


def output(event: str, text: str) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}},
                     separators=(",", ":")))


def engine_run(channel, session: str) -> str | None:
    """`engine run: <session>` when this session has an active engine ledger (no `## closed` heading)."""
    if not channel.safe_name(session):
        return None
    ledger = Path.home() / ".bootgear" / "session" / f"{session}.md"
    active = ledger.is_file() and not re.search(r"(?m)^## closed\s*$", ledger.read_text(encoding="utf-8"))
    return f"engine run: {session}" if active else None


def main() -> None:
    if event_help("advisor", "hook", "stdin JSON: session_id, hook_event_name, source, and optional agent_id. "
                  "Events: SessionStart (source compact), PostToolUse, UserPromptSubmit, Stop.",
                  {"session_id": "example-session", "hook_event_name": "UserPromptSubmit"}):
        return
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
    if event == "Stop":
        for record, role in channel.owned_channels(root, session):
            if role == "listener" and not channel.listener_can_ask(record):
                next_step = channel.channel_status(root, record, role)["next"]
                reason = (f"Keep this turn running. Advisor channel {record['channel']} is open. "
                          "Send any questions or reports to the asker through the mailbox. "
                          "Do not wait for the user to reply. Collect any running receive. "
                          f"Otherwise continue now: {next_step}")
                print(json.dumps({"decision": "block", "reason": reason}))
                break
    elif compact:
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
