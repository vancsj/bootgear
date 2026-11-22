"""Register, inspect, and maintain advisor seats."""

from __future__ import annotations

import argparse
import fcntl
import json
import math
import signal
import time
from pathlib import Path

from channel_liveness import (
    HEARTBEAT_MAX_FAILURES,
    HEARTBEAT_TTL_SECONDS,
    STATUS_KEYS,
    HeartbeatStopped,
    RecordUnreadable,
    _as_float,
    all_channels,
    beat,
    live_candidates,
    owned_channels,
    pause,
    seat_beating,
    seat_live,
)
from channel_messages import message_files
from channel_output import (
    check_role,
    check_session,
    emit,
    heartbeat_command,
    output_mode,
    print_registered,
    prose_scalar,
    refuse,
    refuse_missing_session,
    script_command,
    session_flag,
)
from channel_reservations import (
    invited_channel,
    public_record,
    require_owner,
    validate_invitation,
)
from channel_store import (
    ROLES,
    allocator_lock,
    atomic_write,
    channel_dir,
    channel_lock,
    closed_channel,
    fail,
    new_record,
    next_channel,
    other_role,
    read_channel_record,
    read_json_object,
    root_from,
)


def register(args: argparse.Namespace) -> None:
    if args.role not in ROLES:
        refuse(args, "role must be listener or asker", category="invalid_role")
    check_session(args)
    owner_key = f"{args.role}_owner"
    root = root_from(args)
    session = args.session

    invited = invited_channel(args, root)
    if invited is not None:
        args.channel = invited
    if args.channel:
        path = channel_dir(root, args.channel)
        lock = channel_lock(path)
        try:
            record = read_channel_record(path) if (path / "channel.json").exists() else new_record(args.channel)
            if record.get("state") == "closed":
                fail(f"channel {args.channel} is closed", category="channel_closed")
            validate_invitation(args, record)
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
    with allocator_lock(root):
        channel = next_channel(root)
        path = channel_dir(root, channel)
        record = new_record(channel)
        record[owner_key] = session
        record[f"{args.role}_seen_at"] = time.time()
        atomic_write(path / "channel.json", json.dumps(record) + "\n")
    print_registered(args, root, record)


def write_state(args: argparse.Namespace, value: str, check=None) -> None:
    """Record `value` for `args.role` under the channel lock, after `check(record)` passes. Closing
    drops both seats' restart grace, so no seat reads live on a closed channel past its stamp."""
    root = root_from(args)
    path = channel_dir(root, args.channel)
    lock = channel_lock(path)
    try:
        record = read_channel_record(path)
        require_owner(record, args.role)
        if record.get("state") == "closed" and value != "closed":
            closed_channel(args.channel)
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
    emit(args, public_record(record))


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


def status(args: argparse.Namespace) -> None:
    root = root_from(args)
    path = channel_dir(root, args.channel, create=False)
    record = read_channel_record(path)
    output = dict(public_record(record))
    output["listener_alive"] = seat_live(record, "listener")
    output["asker_alive"] = seat_live(record, "asker")
    emit(args, output)


def channel_status(root: Path, record: dict[str, object], role: str) -> dict[str, object]:
    """Where `role` stands on the channel in `record`, and the command that resumes it."""
    channel = str(record.get("channel"))
    messages = [m for f in message_files(root / "channels" / channel) if (m := read_json_object(f)) is not None]
    inbox = [m for m in messages if m.get("recipient") == role]
    read = sorted((m for m in inbox if m.get("read")), key=lambda m: _as_float(m.get("created_at")) or 0)
    answered = {m.get("parent_id") for m in messages if m.get("sender") == role and m.get("kind") == "response"}
    owed = [m for m in read if m.get("kind") == "request" and m.get("message_id") not in answered]
    owed_id = owed[-1].get("message_id") if owed else None
    if owed_id is not None:
        step = f"answer request {owed_id}: fetch it again and send the response"
    else:
        step = (f"{script_command(argparse.Namespace(root=None), root)} receive --channel {channel} "
                f"--for {role} --timeout 300")
    beating = seat_beating(record, role)
    owner = record.get(f"{role}_owner")
    if not beating and owner is not None:
        seat = argparse.Namespace(root=None, role=role, session=str(owner))
        step = (f"start in a new background session: {heartbeat_command(seat, root, channel)}\n"
                f"then: {step}")
    return {
        "channel": channel,
        "role": role,
        "state": record.get("state"),
        "peer_live": seat_live(record, other_role(role)),
        "heartbeat": beating,
        "unread": sum(1 for m in inbox if not m.get("read")),
        "last_read": read[-1].get("message_id") if read else None,
        "owed": owed_id,
        "next": step,
    }


def render_status(statuses: list[dict[str, object]]) -> str:
    """One block of `key: value` lines per channel, `next` last, blocks separated by a blank line."""
    return "\n\n".join(
        "\n".join(f"{key}: {'none' if status.get(key) is None else prose_scalar(status.get(key))}"
                  for key in STATUS_KEYS)
        for status in statuses
    )


def whoami(args: argparse.Namespace) -> None:
    check_session(args)
    root = root_from(args)
    statuses = [channel_status(root, record, role) for record, role in owned_channels(root, args.session)]
    if not statuses:
        emit(args, {"channels": [], "note": "no open channel for this session"})
    elif output_mode(args) == "json":
        print(json.dumps({"channels": statuses}))
    else:
        print(render_status(statuses))


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
                    emit(args, output)
                    raise SystemExit(2 if stopped == "seat_taken" else 0)
            pause(args.interval)
    except HeartbeatStopped:
        emit(args, {"stopped": "signal", "next": nexts["signal"]})


def list_channels(args: argparse.Namespace) -> None:
    if args.wait is not None and not args.live_for:
        refuse(args, "--wait requires --live-for")
    if args.session is not None:
        check_session(args)
    if args.live_for and args.live_for not in ROLES:
        refuse(args, "--live-for must be listener or asker", category="invalid_role")
    if args.live_for and not args.session:
        refuse_missing_session(args)
    if args.wait is not None and not (math.isfinite(args.wait) and args.wait >= 0):
        refuse(args, "--wait must be a finite number of seconds, 0 or more")
    root = root_from(args)

    if not args.live_for:
        emit(args, {"channels": [public_record(record) for record in all_channels(root)]})
        return

    role = args.live_for
    peer = other_role(role)
    script = script_command(args, root)
    session_id = str(args.session)
    session_arg = session_flag(session_id)

    deadline = time.monotonic() + (args.wait or 0)
    while not (candidates := live_candidates(root, role, session_id)) and args.wait is not None:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            emit(args, {
                "channels": [],
                "note": f"no {peer} appeared within {args.wait:g}s; tell the user to start one",
            })
            raise SystemExit(1)
        time.sleep(min(1.0, remaining))

    if candidates:
        emit(args, {
            "channels": candidates,
            "next": f"{script} register --role {role} --channel {candidates[0]['channel']}{session_arg}",
        })
        return
    emit(args, {
        "channels": [],
        "note": f"no live {peer} found",
        "next": (f"only if you started the {peer} yourself or the user said one is starting, run "
                 f"`{script} list --live-for {role}{session_arg} --wait 120`; "
                 f"otherwise tell the user to start a {peer} and stop"),
    })
