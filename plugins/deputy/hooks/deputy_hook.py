#!/usr/bin/env python3
"""Claude Code and Codex hook for the deputy: reminds the session to ask the deputy on
UserPromptSubmit, and to record an escalated answer on PostToolUse of the host's question tool."""

from __future__ import annotations

import contextlib
import json
import os
import sys
from pathlib import Path

ASK = ("deputy: before you ask the user a work question, call `deputy:ask` with the question, its options "
       "and its stakes. Ask the user only if it returns `escalate`. Never send a production change, outward "
       "send, irreversible action, goal sign-off or permitted mutations to the deputy. If this prompt answers "
       "a question that `deputy:ask` escalated, and the answer is written in a session ledger file, call "
       "`deputy:record` with the question, the answer, the reason, the options and the stakes.")
RECORD = ("deputy: if `deputy:ask` returned `escalate` for the question the user just answered, and the answer "
          "is written in a session ledger file, call `deputy:record` with the question, the answer, the reason, "
          "the options and the stakes. Without a session ledger file, do not call it.")
QUESTION_TOOLS = ("AskUserQuestion", "request_user_input")


def reminder(payload: dict) -> str | None:
    event = payload.get("hook_event_name")
    if event == "UserPromptSubmit":
        return ASK
    if event == "PostToolUse" and payload.get("tool_name") in QUESTION_TOOLS:
        return RECORD
    return None


def remind() -> None:
    payload = json.loads(sys.stdin.read())
    if not isinstance(payload, dict) or payload.get("agent_id"):
        return
    root = Path(os.environ.get("LEDGER_DEPUTY_ROOT", "~/.memory-ledger/deputy")).expanduser()
    if not root.is_dir():
        return
    text = reminder(payload)
    if text:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": payload["hook_event_name"],
                                                 "additionalContext": text}}, separators=(",", ":")))


def main() -> int:
    """Print the reminder, or nothing on bad input, for a subagent, without a deputy root, or on any error."""
    with contextlib.suppress(BaseException):
        remind()
    return 0


if __name__ == "__main__":
    sys.exit(main())
