#!/usr/bin/env python3
"""Keep paired advisors listening and report missing heartbeats."""

from __future__ import annotations

import json
import sys
import time

from bootgear_cli import clikit, coordination


def main() -> None:
    if clikit.event_help("advisor", "hook", "stdin JSON from a native advisor host event.",
                         {"session_id": "example-host", "hook_event_name": "Stop"}):
        return
    event = json.load(sys.stdin)
    if not isinstance(event, dict) or event.get("agent_id"):
        return
    try:
        store = coordination.observe(coordination.Caller.from_host_event())
    except (clikit.Refusal, OSError, ValueError):
        return
    if store is None:
        return
    name = event.get("hook_event_name")
    is_advisor = coordination.linked(store, store.seat)
    paired = is_advisor or (store.seat == "main" and
                            any(coordination.linked(store, seat) for seat in store.state["seats"]))
    program = clikit.gear_command("cli", "coordination")
    poll = f"{program} poll --wait 300"
    if name == "Stop" and is_advisor:
        print(json.dumps({"decision": "block", "reason": f"Keep listening for work. Run {poll}"}))
    elif name == "SessionStart" and event.get("source") == "compact" and (
            paired or coordination.active_slate(store)):
        _hint(name, f"Continue work. Run {poll}")
    elif name in {"PostToolUse", "UserPromptSubmit"} and paired:
        record = store.state["seats"][store.seat]
        if record["restart_until"] or time.time() - record.get("heartbeat_at", 0) > coordination.HEARTBEAT_TTL:
            _hint(name, f"Restart the required seat heartbeat in the background. Run {program} heartbeat --wait 6180")


def _hint(event: str, context: str) -> None:
    print(json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": context}}))


if __name__ == "__main__":
    main()
