"""Receive one advisor reply, allowing time while the worker's slate makes progress."""

from __future__ import annotations

import argparse
import json
import math
import re
import shlex
import subprocess
from collections.abc import Callable
from typing import Any

from bootgear_cli.clikit import gear_argv, gear_command

from . import assignments, ledger, protocol
from .cli_common import _read, _refuse, emit
from .model import Slate

AdvisorCall = Callable[..., tuple[int, dict[str, Any]]]


def _progressed(previous: Slate, current: Slate, worker: str) -> bool:
    if len(previous.events) == len(current.events):
        return False
    if protocol.slate_phase(previous) != protocol.slate_phase(current):
        return True
    claims = {claim.id for claim in current.claims.values()
              if claim.finder == worker or (protocol.fresh_eye_role(current, claim) == "r2"
                 and assignments.claim_owner(current, claim, "r2") == worker)}
    return any(event.get("as") == worker or event.get("claim") in claims
               for event in current.events[len(previous.events):])


def receive_reply(read_slate: Callable[[], Slate], call: AdvisorCall, worker: str,
                  channel: str, request: str, timeout: float) -> dict[str, Any]:
    slate = read_slate()
    quiet = 0
    receives = 0
    while quiet < 5:
        status, data = call("receive", "--channel", channel, "--for", "asker", "--timeout", str(timeout))
        receives += 1
        if status not in (0, 1):
            raise ledger.LedgerError([f"advisor receive on {channel}: {data.get('error', data)}"])
        for message in data.get("messages", []):
            if message["kind"] == "response" and message.get("parent_id") == request:
                return {"channel": channel, "message_id": message["message_id"],
                        "parent_id": request, "receives": receives}
        if data.get("peer_live") is not True:
            raise ledger.LedgerError([f"advisor worker {worker}: reserved listener is unavailable on {channel}"])
        unread = data.get("unread", [])
        for message in unread:
            if message["kind"] != "response":
                raise ledger.LedgerError([f"advisor worker {worker}: unexpected {message['kind']} message"])
            status, fetched = call("fetch", "--channel", channel, "--message-id", message["message_id"])
            if status != 0:
                raise ledger.LedgerError([f"advisor fetch on {channel}: {fetched.get('error', fetched)}"])
        current = read_slate()
        if _progressed(slate, current, worker):
            quiet = 0
        elif not unread:
            quiet += 1
        slate = current
    raise ledger.LedgerError([f"advisor worker {worker}: five receives without relevant progress on {channel}"])


def _call(*args: str) -> tuple[int, dict[str, Any]]:
    try:
        result = subprocess.run([*gear_argv("advisor", "channel"), *args, "--json"],
                                capture_output=True, text=True, check=False)
    except OSError as error:
        raise ledger.LedgerError([f"Advisor command unavailable: {error}"]) from error
    try:
        data = json.loads(result.stdout or result.stderr)
    except json.JSONDecodeError as error:
        raise ledger.LedgerError([f"Advisor command exit {result.returncode}: {result.stderr.strip()}"]) from error
    if not isinstance(data, dict):
        raise ledger.LedgerError(["Advisor command must return one JSON object"])
    return result.returncode, data


def cmd_advisor_wait(args: argparse.Namespace) -> None:
    slate = _read(args)
    if (slate.parallelism["r2"] < 2 or slate.mechanism("r2") != "advisor"
            or assignments.workers(slate).get(args.agent) != "r2" or slate.review_group is None):
        _refuse(["advisor-wait requires an assigned parallel advisor worker"])
    if not math.isfinite(args.timeout) or args.timeout < 0:
        _refuse(["advisor-wait --timeout must be a finite duration of zero or more seconds"])
    if not re.fullmatch(r"\d{4,}", args.channel) or not re.fullmatch(r"[0-9a-f]{32}", args.request):
        _refuse(["advisor-wait needs the channel number and message_id returned by the send"])
    try:
        code, data = _call("reservations", "--group", slate.review_group)
        if code != 0:
            raise ledger.LedgerError([f"Advisor reservations: {data.get('error', data)}"])
        if not any(record["channel"] == args.channel and record["reservation"]["worker"] == args.agent
                   for record in data["channels"]):
            raise ledger.LedgerError([f"channel {args.channel} is outside worker {args.agent}'s reservation"])
        result = receive_reply(lambda: _read(args), _call, args.agent, args.channel, args.request, args.timeout)
    except ledger.LedgerError as error:
        _refuse(error.problems)
    command = gear_command("advisor", "channel") + " " + shlex.join(
        ["fetch", "--channel", args.channel, "--message-id", result["message_id"]])
    emit(args.output_mode, result, [f"REPLY {args.agent} {result['message_id']}"],
         command + " then verify the worker's recorded actions")
