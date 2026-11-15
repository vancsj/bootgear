#!/usr/bin/env python3
"""Codex adapter for the shared memory-ledger reminder policy."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from bootgear_cli.clikit import event_help

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ledgerlib.identity import validate_codex_session_id
from ledgerlib.nudge import NudgeEvent, evaluate


def main() -> None:
    if event_help("memory-ledger", "codex-hook", "Codex event JSON on stdin: UUID session_id, hook_event_name, tool_name, and tool_input.",
                  {"session_id": "00000000-0000-4000-8000-000000000001", "hook_event_name": "PostToolUse", "tool_name": "exec_command", "tool_input": {"cmd": "rg symbol source.py"}}):
        return
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, EOFError):
        return
    if not isinstance(payload, dict):
        return
    try:
        validate_codex_session_id(payload.get("session_id"))
    except SystemExit:
        return
    event = NudgeEvent.from_payload(payload, host="codex")
    if event is None:
        return
    result = evaluate(event)
    if result.visible_status:
        print(json.dumps({"systemMessage": f"memory-ledger: {result.status}"},
                         separators=(",", ":")))
    elif result.status == "nudged":
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": result.message,
            }
        }, separators=(",", ":")))


if __name__ == "__main__":
    main()
