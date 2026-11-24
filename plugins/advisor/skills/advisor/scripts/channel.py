#!/usr/bin/env python3
"""Owner-only numbered mailbox for Claude Code / Codex advisor pairs."""

from __future__ import annotations

import argparse

from bootgear_cli import clikit
from bootgear_cli.clikit import current_program
from channel_liveness import (  # noqa: F401
    HEARTBEAT_INTERVAL_SECONDS,
    HEARTBEAT_MAX_AGE_SECONDS,
    hook_touch,
    owned_channels,
)
from channel_messages import DEFAULT_PENDING_CAP, listener_can_ask, fetch, receive, send  # noqa: F401
from channel_output import (
    EXAMPLES,
    RefusingParser,
    add_session,
    check_channel,
    heartbeat_command,  # noqa: F401
    resolve_session,
)
from channel_reservations import launch, reservations, reserve, wait_listener
from channel_seats import (  # noqa: F401
    channel_status,
    close,
    heartbeat,
    list_channels,
    register,
    render_status,
    state,
    status,
    whoami,
)
from channel_store import (  # noqa: F401
    DEFAULT_ROOT,
    caller_path,
    channel_dir,
    fail,
    root_from,
    safe_name,
)


def add_channel(parser: argparse.ArgumentParser, required: bool = True) -> None:
    parser.add_argument("--channel", required=required,
                        help="paired mailbox number, at least four digits; register can allocate one")


def add_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", help="override the mailbox root")


