#!/usr/bin/env python3
"""Owner-only numbered mailbox for Claude Code / Codex advisor pairs."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import secrets
import shlex
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


def fail(message: str, category: str | None = None) -> NoReturn:
    payload = {"error": message}
    if category is not None:
        payload["category"] = category
    print(json.dumps(payload), file=sys.stderr)
    raise SystemExit(2)


def safe_name(value: str, label: str) -> str:
    if not value or value in {".", ".."} or any(
        char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for char in value
    ):
        fail(f"invalid {label}: {value!r}")
    return value


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
    if body_file == "-" and sys.stdin.isatty():
        fail("--body-file - requires piped input")
    path = None if body_file == "-" else caller_path(body_file)
    body = sys.stdin.read() if path is None else path.read_text(encoding="utf-8")
    if not body.strip():
        fail("message body is empty")
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
        "listener_owner": None, "listener_pid": None, "listener_pid_started_at": None,
        "asker_owner": None, "asker_pid": None, "asker_pid_started_at": None,
    }


def brief_record(record: dict[str, object]) -> dict[str, object]:
    return {
        "channel": record.get("channel"),
        "listener_owner": record.get("listener_owner"),
        "listener_pid": record.get("listener_pid"),
        "listener_pid_started_at": record.get("listener_pid_started_at"),
        "asker_owner": record.get("asker_owner"),
        "asker_pid": record.get("asker_pid"),
        "asker_pid_started_at": record.get("asker_pid_started_at"),
    }


def register(args: argparse.Namespace) -> None:
    if args.role not in ROLES:
        fail("role must be listener or asker", category="invalid_role")
    if args.pid <= 0:
        fail("pid must be a positive integer", category="invalid_pid")
    owner_key = f"{args.role}_owner"
    pid_key = f"{args.role}_pid"
    started_key = f"{args.role}_pid_started_at"
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
            record[pid_key] = args.pid
            record[started_key] = args.pid_started_at
            record["updated_at"] = time.time()
            atomic_write(path / "channel.json", json.dumps(record) + "\n")
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
            lock.close()
        print(json.dumps(brief_record(record)))
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
        record[pid_key] = args.pid
        record[started_key] = args.pid_started_at
        atomic_write(path / "channel.json", json.dumps(record) + "\n")
        fcntl.flock(lock, fcntl.LOCK_UN)
    print(json.dumps(brief_record(record)))


def state(args: argparse.Namespace) -> None:
    root = root_from(args)
    path = channel_dir(root, args.channel)
    if args.role not in ROLES:
        fail("role must be listener or asker")
    if args.value not in {"waiting", "busy", "closed"}:
        fail("state must be waiting, busy, or closed")
    lock = channel_lock(path)
    try:
        record = read_channel_record(path)
        record.update({"state": args.value, "state_role": args.role, "updated_at": time.time()})
        atomic_write(path / "channel.json", json.dumps(record) + "\n")
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()
    print(json.dumps(record))


def close(args: argparse.Namespace) -> None:
    if args.role not in ROLES:
        fail("role must be listener or asker")
    args.value = "closed"
    state(args)


def read_process_start_time(pid: int) -> float | None:
    """macOS-only: proc_pidinfo's own stable p_start value for this PID, via ctypes.

    Returns None if the process exists but its start time can't be read (a
    malformed/short proc_pidinfo result); raises ProcessLookupError if no
    process exists at this PID at all. Fails with category
    `unsupported_platform` on any other OS.
    """
    if sys.platform != "darwin":
        fail("the advisor mailbox needs macOS: it reads process start times with proc_pidinfo",
             category="unsupported_platform")
    import ctypes
    import ctypes.util

    PROC_PIDTBSDINFO = 3
    libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)

    class ProcBsdInfo(ctypes.Structure):
        _fields_ = [
            ("pbi_flags", ctypes.c_uint32),
            ("pbi_status", ctypes.c_uint32),
            ("pbi_xstatus", ctypes.c_uint32),
            ("pbi_pid", ctypes.c_uint32),
            ("pbi_ppid", ctypes.c_uint32),
            ("pbi_uid", ctypes.c_uint32),
            ("pbi_gid", ctypes.c_uint32),
            ("pbi_ruid", ctypes.c_uint32),
            ("pbi_rgid", ctypes.c_uint32),
            ("pbi_svuid", ctypes.c_uint32),
            ("pbi_svgid", ctypes.c_uint32),
            ("rfu_1", ctypes.c_uint32),
            ("pbi_comm", ctypes.c_char * 16),
            ("pbi_name", ctypes.c_char * 32),
            ("pbi_nfiles", ctypes.c_uint32),
            ("pbi_pgid", ctypes.c_uint32),
            ("pbi_pjobc", ctypes.c_uint32),
            ("e_tdev", ctypes.c_uint32),
            ("e_tpgid", ctypes.c_uint32),
            ("pbi_nice", ctypes.c_int32),
            ("pbi_start_tvsec", ctypes.c_uint64),
            ("pbi_start_tvusec", ctypes.c_uint64),
        ]

    info = ProcBsdInfo()
    size = libc.proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, ctypes.byref(info), ctypes.sizeof(info))
    if size == 0:
        raise ProcessLookupError(f"no process at pid {pid}")
    if size != ctypes.sizeof(info) or info.pbi_pid != pid:
        return None
    return info.pbi_start_tvsec + info.pbi_start_tvusec / 1_000_000


def is_alive(pid: int | None, started_at: float | None) -> bool | None:
    if pid is None or started_at is None:
        return None  # no pid recorded (never registered)
    try:
        actual_started_at = read_process_start_time(pid)
    except ProcessLookupError:
        return False
    except PermissionError:
        return None  # a process exists at this pid, but its start time isn't readable
    if actual_started_at is None:
        return None  # process exists but its start time couldn't be confirmed
    return actual_started_at == started_at  # exact match -- not a tolerance comparison


def _as_int(value: object) -> int | None:
    return value if isinstance(value, int) else None


def _as_float(value: object) -> float | None:
    return value if isinstance(value, (int, float)) else None


def status(args: argparse.Namespace) -> None:
    root = root_from(args)
    path = channel_dir(root, args.channel)
    record = read_channel_record(path)
    output = dict(record)
    output["listener_alive"] = is_alive(_as_int(record.get("listener_pid")), _as_float(record.get("listener_pid_started_at")))
    output["asker_alive"] = is_alive(_as_int(record.get("asker_pid")), _as_float(record.get("asker_pid_started_at")))
    print(json.dumps(output))


def whoami(args: argparse.Namespace) -> None:
    """Prints the exact proc_pidinfo start time for a PID the caller already
    knows (its own long-lived host process), so --pid-started-at is sourced
    from the same precision this design's liveness check requires -- not
    from a caller's own guess at a shell command like `ps -o lstart`, whose
    whole-second resolution can never satisfy is_alive's exact comparison."""
    try:
        started_at = read_process_start_time(args.pid)
    except ProcessLookupError:
        fail(f"no process at pid {args.pid}")
    if started_at is None:
        fail(f"pid {args.pid} exists but its start time could not be read")
    print(json.dumps({"pid": args.pid, "pid_started_at": started_at}))


