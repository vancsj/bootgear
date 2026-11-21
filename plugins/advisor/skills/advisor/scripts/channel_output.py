"""Render advisor CLI results, refusals, and next commands."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from pathlib import Path
from typing import NoReturn

from bootgear_cli import clikit
from bootgear_cli.clikit import current_program
from channel_liveness import (
    HEARTBEAT_INTERVAL_SECONDS,
    HEARTBEAT_MAX_AGE_SECONDS,
    seat_beating,
)
from channel_store import (
    CHANNEL_PATTERN,
    DEFAULT_ROOT,
    ROLES,
    brief_record,
    caller_path,
    fail,
)

COMMANDS = ("register", "init", "send", "receive", "fetch", "state", "close", "heartbeat", "list", "status",
            "whoami")
EXAMPLES = {
    "register": "register --role asker --channel 0001",
    "init": "init --channel 0001",
    "send": "send --channel 0001 --from asker --to listener --kind request --body-file -",
    "receive": "receive --channel 0001 --for asker --timeout 300",
    "fetch": "fetch --channel 0001 --message-id MESSAGE_ID",
    "state": "state --channel 0001 --role listener --value waiting",
    "close": "close --channel 0001 --role listener",
    "heartbeat": "heartbeat --channel 0001 --role listener",
    "list": "list --live-for asker",
    "status": "status --channel 0001",
    "whoami": "whoami",
}


OUTPUT_MODES = ("json", "prose")
# The fields a prose line shows for one list item; any other item prints every field.
ITEM_KEYS = {
    "message_id": ("message_id", "sender", "kind", "parent_id", "preview", "answered"),
    "channel": ("channel", "state", "listener_owner", "asker_owner"),
}


def output_mode(args: argparse.Namespace) -> str:
    """`--json` or `--prose`, else `BOOTGEAR_OUTPUT=json|prose`, else prose."""
    if getattr(args, "json", False):
        return "json"
    if getattr(args, "prose", False):
        return "prose"
    configured = os.environ.get("BOOTGEAR_OUTPUT")
    return configured if configured in OUTPUT_MODES else "prose"


def prose_scalar(value: object) -> str:
    return json.dumps(value) if value is None or isinstance(value, bool) else str(value)


def prose_item(item: object) -> str:
    if not isinstance(item, dict):
        return prose_scalar(item)
    for marker, keys in ITEM_KEYS.items():
        if marker in item:
            item = {key: item[key] for key in keys if key in item}
            break
    return " ".join(f"{key}={prose_scalar(value)}" for key, value in item.items() if value is not None)


def render_prose(payload: dict[str, object]) -> str:
    """One `key: value` line per field, lists as `- ` items, multi-line text after the short
    fields, and `next` last."""
    lines: list[str] = []
    blocks: list[str] = []
    for key, value in payload.items():
        if key == "next":
            continue
        if isinstance(value, list):
            lines.append(f"{key}:" if value else f"{key}: none")
            lines.extend(f"  - {prose_item(item)}" for item in value)
        elif isinstance(value, str) and "\n" in value:
            blocks.append(f"{key}:\n{value}")
        else:
            lines.append(f"{key}: {prose_scalar(value)}")
    lines.extend(blocks)
    if "next" in payload:
        lines.append(f"next: {payload['next']}")
    return "\n".join(lines)


def emit(args: argparse.Namespace, payload: dict[str, object], ensure_ascii: bool = True) -> None:
    """Print `payload` to stdout in the selected output mode."""
    if output_mode(args) == "json":
        print(json.dumps(payload, ensure_ascii=ensure_ascii))
    else:
        print(render_prose(payload))


def invocation(root_value: str | None) -> str:
    """This script's invocation for a `--root` value, without creating the root: an absolute
    `--root` whenever one was given or `BOOTGEAR_ADVISOR_DIR` moves it off the default."""
    command = current_program("advisor", "channel")
    configured = root_value or os.environ.get("BOOTGEAR_ADVISOR_DIR")
    if configured:
        root = caller_path(configured)
        if root_value is not None or root != DEFAULT_ROOT:
            command += f" --root {shlex.quote(str(root))}"
    return command


CORRECTED_ARGUMENTS = "run the command again with corrected arguments, as in example"
MISSING_SESSION_NEXT = "stop and tell the user that this session has no session id in the environment"


def refuse_command(command: str | None, root_value: str | None, message: str,
                   category: str = "invalid_args", next_step: str = CORRECTED_ARGUMENTS) -> NoReturn:
    """An argument refusal of `command`, with one correct invocation and the other subcommands."""
    fail(message, category=category, next_step=next_step,
         extra={
             "example": f"{invocation(root_value)} {EXAMPLES[command or 'list']}",
             "commands": ", ".join(c for c in COMMANDS if c != command),
         })


def refuse(args: argparse.Namespace, message: str, category: str = "invalid_args",
           next_step: str = CORRECTED_ARGUMENTS) -> NoReturn:
    refuse_command(args.command, args.root, message, category, next_step)


def refuse_missing_session(args: argparse.Namespace) -> NoReturn:
    refuse(args, clikit.missing_session("--session"), next_step=MISSING_SESSION_NEXT)


def argv_command(argv: list[str]) -> tuple[str | None, str | None]:
    """The `--root` value and the subcommand in `argv`, reading `--root` and its abbreviations
    (`--r`, `--ro`, `--roo`) the way argparse does."""
    root = None
    index = 0
    while index < len(argv):
        token = argv[index]
        if token in COMMANDS:
            return root, token
        name, equals, value = token.partition("=")
        if len(name) >= 3 and "--root".startswith(name):
            if equals:
                root = value
            elif index + 1 < len(argv):
                index += 1
                root = argv[index]
        index += 1
    return root, None


class RefusingParser(argparse.ArgumentParser):
    """Reports a parse error as the same JSON refusal the subcommands print, for the subcommand
    in argv (argparse raises unrecognized arguments from the top-level parser)."""

    def error(self, message: str) -> NoReturn:
        root, command = argv_command(sys.argv[1:])
        refuse_command(command, root, message)


def check_channel(args: argparse.Namespace) -> None:
    """Refuse a `--channel` that is not at least four digits."""
    value = getattr(args, "channel", None)
    if value is not None and not CHANNEL_PATTERN.fullmatch(value):
        refuse(args, f"invalid --channel {value!r}: expected at least four digits")


def check_session(args: argparse.Namespace) -> None:
    """Refuse a `--session` a printed command could not pass back as its own argument."""
    if not args.session or args.session.startswith("-"):
        refuse(args, f"invalid --session {args.session!r}: must be non-empty and not start with '-'")


def add_session(parser: argparse.ArgumentParser, *, required: bool = False) -> None:
    """`--session`; with `required`, a call with no flag and no environment session refuses."""
    parser.add_argument("--session", default=None,
                        help="this session's id; the environment normally supplies it")
    parser.set_defaults(session_required=required)


def resolve_session(args: argparse.Namespace) -> None:
    """Fill `args.session` from the environment; refuse when a command needs it and none is set."""
    if not hasattr(args, "session"):
        return
    args.session = clikit.session_id(args.session)
    if args.session is None and args.session_required:
        refuse_missing_session(args)


def check_role(args: argparse.Namespace, value: str, flag: str) -> None:
    if value not in ROLES:
        refuse(args, f"invalid {flag} {value!r}: must be listener or asker", category="invalid_role")


def script_command(args: argparse.Namespace, root: Path) -> str:
    """This script's invocation, with `--root` whenever it was given or is not the default."""
    command = clikit.gear_command("advisor", "channel")
    if args.root is not None or root != DEFAULT_ROOT:
        command += f" --root {shlex.quote(str(root))}"
    return command


