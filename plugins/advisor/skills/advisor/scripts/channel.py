#!/usr/bin/env python3
"""Owner-only numbered mailbox for Claude Code / Codex advisor pairs."""

from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
import re
import secrets
import shlex
import signal
import sys
import time
import uuid
from pathlib import Path
from typing import NoReturn

DEFAULT_ROOT = Path.home() / ".bootgear" / "advisor"
ROLES = {"listener", "asker"}
KINDS = {"request", "response", "stop"}
CHANNEL_PATTERN = re.compile(r"^[0-9]{4,}$")
DEFAULT_PENDING_CAP = 2
PREVIEW_WORDS = 10
HISTORY_SIZE = 3
LIVE_CANDIDATE_WINDOW_SECONDS = 48 * 3600
HEARTBEAT_INTERVAL_SECONDS = 3
HEARTBEAT_TTL_SECONDS = 10
HEARTBEAT_MAX_FAILURES = 3
HEARTBEAT_MAX_AGE_SECONDS = 6180
# A max_age stop keeps the seat live this long for the restart; max-age + grace stays under
# Claude Code's 2-hour background task cap.
RESTART_GRACE_SECONDS = 720
COMMANDS = ("register", "init", "send", "receive", "fetch", "state", "close", "heartbeat", "list", "status")
EXAMPLES = {
    "register": 'register --role asker --channel 0001 --session "$SESSION_ID"',
    "init": "init --channel 0001",
    "send": "send --channel 0001 --from asker --to listener --kind request --body-file -",
    "receive": "receive --channel 0001 --for asker --timeout 300",
    "fetch": "fetch --channel 0001 --message-id MESSAGE_ID",
    "state": "state --channel 0001 --role listener --value waiting",
    "close": "close --channel 0001 --role listener",
    "heartbeat": 'heartbeat --channel 0001 --role listener --session "$SESSION_ID"',
    "list": 'list --live-for asker --session "$SESSION_ID"',
    "status": "status --channel 0001",
}


def fail(message: str, category: str | None = None, next_step: str | None = None,
         extra: dict[str, str] | None = None) -> NoReturn:
    payload = {"error": message}
    if category is not None:
        payload["category"] = category
    if next_step is not None:
        payload["next"] = next_step
    payload.update(extra or {})
    print(json.dumps(payload), file=sys.stderr)
    raise SystemExit(2)


def invocation(root_value: str | None) -> str:
    """This script's invocation for a `--root` value, without creating the root: an absolute
    `--root` whenever one was given or `BOOTGEAR_ADVISOR_DIR` moves it off the default."""
    command = f"python3 {shlex.quote(str(Path(__file__).resolve()))}"
    configured = root_value or os.environ.get("BOOTGEAR_ADVISOR_DIR")
    if configured:
        root = caller_path(configured)
        if root_value is not None or root != DEFAULT_ROOT:
            command += f" --root {shlex.quote(str(root))}"
    return command


def refuse_command(command: str | None, root_value: str | None, message: str,
                   category: str = "invalid_args") -> NoReturn:
    """An argument refusal of `command`, with one correct invocation and the other subcommands."""
    fail(message, category=category, next_step="run the command again with corrected arguments, as in example",
         extra={
             "example": f"{invocation(root_value)} {EXAMPLES[command or 'list']}",
             "commands": ", ".join(c for c in COMMANDS if c != command),
         })


def refuse(args: argparse.Namespace, message: str, category: str = "invalid_args") -> NoReturn:
    refuse_command(args.command, args.root, message, category)


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


def check_role(args: argparse.Namespace, value: str, flag: str) -> None:
    if value not in ROLES:
        refuse(args, f"invalid {flag} {value!r}: must be listener or asker", category="invalid_role")


def safe_name(value: str) -> bool:
    return bool(value) and value not in {".", ".."} and all(
        char in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for char in value
    )


def closed_channel(channel: str) -> NoReturn:
    fail(f"channel is closed: {channel}", category="channel_closed",
         next_step=f"stop using channel {channel} and tell the user; continuing needs a new pairing")


def safe_channel(value: str) -> str:
    if not CHANNEL_PATTERN.fullmatch(value):
        fail(f"invalid channel: {value!r}; expected at least four digits")
    return value


def other_role(role: str) -> str:
    return "asker" if role == "listener" else "listener"


