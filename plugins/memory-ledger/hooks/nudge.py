#!/usr/bin/env python3
"""Claude Code adapter for the shared memory-ledger reminder policy."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from ledgerlib.nudge import NudgeEvent, evaluate


def main() -> None:
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