def add_output(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true", help="print JSON instead of prose")
    parser.add_argument("--prose", action="store_true", help="print prose (the default)")


def build_parser() -> argparse.ArgumentParser:
    program = current_program("advisor", "channel")
    parser = RefusingParser(prog=program, description=__doc__)
    add_root(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)

    register_parser = subparsers.add_parser("register")
    add_channel(register_parser, required=False)
    register_parser.add_argument("--role", required=True, metavar="{asker,listener}", help="seat to register")
    register_parser.add_argument("--group", help="review group for an invited listener")
    register_parser.add_argument("--worker", help="worker ID for an invited listener")
    register_parser.add_argument("--invitation", help="reservation token for an invited listener")
    add_session(register_parser, required=True)
    add_output(register_parser)
    register_parser.set_defaults(handler=register)

    for name, handler in (("reserve", reserve), ("launch", launch), ("wait-listener", wait_listener)):
        reserved = subparsers.add_parser(name)
        reserved.add_argument("--group", required=True, metavar="GROUP", help="saved review group")
        reserved.add_argument("--worker", required=True, metavar="ID", help="worker's assigned agent ID")
        add_session(reserved, required=True)
        add_output(reserved)
        reserved.set_defaults(handler=handler)
        if name == "launch":
            reserved.add_argument("--template", required=True,
                                  help="approved command with separate {group}, {worker}, {invitation} arguments")
            reserved.add_argument("--retry", action="store_true",
                                  help="use the single recovery attempt before any listener claims the seat")
        elif name == "wait-listener":
            reserved.add_argument("--timeout", type=float, default=300,
                                  help="maximum seconds to wait for this listener's heartbeat (default: 300)")

    reservations_parser = subparsers.add_parser("reservations")
    reservations_parser.add_argument("--group", required=True, metavar="GROUP", help="saved review group")
    add_session(reservations_parser, required=True)
    add_output(reservations_parser)
    reservations_parser.set_defaults(handler=reservations)

    init_parser = subparsers.add_parser("init")
    add_channel(init_parser)
    add_output(init_parser)
    init_parser.set_defaults(handler=lambda args: print(channel_dir(root_from(args), args.channel)))

    send_parser = subparsers.add_parser("send")
    add_channel(send_parser)
    send_parser.add_argument("--from", dest="sender", required=True, metavar="{asker,listener}", help="sending seat")
    send_parser.add_argument("--to", dest="recipient", required=True, metavar="{asker,listener}", help="receiving seat; must differ from --from")
    send_parser.add_argument("--kind", required=True, metavar="{request,response,stop}", help="message kind")
    send_parser.add_argument("--parent-id", help="request message id from receive; required for a response. It must name a request from --to to --from")
    send_parser.add_argument("--body-file", required=True, help="UTF-8 message file; '-' reads stdin")
    send_parser.add_argument("--cap", type=int, default=None, help=f"pending-message cap, default {DEFAULT_PENDING_CAP}")
    add_output(send_parser)
    send_parser.set_defaults(handler=send)

    receive_parser = subparsers.add_parser("receive")
    add_channel(receive_parser)
    receive_parser.add_argument("--for", dest="recipient", required=True, metavar="{asker,listener}", help="seat receiving the next message")
    receive_parser.add_argument("--timeout", type=float, default=300.0, help="maximum wait in seconds (default: 300)")
    receive_parser.add_argument("--poll", type=float, default=0.5, help="poll interval in seconds (default: 0.5)")
    add_output(receive_parser)
    receive_parser.set_defaults(handler=receive)

    fetch_parser = subparsers.add_parser("fetch")
    add_channel(fetch_parser)
    fetch_parser.add_argument("--message-id", required=True, help="message id returned by receive; prints the full body")
    add_output(fetch_parser)
    fetch_parser.set_defaults(handler=fetch)

    state_parser = subparsers.add_parser("state")
    add_channel(state_parser)
    state_parser.add_argument("--role", required=True, metavar="{asker,listener}", help="seat whose state changes")
    state_parser.add_argument("--value", required=True, metavar="{waiting,busy,closed}", help="new seat state")
    add_output(state_parser)
    state_parser.set_defaults(handler=state)

    close_parser = subparsers.add_parser("close")
    add_channel(close_parser)
    close_parser.add_argument("--role", required=True, metavar="{asker,listener}", help="seat closing the channel")
    close_parser.add_argument("--if-peer-stale", dest="if_peer_stale", action="store_true",
                              help="require a stale peer and empty inbox; a listener also needs 24 empty rounds")
    add_output(close_parser)
    close_parser.set_defaults(handler=close)

    heartbeat_parser = subparsers.add_parser("heartbeat")
    add_channel(heartbeat_parser)
    heartbeat_parser.add_argument("--role", required=True, metavar="{asker,listener}", help="seat whose liveness is maintained")
    add_session(heartbeat_parser, required=True)
    heartbeat_parser.add_argument("--interval", type=float, default=HEARTBEAT_INTERVAL_SECONDS, help="seconds between heartbeat writes (default: 3)")
    heartbeat_parser.add_argument("--max-age", dest="max_age", type=float, default=HEARTBEAT_MAX_AGE_SECONDS, help="stop after this many seconds (default: 6180)")
    add_output(heartbeat_parser)
    heartbeat_parser.set_defaults(handler=heartbeat)

    list_parser = subparsers.add_parser("list")
    list_parser.add_argument("--live-for", dest="live_for", default=None, metavar="{asker,listener}", help="list live peers available to this seat")
    add_session(list_parser)
    list_parser.add_argument("--wait", type=float, default=None, help="seconds to wait for a live peer")
    add_output(list_parser)
    list_parser.set_defaults(handler=list_channels)

    status_parser = subparsers.add_parser("status")
    add_channel(status_parser)
    add_output(status_parser)
    status_parser.set_defaults(handler=status)

    whoami_parser = subparsers.add_parser("whoami")
    add_session(whoami_parser, required=True)
    add_output(whoami_parser)
    whoami_parser.set_defaults(handler=whoami)

    clikit.add_help_examples(parser, clikit.Catalog(prog=program, examples=EXAMPLES))
    return parser


if __name__ == "__main__":
    arguments = build_parser().parse_args()
    check_channel(arguments)
    resolve_session(arguments)
    try:
        arguments.handler(arguments)
    except SystemExit:
        raise
    except Exception as error:  # noqa: BLE001
        fail(f"{type(error).__name__}: {error}")
