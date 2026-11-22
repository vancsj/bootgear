"""Reserve the exact listener seat for one review group and worker."""

from __future__ import annotations

import argparse
import hmac
import json
import math
import os
import secrets
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any

from bootgear_cli import clikit
from channel_liveness import all_channels, reserved_listener_live, seat_live
from channel_output import check_session, emit, refuse, script_command
from channel_store import (
    allocator_lock,
    atomic_write,
    caller_path,
    channel_dir,
    channel_lock,
    closed_channel,
    fail,
    new_record,
    next_channel,
    read_channel_record,
    root_from,
    safe_name,
)

MARKERS = ("{group}", "{worker}", "{invitation}")


def _details(record: dict[str, object]) -> dict[str, Any]:
    value = record.get("reservation")
    return value if isinstance(value, dict) else {}


def public_record(record: dict[str, object]) -> dict[str, object]:
    details = _details(record)
    if not details:
        return record
    return {**record, "reservation": {key: details[key] for key in ("group", "worker", "launch_attempts")}}


def require_owner(record: dict[str, object], role: str) -> None:
    if _details(record):
        owner = record.get(f"{role}_owner")
        if owner is None or owner != clikit.session_id():
            fail(f"the reserved {role} seat belongs to another session", "seat_owner_mismatch")


def _validate_key(args: argparse.Namespace) -> None:
    problems = []
    if not args.group or not args.group.strip() or args.group.startswith("-"):
        problems.append("--group must be nonempty and cannot start with '-'")
    if not args.worker or not safe_name(args.worker) or args.worker.startswith("-"):
        problems.append("--worker must be an agent ID and cannot start with '-'")
    if problems:
        refuse(args, ". ".join(problems))


def _group(root: Path, group: str) -> list[dict[str, object]]:
    return [record for record in all_channels(root) if _details(record).get("group") == group]


def _owned(group: list[dict[str, object]], session: str) -> None:
    if any(record.get("asker_owner") != session for record in group):
        fail("the review group's reservations belong to another asker session", "group_owner_mismatch")


def _worker(group: list[dict[str, object]], worker: str) -> dict[str, object] | None:
    return next((record for record in group if _details(record).get("worker") == worker), None)


def reserve(args: argparse.Namespace) -> None:
    check_session(args)
    _validate_key(args)
    root = root_from(args)
    with allocator_lock(root):
        group = _group(root, args.group)
        _owned(group, args.session)
        record = _worker(group, args.worker)
        if record is None:
            channel = next_channel(root)
            path = channel_dir(root, channel)
            record = new_record(channel)
            record["asker_owner"] = args.session
            record["asker_seen_at"] = time.time()
            record["reservation"] = {"group": args.group, "worker": args.worker,
                                     "invitation": secrets.token_hex(24), "launch_attempts": 0}
            atomic_write(path / "channel.json", json.dumps(record) + "\n")
        elif record["state"] == "closed":
            closed_channel(str(record["channel"]))
    details = _details(record)
    emit(args, {"channel": record["channel"], "group": details["group"], "worker": details["worker"],
                "invitation": details["invitation"], "launch_attempts": details["launch_attempts"],
                "listener_owner": record["listener_owner"],
                "heartbeat": f"{script_command(args, root)} heartbeat --channel {record['channel']} --role asker",
                "next": "start the printed asker heartbeat if needed, then start the reserved listener"})


def invited_channel(args: argparse.Namespace, root: Path) -> str | None:
    fields = tuple(getattr(args, name, None) for name in ("group", "worker", "invitation"))
    if all(value is None for value in fields):
        return None
    if args.role != "listener" or args.channel or any(not value for value in fields):
        refuse(args, "invited registration requires listener, group, worker and invitation without --channel")
    _validate_key(args)
    record = _worker(_group(root, args.group), args.worker)
    if record is None:
        fail("no reservation matches this group and worker", "invitation_mismatch")
    return str(record["channel"])


def validate_invitation(args: argparse.Namespace, record: dict[str, object]) -> None:
    details = _details(record)
    if args.role == "listener" and details:
        if (getattr(args, "group", None) != details["group"]
                or getattr(args, "worker", None) != details["worker"]
                or not hmac.compare_digest(str(getattr(args, "invitation", "")).encode(),
                                           details["invitation"].encode())):
            fail("the listener invitation does not match this reservation", "invitation_mismatch")
        record["listener_host"] = clikit.host()


