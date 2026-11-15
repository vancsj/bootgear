#!/usr/bin/env python3
"""Claude Code adapter for the shared memory-ledger reminder policy."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from bootgear_cli.clikit import event_help

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ledgerlib.nudge import NudgeEvent, evaluate


def main() -> None:
    if event_help("memory-ledger", "hook", "Claude event JSON on stdin: session_id, hook_event_name, tool_name, and tool_input.",
                  {"session_id": "example-session", "hook_event_name": "PostToolUse", "tool_name": "Read", "tool_input": {"file_path": "source.py"}}):
        return
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        return
    if not isinstance(payload, dict):
        return
    event = NudgeEvent.from_payload(payload, host="claude")
    if event is None:
        return
    result = evaluate(event)
    if result.visible_status:
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": f"memory-ledger: {result.status}",
            }
        }, separators=(",", ":")))
    elif result.status == "nudged":
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": result.message,
            }
        }, separators=(",", ":")))


if __name__ == "__main__":
    main()
