"""Supply the native participant ID carried by a host tool event."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Any

from bootgear_cli import clikit
from bootgear_cli.coordination import HOST_CALLER, PARTICIPANT_ENV
from bootgear_cli.gear import DEFAULT_ROOT, command_parser

COORDINATION = ("cli", "coordination")
CONVERGE = ("converge", "converge")
NATIVE_COMMANDS = {"join", "poll", "send", "complete", "heartbeat", "blocked"}
REVIEW_COMMANDS = {"init", "act", "finish", "status", "coverage", "cutoff", "converged", "gate",
                   "render", "fix-check", "fallback"}
DIRECTORY_CHANGE = re.compile(
    r"^[ \t]*cd[ \t]+(?:--[ \t]+)?"
    r"""(?P<path>'[^'\n]+'|"[^"$\x60\\\n]+"|[^\s;&|<>()'"$\x60\\*?\[\]{}~]+)[ \t]+&&[ \t]*"""
)


def _details(payload: dict[str, Any]) -> dict[str, Any] | None:
    participant = payload.get("agent_id")
    tool_input = payload.get("tool_input", {})
    if not isinstance(tool_input, dict):
        return None
    if participant is not None and (not isinstance(participant, str) or not participant):
        return None
    command = tool_input.get("command")
    if not isinstance(command, str):
        return None
    directory_change = DIRECTORY_CHANGE.match(command)
    try:
        tokens = shlex.split(command[directory_change.end():] if directory_change else command)
        directory = shlex.split(directory_change["path"])[0] if directory_change else None
    except ValueError:
        return None
    if not tokens or Path(tokens[0]).name != "gear":
        return None
    gear = clikit.gear_argv(*COORDINATION)
    cwd = clikit.caller_path(directory or ".")
    if (cwd / tokens[0]).resolve() != Path(gear[0]).resolve():
        return None
    parser = command_parser(add_help=False, exit_on_error=False)
    parser.set_defaults(root=None)
    try:
        options, unknown = parser.parse_known_args(tokens[1:])
    except argparse.ArgumentError:
        return None
    if unknown or options.host not in {None, clikit.host()}:
        return None
    trusted_root = Path(os.environ.get("GEAR_ROOT") or DEFAULT_ROOT).resolve()
    if options.root is not None and (cwd / options.root).resolve() != trusted_root:
        return None
    route = tuple(options.route[:2])
    if route not in {COORDINATION, CONVERGE}:
        return None
    verb = options.route[2] if len(options.route) > 2 else ""
    if route == CONVERGE and verb not in REVIEW_COMMANDS:
        return None
    allowed = verb in NATIVE_COMMANDS if route == COORDINATION else verb == "act"
    if participant is not None and not allowed:
        return {"permissionDecision": "deny",
                "permissionDecisionReason": "This command requires the main coordination seat."}
    output = [flag for flag, enabled in (("--json", options.json), ("--prose", options.prose)) if enabled]
    bound_command = shlex.join(["/usr/bin/env", f"{PARTICIPANT_ENV}={participant or HOST_CALLER}",
                                *gear[:-2], *output, *options.route])
    if directory is not None:
        bound_command = f"{shlex.join(['cd', '--', directory])} && {bound_command}"
    return {"permissionDecision": "allow", "updatedInput": {**tool_input, "command": bound_command}}


def main() -> None:
    if clikit.event_help("cli", "coordination-hook", "stdin JSON from a native Bash PreToolUse event.",
                         {"session_id": "example-host", "hook_event_name": "PreToolUse"}):
        return
    payload = json.load(sys.stdin)
    if isinstance(payload, dict) and (output := _details(payload)):
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", **output}}))


if __name__ == "__main__":
    main()