def message_files(path: Path):
    return sorted((path / "messages").glob("*.json"))


def send(args: argparse.Namespace) -> None:
    if args.sender not in ROLES or args.recipient not in ROLES:
        fail("sender and recipient must be listener or asker")
    if args.sender == args.recipient:
        fail("sender and recipient must differ")
    if args.kind not in KINDS:
        fail(f"unknown kind: {args.kind}")
    if args.kind == "response" and not args.parent_id:
        fail("responses require --parent-id")

    root = root_from(args)
    path = channel_dir(root, args.channel)
    record = read_channel_record(path)
    if record.get("state") == "closed":
        fail(f"channel is closed: {args.channel}")

    body = read_body(args.body_file)
    lock = channel_lock(path)
    try:
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
    if args.recipient not in ROLES:
        fail("recipient must be listener or asker")
    root = root_from(args)
    path = channel_dir(root, args.channel)
    record = read_channel_record(path)
    if record.get("state") == "closed":
        fail(f"channel is closed: {args.channel}")

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

    messages = [json.loads(f.read_text(encoding="utf-8")) for f in current]
    messages.sort(key=lambda m: m.get("created_at", 0), reverse=True)
    recent = messages[:HISTORY_SIZE]
    output = {
        "new_since_call": pending,
        "messages": [summarize(m) for m in recent],
    }
    script = f"python3 {shlex.quote(str(Path(__file__).resolve()))}"
    if args.root is not None or root != DEFAULT_ROOT:
        script += f" --root {shlex.quote(str(root))}"
    if pending == 0:
        read = "; the messages listed were already read" if recent else ""
        if args.recipient == "asker":
            wait = ("a reply can take many minutes, so run receive again with a long "
                    "--timeout (e.g. 300) instead of giving up or resending; up to 5 "
                    "waits of 300s before reporting the peer unavailable")
        else:
            wait = ("a request can come at any time, so run receive again with a long "
                    "--timeout (e.g. 300)")
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
    root = root_from(args)
    path = channel_dir(root, args.channel)
    read_channel_record(path)
    message_id = safe_name(args.message_id, "message id")
    message_path = path / "messages" / f"{message_id}.json"
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


