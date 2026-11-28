"""Gear commands for coordinating participants through their default store."""

from __future__ import annotations

import argparse
import math
import sys
import time

from bootgear_cli import clikit, coordination

CATALOG = clikit.Catalog(
    clikit.current_program("cli", "coordination"),
    {"init": "init", "reserve": "reserve advisor advisor", "join": "join <invitation>",
     "replace": "replace advisor", "release": "release advisor", "heartbeat": "heartbeat --wait 6180",
     "send": 'send advisor "Review the draft"', "poll": "poll --wait 60",
     "complete": 'complete <assignment-id> "Review complete"',
     "blocked": 'blocked "The draft cannot be read"'},
    ("send", "poll", "complete"),
)


def _duration(value: str) -> float:
    try:
        duration = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("expected seconds") from None
    if not math.isfinite(duration) or duration < 0:
        raise argparse.ArgumentTypeError("expected a nonnegative number of seconds")
    return duration


def _parser() -> argparse.ArgumentParser:
    parser = clikit.parser_class(CATALOG)(prog=CATALOG.display_prog(),
                                          description="Coordinate seats through the current host.")
    commands = parser.add_subparsers(dest="command", required=True)
    descriptions = {
        "init": "Initialize the store for the current host.",
        "reserve": "Reserve a seat and return an invitation.",
        "join": "Join the seat named by an invitation.",
        "replace": "Rotate the invitation for a stale seat.",
        "release": "Stop a participant and keep its unfinished work on the seat.",
        "heartbeat": "Refresh the liveness of the current participant.",
        "send": "Create an assignment for a seat.",
        "poll": "Read a delivery or resume open work.",
        "complete": "Complete an assignment with an optional reply.",
        "blocked": "Report a blocker to main without completing work.",
    }
    for name, description in descriptions.items():
        command = commands.add_parser(name, description=description)
        command.add_argument("--json", action="store_true", help="emit structured JSON")
        command.add_argument("--prose", action="store_true", help="emit key and value lines")
        command.add_argument("--timeout", type=_duration, default=coordination.DEFAULT_TIMEOUT,
                             help="time to acquire the store lock in seconds")
        if name in {"reserve", "replace", "release", "send"}:
            command.add_argument("seat")
        if name == "reserve":
            command.add_argument("role")
        if name == "join":
            command.add_argument("invitation")
        if name == "send":
            command.add_argument("message", help="message body or '-' to read stdin")
            command.add_argument("--key", help="request key for an intentional repeat")
        if name == "poll":
            command.add_argument("--ack", help="acknowledge this delivery ID")
            command.add_argument("--wait", type=_duration, default=0,
                                 help="time to wait for work in seconds")
        if name == "heartbeat":
            command.add_argument("--restart", action="store_true", help="start the restart grace")
            command.add_argument("--wait", type=_duration, default=0, help="keep the seat live for this many seconds")
        if name == "blocked":
            command.add_argument("message", help="blocker description or '-' to read stdin")
        if name == "complete":
            command.add_argument("assignment")
            command.add_argument("message", nargs="?", help="reply or '-' to read stdin")
    return parser


def _message(message: str | None) -> str | None:
    return sys.stdin.read().rstrip() if message == "-" else message


def _poll(caller: coordination.Caller, args: argparse.Namespace) -> coordination.Record:
    deadline = time.monotonic() + args.wait
    acknowledgement = args.ack
    while True:
        with coordination.transaction(caller, args.timeout, accept_stopped=True) as store:
            result = coordination.poll(store, acknowledgement, args.timeout)
        if result.get("status") != "idle" or (remaining := deadline - time.monotonic()) <= 0:
            return {key: value for key, value in result.items() if key != "progress_at"}
        acknowledgement = None
        time.sleep(min(remaining, 0.25))


def _beat(caller: coordination.Caller, args: argparse.Namespace) -> coordination.Record:
    deadline = time.monotonic() + min(args.wait, 6180)
    while True:
        remaining = deadline - time.monotonic()
        restarting = args.restart or (args.wait > 0 and remaining <= 0)
        with coordination.transaction(caller, args.timeout, accept_stopped=True) as store:
            coordination.heartbeat(store, restarting=restarting, background=args.wait > 0)
        if restarting or remaining <= 0:
            return {"status": "restarting" if restarting else "live", "seat": store.seat}
        time.sleep(min(remaining, 3))


def _transaction(caller: coordination.Caller, args: argparse.Namespace) -> coordination.Record:
    message = _message(getattr(args, "message", None))
    with coordination.transaction(caller, args.timeout) as store:
        match args.command:
            case "reserve":
                return coordination.reserve(store, args.seat, args.role)
            case "replace":
                return coordination.replace(store, args.seat)
            case "send":
                return coordination.send(store, args.seat, message or "", args.key)
            case "complete":
                return coordination.complete(store, args.assignment, message, args.timeout)
            case "blocked":
                return coordination.blocked(store, message or "")
            case _:
                raise AssertionError(args.command)


def _next(command: str, result: coordination.Record) -> str | None:
    program = CATALOG.display_prog()
    poll = program + " poll --wait 300"
    if result.get("status") == "stopped":
        return None
    if command == "poll" and result.get("status") == "blocked":
        return "start or resume the affected advisor, or replace its seat when stale"
    if command in {"reserve", "replace"}:
        return "give the invitation to the participant assigned to this seat"
    if command == "init":
        return "reserve a seat for work or open a Converge slate"
    if command == "heartbeat":
        return program + " heartbeat --wait 6180" if result["status"] == "restarting" else None
    if command == "poll" and "delivery_id" in result:
        poll += f" --ack {result['delivery_id']}"
        if result["kind"] == "assignment":
            finish = f"{program} complete {result['assignment_id']}"
            if result.get("work"):
                return f"submit the assignment evidence through Converge, then {finish}"
            return f"do the assigned work, then {finish}"
    if command in {"join", "send", "poll", "blocked", "complete"}:
        return poll
    return None


def _dispatch(args: argparse.Namespace) -> None:
    caller = coordination.Caller.from_environment()
    try:
        match args.command:
            case "init":
                result = coordination.initialize(caller, args.timeout)
            case "join":
                result = coordination.join(caller, args.invitation, args.timeout)
            case "release":
                result = coordination.release(caller, args.seat, args.timeout)
            case "heartbeat":
                result = _beat(caller, args)
            case "poll":
                result = _poll(caller, args)
            case _:
                result = _transaction(caller, args)
    except coordination.Stopped as error:
        result = {"status": "stopped", "seat": error.seat}
    except (OSError, ValueError) as error:
        clikit.refuse(f"cannot access coordination store: {error}")
    clikit.emit(args.output_mode, result, [f"{key}: {value}" for key, value in result.items()],
                _next(args.command, result))


def main() -> None:
    clikit.run(_parser(), CATALOG, lambda args: args.command, dispatch=_dispatch)


if __name__ == "__main__":
    main()