def receive_next(args: argparse.Namespace, root: Path, role: str) -> str:
    """Tell the caller how to keep receiving after a message changes the inbox."""
    receive = f"{script_command(args, root)} receive --channel {args.channel} --for {role} --timeout 300"
    return (f"fetch and answer each message before running `{receive}` again; "
            "a receive call with a message still unread returns it at once")


def heartbeat_reminder(args: argparse.Namespace, root: Path, record: dict[str, object]) -> str | None:
    """The restart line for the caller's own heartbeat, or None while its seat is fresh.

    The seat owner is the session that registered it, so the command names the same session."""
    role = args.recipient
    owner = record.get(f"{role}_owner")
    if seat_beating(record, role) or owner is None:
        return None
    seat = argparse.Namespace(root=args.root, role=role, session=owner)
    return ("your heartbeat is not running: start it in a new background session first: "
            f"{heartbeat_command(seat, root, args.channel)}")


def session_flag(session: str) -> str:
    """` --session <id>` when `session` differs from the environment session, else empty."""
    return "" if session == clikit.session_id() else f" --session {shlex.quote(session)}"


def heartbeat_command(args: argparse.Namespace, root: Path, channel: str) -> str:
    """The `heartbeat` invocation for this seat, with `--session`, `--interval` and `--max-age` only
    when they differ from the environment session or the default."""
    command = (f"{script_command(args, root)} heartbeat --channel {channel} "
               f"--role {args.role}{session_flag(args.session)}")
    interval = getattr(args, "interval", HEARTBEAT_INTERVAL_SECONDS)
    max_age = getattr(args, "max_age", HEARTBEAT_MAX_AGE_SECONDS)
    if interval != HEARTBEAT_INTERVAL_SECONDS:
        command += f" --interval {exact(interval)}"
    if max_age != HEARTBEAT_MAX_AGE_SECONDS:
        command += f" --max-age {exact(max_age)}"
    return command


def exact(value: float) -> str:
    """`value` as text that parses back to the same float."""
    return str(int(value)) if float(value).is_integer() else repr(float(value))


def print_registered(args: argparse.Namespace, root: Path, record: dict[str, object]) -> None:
    output = brief_record(record)
    output["note"] = ("run next in the background for as long as this session uses the channel; "
                      "the seat reads stale without it")
    output["next"] = heartbeat_command(args, root, str(record["channel"]))
    emit(args, output)
