"""Send, receive, and fetch advisor mailbox messages."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path

from channel_liveness import seat_beating, seat_busy, seat_live, seat_restarting
from channel_output import (
    check_role,
    emit,
    heartbeat_reminder,
    receive_next,
    refuse,
    script_command,
)
from channel_store import (
    atomic_write,
    channel_dir,
    channel_lock,
    closed_channel,
    fail,
    other_role,
    read_body,
    read_channel_record,
    root_from,
    safe_name,
)

KINDS = {"request", "response", "stop"}
MESSAGE_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
DEFAULT_PENDING_CAP = 2
PREVIEW_WORDS = 10
HISTORY_SIZE = 3


def message_files(path: Path):
    return sorted((path / "messages").glob("*.json"))


def is_request_between(path: Path, message_id: str, sender: str, recipient: str) -> bool:
    """True when `message_id` is a request on this channel from `sender` to `recipient`."""
    message_path = path / "messages" / f"{message_id}.json"
    if not message_path.exists():
        return False
    message = json.loads(message_path.read_text(encoding="utf-8"))
    return (message.get("kind") == "request" and message.get("sender") == sender
            and message.get("recipient") == recipient)


def send(args: argparse.Namespace) -> None:
    check_role(args, args.sender, "--from")
    check_role(args, args.recipient, "--to")
    if args.sender == args.recipient:
        refuse(args, "--from and --to must differ", category="invalid_role")
    if args.kind not in KINDS:
        refuse(args, f"invalid --kind {args.kind!r}: must be request, response, or stop")
    if args.kind == "response" and not args.parent_id:
        refuse(args, "--kind response requires --parent-id")
    if args.parent_id is not None and not MESSAGE_ID_PATTERN.fullmatch(args.parent_id):
        refuse(args, f"invalid --parent-id {args.parent_id!r}: use the message_id receive printed")
    if args.body_file == "-" and sys.stdin.isatty():
        refuse(args, "--body-file - requires piped input")

    root = root_from(args)
    path = channel_dir(root, args.channel)
    record = read_channel_record(path)
    if record.get("state") == "closed":
        closed_channel(args.channel)

    try:
        body = read_body(args.body_file)
    except (OSError, UnicodeDecodeError) as error:
        refuse(args, f"cannot read --body-file: {error}")
    if not body.strip():
        refuse(args, "message body is empty")
    lock = channel_lock(path)
    try:
        if args.kind != "stop" and seat_live(read_channel_record(path), args.recipient) is not True:
            fail(
                f"{args.recipient} on channel {args.channel} has no live heartbeat",
                category="peer_not_live",
                next_step=f"tell the user the {args.recipient} is gone; a new {args.recipient} has to start and pair",
            )
        if args.parent_id is not None and not is_request_between(
                path, args.parent_id, sender=args.recipient, recipient=args.sender):
            fail(
                f"no request {args.parent_id} from {args.recipient} to {args.sender} on channel {args.channel}",
                category="unknown_parent_id",
                next_step="reply with the message_id of a request you received on this channel",
            )
        pending = [
            f for f in message_files(path)
            if (loaded := json.loads(f.read_text(encoding="utf-8"))).get("recipient") == args.recipient
            and loaded.get("kind") != "stop"
            and not loaded.get("read")
        ]
        cap = args.cap if args.cap is not None else DEFAULT_PENDING_CAP
        if len(pending) >= cap:
            fail(
                f"{args.recipient} inbox already has {len(pending)} message(s) "
                f"(cap {cap}); wait for it to catch up before sending more"
            )
        message_id = uuid.uuid4().hex
        message = {
            "version": 2,
            "message_id": message_id,
            "channel": args.channel,
            "sender": args.sender,
            "recipient": args.recipient,
            "kind": args.kind,
            "parent_id": args.parent_id,
            "created_at": time.time(),
            "body": body,
        }
        atomic_write(path / "messages" / f"{message_id}.json", json.dumps(message, ensure_ascii=False) + "\n")
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()
    emit(args, {"message_id": message_id, "channel": args.channel,
                "next": receive_next(args, root, args.sender)})


def preview_of(body: str, words: int = PREVIEW_WORDS) -> str:
    parts = body.split()
    preview = " ".join(parts[:words])
    return preview + ("…" if len(parts) > words else "")


def summarize(message: dict[str, object]) -> dict[str, object]:
    summary = {
        "message_id": message.get("message_id"),
        "sender": message.get("sender"),
        "kind": message.get("kind"),
        "preview": preview_of(str(message.get("body", ""))),
    }
    if message.get("parent_id"):
        summary["parent_id"] = message["parent_id"]
    return summary


def summarize_for(message: dict[str, object], answered: set[object]) -> dict[str, object]:
    """`summarize`, plus whether the caller already sent a response to this request."""
    summary = summarize(message)
    if message.get("kind") == "request":
        summary["answered"] = message.get("message_id") in answered
    return summary


def receive(args: argparse.Namespace) -> None:
    check_role(args, args.recipient, "--for")
    root = root_from(args)
    path = channel_dir(root, args.channel)
    record = read_channel_record(path)
    if record.get("state") == "closed":
        closed_channel(args.channel)

    wait_lock_path = path / f"receive-{args.recipient}.lock"
    wait_lock_path.touch(mode=0o600, exist_ok=True)
    os.chmod(wait_lock_path, 0o600)
    wait_lock = wait_lock_path.open("r+")
    try:
        fcntl.flock(wait_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fail(
            f"another receive for {args.recipient} on channel {args.channel} is already waiting; "
            "wait for it or check its result instead of starting a second one"
        )

    try:
        def inbox() -> list[Path]:
            return [
                f for f in message_files(path)
                if json.loads(f.read_text(encoding="utf-8")).get("recipient") == args.recipient
            ]

        def unread_count(files: list[Path]) -> int:
            return sum(
                1 for f in files
                if not json.loads(f.read_text(encoding="utf-8")).get("read")
            )

        peer = other_role(args.recipient)
        deadline = time.monotonic() + args.timeout
        while True:
            peer_record = read_channel_record(path)
            peer_live = seat_live(peer_record, peer)
            current = inbox()
            pending = unread_count(current)
            if pending > 0 or args.timeout <= 0 or peer_live is False:
                break
            if time.monotonic() >= deadline:
                current = inbox()
                pending = unread_count(current)
                break
            time.sleep(args.poll)
    finally:
        fcntl.flock(wait_lock, fcntl.LOCK_UN)
        wait_lock.close()

    messages = [json.loads(f.read_text(encoding="utf-8")) for f in current]
    messages.sort(key=lambda m: m.get("created_at", 0), reverse=True)
    recent = messages[:HISTORY_SIZE]
    sent = [json.loads(f.read_text(encoding="utf-8")) for f in message_files(path)]
    answered = {m.get("parent_id") for m in sent
                if m.get("sender") == args.recipient and m.get("kind") == "response"}
    output = {
        "new_since_call": pending,
        "messages": [summarize_for(m, answered) for m in recent],
        "peer_live": peer_live,
    }
    script = script_command(args, root)
    if pending == 0:
        read = "; the messages listed were already read" if recent else ""
        reminder = heartbeat_reminder(args, root, peer_record)
        if peer_live is False:
            output["note"] = (
                f"no new message for {args.recipient} on channel {args.channel} "
                f"within {args.timeout:g}s{read} — peer heartbeat stale; tell the user instead of waiting again"
            )
            if reminder:
                output["next"] = reminder
            emit(args, output, ensure_ascii=False)
            raise SystemExit(1)
        if args.recipient == "asker" and seat_busy(peer_record, peer):
            wait = ("the listener is busy on this request, so keep waiting: run receive again "
                    "with --timeout 300; busy waits do not count toward the 12 quiet waits, "
                    "up to 12 of them")
        elif args.recipient == "asker":
            wait = ("a reply can take many minutes, so run receive again with a long "
                    "--timeout (e.g. 300) instead of giving up or resending; up to 12 "
                    "waits of 300s before reporting the peer unavailable")
        else:
            wait = ("a request can come at any time, so run receive again with a long "
                    "--timeout (e.g. 300)")
        if not seat_beating(peer_record, peer) and seat_restarting(peer_record, peer):
            wait = f"the {peer} is restarting its heartbeat, so keep waiting; {wait}"
        output["note"] = (
            f"no new message for {args.recipient} on channel {args.channel} "
            f"within {args.timeout:g}s{read} — {wait}"
        )
        receive_again = f"{script} receive --channel {args.channel} --for {args.recipient} --timeout 300"
        output["next"] = f"{reminder}\nthen run: {receive_again}" if reminder else receive_again
        emit(args, output, ensure_ascii=False)
        raise SystemExit(1)
    unread = next(m for m in messages if not m.get("read"))
    output["note"] = (
        "fetch each unread message by its message_id to mark it read before calling receive again — "
        "a receive call with a message still unread returns it at once"
    )
    fetch = f"{script} fetch --channel {args.channel} --message-id {unread['message_id']}"
    reminder = heartbeat_reminder(args, root, peer_record)
    output["next"] = f"{fetch}\nthen: {reminder}" if reminder else fetch
    emit(args, output, ensure_ascii=False)


def fetch(args: argparse.Namespace) -> None:
    if not safe_name(args.message_id):
        refuse(args, f"invalid --message-id {args.message_id!r}: use the message_id receive printed")
    root = root_from(args)
    path = channel_dir(root, args.channel)
    read_channel_record(path)
    message_path = path / "messages" / f"{args.message_id}.json"
    if not message_path.exists():
        fail(f"no such message on channel {args.channel}: {args.message_id}")
    lock = channel_lock(path)
    try:
        message = json.loads(message_path.read_text(encoding="utf-8"))
        output = {"body": message.get("body"), "kind": message.get("kind"),
                  "next": receive_next(args, root, message["recipient"])}
        if message.get("parent_id"):
            output["parent_id"] = message["parent_id"]
        if not message.get("read"):
            message["read"] = True
            atomic_write(message_path, json.dumps(message, ensure_ascii=False) + "\n")
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()
    emit(args, output, ensure_ascii=False)
