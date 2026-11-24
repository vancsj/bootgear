"""Read and write advisor mailbox records under their shared lock."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import secrets
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import NoReturn

DEFAULT_ROOT = Path.home() / ".bootgear" / "advisor"
ROLES = {"listener", "asker"}
CHANNEL_PATTERN = re.compile(r"^[0-9]{4,}$")


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


def safe_name(value: str) -> bool:
    return bool(value) and value not in {".", ".."} and all(
        char in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for char in value
    )


def closed_channel(channel: str, role: str | None = None) -> NoReturn:
    fail(f"channel is closed: {channel}", category="channel_closed",
         next_step=("end listening silently" if role == "listener" else
                    f"stop using channel {channel} and tell the user; continuing needs a new pairing"))


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


@contextmanager
def allocator_lock(root: Path) -> Iterator[None]:
    path = root / "allocator.lock"
    path.touch(mode=0o600, exist_ok=True)
    os.chmod(path, 0o600)
    with path.open("r+") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield


def next_channel(root: Path) -> str:
    numbers = (int(path.name) for path in (root / "channels").iterdir()
               if path.is_dir() and path.name.isdigit())
    return f"{max(numbers, default=0) + 1:04d}"


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


def read_json_object(path: Path) -> dict[str, object] | None:
    """The JSON object in `path`, or None when it cannot be read or is not an object."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None