def _owned_path(args: argparse.Namespace, root: Path) -> Path:
    check_session(args)
    _validate_key(args)
    group = _group(root, args.group)
    _owned(group, args.session)
    record = _worker(group, args.worker)
    if record is None:
        fail("no channel is reserved for this group and worker", "reservation_missing")
    return channel_dir(root, str(record["channel"]), create=False)


def reservations(args: argparse.Namespace) -> None:
    check_session(args)
    root = root_from(args)
    group = _group(root, args.group)
    _owned(group, args.session)
    emit(args, {"channels": [public_record(record) for record in group],
                "next": "use the saved worker channels for continuation or final closure"})


def wait_listener(args: argparse.Namespace) -> None:
    if not math.isfinite(args.timeout) or args.timeout < 0:
        refuse(args, "--timeout must be a finite duration of zero seconds or more")
    root = root_from(args)
    path = _owned_path(args, root)
    deadline = time.monotonic() + args.timeout
    while True:
        record = read_channel_record(path)
        if record["state"] == "closed":
            closed_channel(path.name)
        if record["listener_owner"] and reserved_listener_live(record):
            emit(args, {"ready": True, "channel": path.name, "listener_owner": record["listener_owner"],
                        "listener_host": record["listener_host"],
                        "next": f"{script_command(args, root)} heartbeat --channel {path.name} --role asker"})
            return
        if record.get("listener_heartbeat_at") is not None and seat_live(record, "listener") is False:
            fail("the reserved listener has a stale heartbeat", "peer_not_live")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            details = _details(record)
            next_step = "report the worker assignment blocked if its listener is unavailable"
            if record["listener_owner"] is None and details["launch_attempts"] == 1:
                retry = shlex.join(["launch", "--group", args.group, "--worker", args.worker,
                                   "--template", details["template"], "--retry"])
                next_step = f"if recovery is approved, run {script_command(args, root)} {retry}"
            emit(args, {"ready": False, "channel": path.name, "listener_owner": record["listener_owner"],
                        "next": next_step})
            raise SystemExit(1)
        time.sleep(min(0.1, remaining))


def launch(args: argparse.Namespace) -> None:
    try:
        template = clikit.argv_template(args.template, MARKERS)
    except ValueError as error:
        refuse(args, f"invalid launcher template: {error}")
    root = root_from(args)
    path = _owned_path(args, root)
    with channel_lock(path):
        record = read_channel_record(path)
        if record["state"] == "closed":
            closed_channel(path.name)
        if record["listener_owner"] is not None:
            fail("the reserved listener seat has already been claimed", "seat_claimed")
        details = _details(record)
        expected_attempts = 1 if args.retry else 0
        if details["launch_attempts"] != expected_attempts:
            fail("the reserved launch attempt is unavailable", "launch_attempt_unavailable")
        if args.retry and details.get("template") != args.template:
            fail("retry requires the original launcher template", "launcher_mismatch")
        values = {marker: details[marker[1:-1]] for marker in MARKERS}
        if any(value.startswith("-") for value in values.values()):
            fail("launcher values cannot start with '-'", "invalid_launcher_value")
        argv = [values.get(argument, argument) for argument in template]
        details["launch_attempts"] += 1
        details["template"] = args.template
        atomic_write(path / "channel.json", json.dumps(record) + "\n")
    env = {key: value for key, value in os.environ.items()
           if key not in {"BOOTGEAR_HOST", "BOOTGEAR_SESSION_ID", "CLAUDE_CODE_SESSION_ID", "CODEX_SESSION_ID"}}
    env["BOOTGEAR_ADVISOR_DIR"] = str(root)
    try:
        result = subprocess.run(argv, cwd=caller_path("."), env=env, capture_output=True, text=True, check=False)
    except OSError as error:
        fail(f"launcher could not run: {error}", "launcher_failed")
    if result.returncode != 0:
        diagnostic = result.stderr.strip().replace(values["{invitation}"], "<invitation>")
        fail(f"launcher exited {result.returncode}: {diagnostic}", "launcher_failed")
    key = shlex.join(["--group", args.group, "--worker", args.worker])
    emit(args, {"channel": path.name, "launch_attempt": expected_attempts + 1,
                "next": f"{script_command(args, root)} wait-listener {key}"})