def live_candidates(root: Path, my_role: str) -> list[dict[str, object]]:
    """Channels updated within the last 48 hours where the peer seat is
    filled and not confirmed dead. Does not check my own seat at all --
    the only caller is an asker about to claim an open listener seat,
    and a listener never calls it."""
    cutoff = time.time() - LIVE_CANDIDATE_WINDOW_SECONDS
    other = other_role(my_role)
    other_owner_key = f"{other}_owner"
    other_pid_key = f"{other}_pid"
    other_started_key = f"{other}_pid_started_at"
    return [
        c for c in all_channels(root)
        if c.get("state") != "closed"
        and max(_as_float(c.get("created_at")) or 0, _as_float(c.get("updated_at")) or 0) >= cutoff
        and c.get(other_owner_key) is not None
        and is_alive(_as_int(c.get(other_pid_key)), _as_float(c.get(other_started_key))) is not False
    ]


def list_channels(args: argparse.Namespace) -> None:
    root = root_from(args)

    if not args.live_for:
        print(json.dumps(all_channels(root)))
        return

    role = args.live_for
    if role not in ROLES:
        fail("--live-for must be listener or asker")

    print(json.dumps(live_candidates(root, role)))


def add_channel(parser: argparse.ArgumentParser, required: bool = True) -> None:
    parser.add_argument("--channel", required=required)


def add_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", help="override the mailbox root")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    add_root(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)

    register_parser = subparsers.add_parser("register")
    add_channel(register_parser, required=False)
    register_parser.add_argument("--role", required=True)
    register_parser.add_argument("--session", required=True, help="this party's session/process id")
    register_parser.add_argument("--pid", required=True, type=int, help="the long-lived host process's own PID")
    register_parser.add_argument("--pid-started-at", required=True, type=float, dest="pid_started_at")
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
    close_parser.set_defaults(handler=close)

    list_parser = subparsers.add_parser("list")
    list_parser.add_argument("--live-for", dest="live_for", default=None)
    list_parser.set_defaults(handler=list_channels)

    status_parser = subparsers.add_parser("status")
    add_channel(status_parser)
    status_parser.set_defaults(handler=status)

    whoami_parser = subparsers.add_parser("whoami")
    whoami_parser.add_argument("--pid", required=True, type=int, help="a PID the caller already knows, typically its own long-lived process")
    whoami_parser.set_defaults(handler=whoami)

    return parser


if __name__ == "__main__":
    arguments = build_parser().parse_args()
    try:
        arguments.handler(arguments)
    except SystemExit:
        raise
    except Exception as error:
        fail(f"{type(error).__name__}: {error}")