def caller_path(value: str) -> Path:
    """`value` resolved against the caller's cwd (`GEAR_CALLER_CWD` under gear)."""
    path = Path(value).expanduser()
    return path if path.is_absolute() else Path(os.environ.get("GEAR_CALLER_CWD") or os.getcwd()) / path


def root_from(args: argparse.Namespace) -> Path:
    configured = args.root or os.environ.get("BOOTGEAR_ADVISOR_DIR")
    root = caller_path(configured) if configured else DEFAULT_ROOT
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    (root / "channels").mkdir(mode=0o700, exist_ok=True)
    os.chmod(root / "channels", 0o700)
    return root


def channel_dir(root: Path, channel: str, create: bool = True) -> Path:
    channel = safe_channel(channel)
    path = root / "channels" / channel
    if create:
        (path / "messages").mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(path / "messages", 0o700)
        os.chmod(path, 0o700)
    return path


def atomic_write(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    temporary.write_text(content, encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    os.chmod(path, 0o600)


def read_body(body_file: str) -> str:
    path = None if body_file == "-" else caller_path(body_file)
    body = sys.stdin.read() if path is None else path.read_text(encoding="utf-8")
    return body.rstrip()


def channel_lock(path: Path):
    lock_path = path / "channel.lock"
    lock_path.touch(mode=0o600, exist_ok=True)
    os.chmod(lock_path, 0o600)
    handle = lock_path.open("r+")
    fcntl.flock(handle, fcntl.LOCK_EX)
    return handle


def read_channel_record(path: Path) -> dict[str, object]:
    record_path = path / "channel.json"
    if not record_path.exists():
        fail(f"channel does not exist: {path.name}")
    try:
        return json.loads(record_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        fail(f"channel metadata is invalid: {error}")


def new_record(channel: str) -> dict[str, object]:
    now = time.time()
    return {
        "channel": channel,
        "created_at": now,
        "updated_at": now,
        "state": "waiting",
        "listener_owner": None,
        "asker_owner": None,
    }


def brief_record(record: dict[str, object]) -> dict[str, object]:
    return {
        "channel": record.get("channel"),
        "listener_owner": record.get("listener_owner"),
        "asker_owner": record.get("asker_owner"),
    }


def script_command(args: argparse.Namespace, root: Path) -> str:
    """This script's invocation, with `--root` whenever it was given or is not the default."""
    command = f"python3 {shlex.quote(str(Path(__file__).resolve()))}"
    if args.root is not None or root != DEFAULT_ROOT:
        command += f" --root {shlex.quote(str(root))}"
    return command


def heartbeat_command(args: argparse.Namespace, root: Path, channel: str) -> str:
    """The `heartbeat` invocation for this seat, with `--interval`/`--max-age` when not the default."""
    command = (f"{script_command(args, root)} heartbeat --channel {channel} "
               f"--role {args.role} --session {shlex.quote(args.session)}")
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
    print(json.dumps(output))


def register(args: argparse.Namespace) -> None:
    if args.role not in ROLES:
        refuse(args, "role must be listener or asker", category="invalid_role")
    check_session(args)
    owner_key = f"{args.role}_owner"
    root = root_from(args)
    session = args.session

    if args.channel:
        path = channel_dir(root, args.channel)
        lock = channel_lock(path)
        try:
            record = read_channel_record(path) if (path / "channel.json").exists() else new_record(args.channel)
            if record.get("state") == "closed":
                fail(f"channel {args.channel} is closed", category="channel_closed")
            current_owner = record.get(owner_key)
            if current_owner not in (None, session):
                fail(
                    f"{args.role} slot on channel {args.channel} is already claimed by another session",
                    category="seat_claimed",
                )
            record[owner_key] = session
            record[f"{args.role}_seen_at"] = time.time()
            record.pop(f"{args.role}_restart_until", None)
            record["updated_at"] = time.time()
            atomic_write(path / "channel.json", json.dumps(record) + "\n")
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
            lock.close()
        print_registered(args, root, record)
        return

    # No --channel: allocate the next number and create fresh, claiming `role`.
    allocator_lock_path = root / "allocator.lock"
    allocator_lock_path.touch(mode=0o600, exist_ok=True)
    os.chmod(allocator_lock_path, 0o600)
    with allocator_lock_path.open("r+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        existing = [
            int(p.name)
            for p in (root / "channels").iterdir()
            if p.is_dir() and p.name.isdigit()
        ]
        channel = f"{max(existing, default=0) + 1:04d}"
        path = channel_dir(root, channel)
        record = new_record(channel)
        record[owner_key] = session
        record[f"{args.role}_seen_at"] = time.time()
        atomic_write(path / "channel.json", json.dumps(record) + "\n")
        fcntl.flock(lock, fcntl.LOCK_UN)
    print_registered(args, root, record)


def write_state(args: argparse.Namespace, value: str, check=None) -> None:
    """Record `value` for `args.role` under the channel lock, after `check(record)` passes. Closing
    drops both seats' restart grace, so no seat reads live on a closed channel past its stamp."""
    root = root_from(args)
    path = channel_dir(root, args.channel)
    lock = channel_lock(path)
    try:
        record = read_channel_record(path)
        if check is not None:
            check(root, path, record)
        record.update({"state": value, "state_role": args.role, "updated_at": time.time()})
        if value == "closed":
            for role in ROLES:
                record.pop(f"{role}_restart_until", None)
        atomic_write(path / "channel.json", json.dumps(record) + "\n")
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()
    print(json.dumps(record))


def state(args: argparse.Namespace) -> None:
    check_role(args, args.role, "--role")
    if args.value not in {"waiting", "busy", "closed"}:
        refuse(args, f"invalid --value {args.value!r}: must be waiting, busy, or closed")
    write_state(args, args.value)


def close(args: argparse.Namespace) -> None:
    check_role(args, args.role, "--role")
    if not args.if_peer_stale:
        write_state(args, "closed")
        return
    peer = other_role(args.role)

    def peer_stale_and_inbox_empty(root: Path, path: Path, record: dict[str, object]) -> None:
        if record.get("state") == "closed":
            return
        if seat_live(record, peer) is True:
            message, category = f"the {peer} on channel {args.channel} is live", "peer_live"
        elif any(not (m := json.loads(f.read_text(encoding="utf-8"))).get("read")
                 and m.get("recipient") == args.role for f in message_files(path)):
            message, category = f"channel {args.channel} has an unread message for {args.role}", "unread_message"
        else:
            return
        fail(f"{message}; the channel stays open", category=category,
             next_step=(f"keep listening: run `{script_command(args, root)} receive --channel {args.channel} "
                        f"--for {args.role} --timeout 300`"))

    write_state(args, "closed", peer_stale_and_inbox_empty)


def _as_float(value: object) -> float | None:
    return value if isinstance(value, (int, float)) else None


def _stamp(value: object) -> float | None:
    """`value` as a finite positive timestamp, or None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        return None
    return float(value)


def seat_fresh(record: dict[str, object], role: str) -> bool:
    """Whether `<role>_seen_at` is 0-TTL seconds old."""
    seen = _stamp(record.get(f"{role}_seen_at"))
    return seen is not None and 0 <= time.time() - seen <= HEARTBEAT_TTL_SECONDS


def seat_restarting(record: dict[str, object], role: str) -> bool:
    """Whether the seat is owned and inside the restart grace its max_age stop wrote. A
    `<role>_restart_until` that is invalid or more than the grace ahead counts as absent."""
    until = _stamp(record.get(f"{role}_restart_until"))
    now = time.time()
    return (record.get(f"{role}_owner") is not None and until is not None
            and now < until <= now + RESTART_GRACE_SECONDS)


def seat_live(record: dict[str, object], role: str) -> bool | None:
    """None if nobody holds the seat; else whether it is fresh or inside its restart grace."""
    if record.get(f"{role}_owner") is None:
        return None
    return seat_fresh(record, role) or seat_restarting(record, role)


def status(args: argparse.Namespace) -> None:
    root = root_from(args)
    path = channel_dir(root, args.channel)
    record = read_channel_record(path)
    output = dict(record)
    output["listener_alive"] = seat_live(record, "listener")
    output["asker_alive"] = seat_live(record, "asker")
    print(json.dumps(output))


def message_files(path: Path):
    return sorted((path / "messages").glob("*.json"))


def send(args: argparse.Namespace) -> None:
    check_role(args, args.sender, "--from")
    check_role(args, args.recipient, "--to")
    if args.sender == args.recipient:
        refuse(args, "--from and --to must differ", category="invalid_role")
    if args.kind not in KINDS:
        refuse(args, f"invalid --kind {args.kind!r}: must be request, response, or stop")
    if args.kind == "response" and not args.parent_id:
        refuse(args, "--kind response requires --parent-id")
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
    print(json.dumps({"message_id": message_id, "channel": args.channel}))


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

        deadline = time.monotonic() + args.timeout
        while True:
            current = inbox()
            pending = unread_count(current)
            if pending > 0 or args.timeout <= 0:
                break
            if time.monotonic() >= deadline:
                current = inbox()
                pending = unread_count(current)
                break
            time.sleep(args.poll)
    finally:
        fcntl.flock(wait_lock, fcntl.LOCK_UN)
        wait_lock.close()

    peer_record = read_channel_record(path)
    peer = other_role(args.recipient)
    peer_live = seat_live(peer_record, peer)
    messages = [json.loads(f.read_text(encoding="utf-8")) for f in current]
    messages.sort(key=lambda m: m.get("created_at", 0), reverse=True)
    recent = messages[:HISTORY_SIZE]
    output = {
        "new_since_call": pending,
        "messages": [summarize(m) for m in recent],
        "peer_live": peer_live,
    }
    script = script_command(args, root)
    if pending == 0:
        read = "; the messages listed were already read" if recent else ""
        if peer_live is False:
            output["note"] = (
                f"no new message for {args.recipient} on channel {args.channel} "
                f"within {args.timeout:g}s{read} — peer heartbeat stale; tell the user instead of waiting again"
            )
            print(json.dumps(output, ensure_ascii=False))
            raise SystemExit(1)
        if args.recipient == "asker":
            wait = ("a reply can take many minutes, so run receive again with a long "
                    "--timeout (e.g. 300) instead of giving up or resending; up to 5 "
                    "waits of 300s before reporting the peer unavailable")
        else:
            wait = ("a request can come at any time, so run receive again with a long "
                    "--timeout (e.g. 300)")
        if not seat_fresh(peer_record, peer) and seat_restarting(peer_record, peer):
            wait = f"the {peer} is restarting its heartbeat, so keep waiting; {wait}"
        output["note"] = (
            f"no new message for {args.recipient} on channel {args.channel} "
            f"within {args.timeout:g}s{read} — {wait}"
        )
        output["next"] = f"{script} receive --channel {args.channel} --for {args.recipient} --timeout 300"
        print(json.dumps(output, ensure_ascii=False))
        raise SystemExit(1)
    unread = next(m for m in messages if not m.get("read"))
    output["note"] = (
        "fetch each unread message by its message_id to mark it read — "
        "otherwise the next receive call will return it again"
    )
    output["next"] = f"{script} fetch --channel {args.channel} --message-id {unread['message_id']}"
    print(json.dumps(output, ensure_ascii=False))


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
        output = {"body": message.get("body"), "kind": message.get("kind")}
        if message.get("parent_id"):
            output["parent_id"] = message["parent_id"]
        if not message.get("read"):
            message["read"] = True
            atomic_write(message_path, json.dumps(message, ensure_ascii=False) + "\n")
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()
    print(json.dumps(output, ensure_ascii=False))


def all_channels(root: Path) -> list[dict[str, object]]:
    return [
        read_channel_record(root / "channels" / p.name)
        for p in sorted((root / "channels").iterdir())
        if p.is_dir() and p.name.isdigit() and (p / "channel.json").exists()
    ]


def live_candidates(root: Path, my_role: str, session: str) -> list[dict[str, object]]:
    """Open channels updated within the last 48 hours whose peer seat is live and whose
    `my_role` seat is free or held by `session`, most recently updated first."""
    cutoff = time.time() - LIVE_CANDIDATE_WINDOW_SECONDS
    other = other_role(my_role)
    candidates = [
        c for c in all_channels(root)
        if c.get("state") != "closed"
        and max(_as_float(c.get("created_at")) or 0, _as_float(c.get("updated_at")) or 0) >= cutoff
        and seat_live(c, other) is True
        and c.get(f"{my_role}_owner") in (None, session)
    ]
    return sorted(candidates, key=lambda c: _as_float(c.get("updated_at")) or 0, reverse=True)


class HeartbeatStopped(Exception):
    pass


class RecordUnreadable(Exception):
    pass


def pause(seconds: float) -> None:
    """Sleep `seconds`, ending early once the wall clock has moved past them (a system sleep stops the monotonic clock)."""
    wall, monotonic = time.time(), time.monotonic()
    while (elapsed := max(time.time() - wall, time.monotonic() - monotonic)) < seconds:
        time.sleep(min(seconds - elapsed, 1.0))


def beat(path: Path, role: str, session: str, expired: bool) -> str | None:
    """One heartbeat under the channel lock: the reason to stop, or None after stamping `<role>_seen_at`.
    Raises OSError or RecordUnreadable when the seat cannot be read or stamped."""
    lock = channel_lock(path)
    try:
        try:
            record = json.loads((path / "channel.json").read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise RecordUnreadable(f"channel metadata is invalid: {error}") from error
        if not isinstance(record, dict):
            raise RecordUnreadable("channel metadata is not an object")
        if record.get("state") == "closed":
            return "channel_closed"
        if record.get(f"{role}_owner") != session:
            return "seat_taken"
        if expired:
            record[f"{role}_restart_until"] = time.time() + RESTART_GRACE_SECONDS
            atomic_write(path / "channel.json", json.dumps(record) + "\n")
            return "max_age"
        record[f"{role}_seen_at"] = time.time()
        record.pop(f"{role}_restart_until", None)
        atomic_write(path / "channel.json", json.dumps(record) + "\n")
        return None
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


def heartbeat(args: argparse.Namespace) -> None:
    if args.role not in ROLES:
        refuse(args, "role must be listener or asker", category="invalid_role")
    check_session(args)
    if not (math.isfinite(args.interval) and 0 < args.interval <= HEARTBEAT_TTL_SECONDS / 2):
        refuse(args, f"--interval must be above 0 and at most {HEARTBEAT_TTL_SECONDS / 2:g}")
    if not (math.isfinite(args.max_age) and args.max_age > 0):
        refuse(args, "--max-age must be a finite number above 0")
    root = root_from(args)
    path = channel_dir(root, args.channel, create=False)
    if not (path / "channel.json").exists():
        fail(f"channel does not exist: {args.channel}", category="channel_missing",
             next_step="use the channel number register printed")
    restart = heartbeat_command(args, root, args.channel)
    nexts = {
        "channel_closed": f"nothing to restart: channel {args.channel} is closed; stop using it",
        "seat_taken": (f"nothing to restart: another session holds the {args.role} seat on channel "
                       f"{args.channel}; stop using it and tell the user"),
        "max_age": restart,
        "signal": (f"nothing to restart if this session stopped it; if the host stopped it while "
                   f"channel {args.channel} is still in use, run `{restart}`"),
    }

    def on_signal(_signum: int, _frame: object) -> None:
        raise HeartbeatStopped

    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(signum, on_signal)
    try:
        start = time.time()
        failures = 0
        while True:
            try:
                stopped = beat(path, args.role, args.session, time.time() - start >= args.max_age)
            except (OSError, RecordUnreadable) as error:
                failures += 1
                if failures >= HEARTBEAT_MAX_FAILURES:
                    fail(f"heartbeat could not stamp the seat {failures} times in a row: {error}",
                         category="heartbeat_failed",
                         next_step=(f"the seat reads stale; run `{script_command(args, root)} status --channel "
                                    f"{args.channel}`, and if the channel is open, register again with the same "
                                    "session and start a new heartbeat"))
            else:
                failures = 0
                if stopped is not None:
                    output = {"stopped": stopped, "next": nexts[stopped]}
                    if stopped == "seat_taken":
                        output["category"] = "seat_claimed"
                    print(json.dumps(output))
                    raise SystemExit(2 if stopped == "seat_taken" else 0)
            pause(args.interval)
    except HeartbeatStopped:
        print(json.dumps({"stopped": "signal", "next": nexts["signal"]}))


def list_channels(args: argparse.Namespace) -> None:
    if args.wait is not None and not args.live_for:
        refuse(args, "--wait requires --live-for")
    if args.session is not None:
        check_session(args)
    if args.live_for and args.live_for not in ROLES:
        refuse(args, "--live-for must be listener or asker", category="invalid_role")
    if args.live_for and not args.session:
        refuse(args, "--live-for requires --session")
    if args.wait is not None and not (math.isfinite(args.wait) and args.wait >= 0):
        refuse(args, "--wait must be a finite number of seconds, 0 or more")
    root = root_from(args)

    if not args.live_for:
        print(json.dumps({"channels": all_channels(root)}))
        return

    role = args.live_for
    peer = other_role(role)
    script = script_command(args, root)
    session_id = str(args.session)
    session = shlex.quote(session_id)

    deadline = time.monotonic() + (args.wait or 0)
    while not (candidates := live_candidates(root, role, session_id)) and args.wait is not None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            print(json.dumps({
                "channels": [],
                "note": f"no {peer} appeared within {args.wait:g}s; tell the user to start one",
            }))
            raise SystemExit(1)
        time.sleep(min(1.0, remaining))

    if candidates:
        print(json.dumps({
            "channels": candidates,
            "next": f"{script} register --role {role} --channel {candidates[0]['channel']} --session {session}",
        }))
        return
    print(json.dumps({
        "channels": [],
        "note": f"no live {peer} found",
        "next": (f"only if you started the {peer} yourself or the user said one is starting, run "
                 f"`{script} list --live-for {role} --session {session} --wait 120`; "
                 f"otherwise tell the user to start a {peer} and stop"),
    }))


def add_channel(parser: argparse.ArgumentParser, required: bool = True) -> None:
    parser.add_argument("--channel", required=required)


def add_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", help="override the mailbox root")


def build_parser() -> argparse.ArgumentParser:
    parser = RefusingParser(description=__doc__)
    add_root(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)

    register_parser = subparsers.add_parser("register")
    add_channel(register_parser, required=False)
    register_parser.add_argument("--role", required=True)
    register_parser.add_argument("--session", required=True, help="this party's session/process id")
    register_parser.set_defaults(handler=register)

    init_parser = subparsers.add_parser("init")
    add_channel(init_parser)
    init_parser.set_defaults(handler=lambda args: print(channel_dir(root_from(args), args.channel)))

    send_parser = subparsers.add_parser("send")
    add_channel(send_parser)
    send_parser.add_argument("--from", dest="sender", required=True)
    send_parser.add_argument("--to", dest="recipient", required=True)
    send_parser.add_argument("--kind", required=True)
    send_parser.add_argument("--parent-id")
    send_parser.add_argument("--body-file", required=True)
    send_parser.add_argument("--cap", type=int, default=None, help=f"pending-message cap, default {DEFAULT_PENDING_CAP}")
    send_parser.set_defaults(handler=send)

    receive_parser = subparsers.add_parser("receive")
    add_channel(receive_parser)
    receive_parser.add_argument("--for", dest="recipient", required=True)
    receive_parser.add_argument("--timeout", type=float, default=300.0)
    receive_parser.add_argument("--poll", type=float, default=0.5)
    receive_parser.set_defaults(handler=receive)

    fetch_parser = subparsers.add_parser("fetch")
    add_channel(fetch_parser)
    fetch_parser.add_argument("--message-id", required=True)
    fetch_parser.set_defaults(handler=fetch)

    state_parser = subparsers.add_parser("state")
    add_channel(state_parser)
    state_parser.add_argument("--role", required=True)
    state_parser.add_argument("--value", required=True)
    state_parser.set_defaults(handler=state)

    close_parser = subparsers.add_parser("close")
    add_channel(close_parser)
    close_parser.add_argument("--role", required=True)
    close_parser.add_argument("--if-peer-stale", dest="if_peer_stale", action="store_true",
                              help="close only if the peer is not live and nothing unread waits for --role")
    close_parser.set_defaults(handler=close)

    heartbeat_parser = subparsers.add_parser("heartbeat")
    add_channel(heartbeat_parser)
    heartbeat_parser.add_argument("--role", required=True)
    heartbeat_parser.add_argument("--session", required=True, help="the session that registered the seat")
    heartbeat_parser.add_argument("--interval", type=float, default=HEARTBEAT_INTERVAL_SECONDS)
    heartbeat_parser.add_argument("--max-age", dest="max_age", type=float, default=HEARTBEAT_MAX_AGE_SECONDS)
    heartbeat_parser.set_defaults(handler=heartbeat)

    list_parser = subparsers.add_parser("list")
    list_parser.add_argument("--live-for", dest="live_for", default=None)
    list_parser.add_argument("--session", default=None, help="this party's session id, for the printed next step")
    list_parser.add_argument("--wait", type=float, default=None, help="seconds to wait for a live peer")
    list_parser.set_defaults(handler=list_channels)

    status_parser = subparsers.add_parser("status")
    add_channel(status_parser)
    status_parser.set_defaults(handler=status)

    return parser


if __name__ == "__main__":
    arguments = build_parser().parse_args()
    check_channel(arguments)
    try:
        arguments.handler(arguments)
    except SystemExit:
        raise
    except Exception as error:  # noqa: BLE001
        fail(f"{type(error).__name__}: {error}")
