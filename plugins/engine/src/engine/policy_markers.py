"""Read Engine ledger and marker files and protect marker updates."""

from __future__ import annotations

import fcntl
import json
import math
import os
import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from . import session_paths
from .host_adapter import AdapterError, HostContext

_CLOSED_HEADING_RE: Final = re.compile(r"(?m)^## closed\s*$")


@dataclass(frozen=True)
class MarkerUpdate:
    path: Path
    data: dict[str, Any] | None


def _ledger_path(context: HostContext) -> Path:
    default_dir = Path.home() / ".bootgear" / "session"
    try:
        return session_paths.active_ledger_path(context.session_id, default_dir)
    except session_paths.SessionPathError as error:
        raise AdapterError("active_session_path_error", str(error)) from error


def _marker_path(context: HostContext, suffix: str) -> Path:
    return _ledger_path(context).parent / f".{context.session_id}.{suffix}"


def _active_ledger(context: HostContext) -> tuple[Path, str] | None:
    path = _ledger_path(context)
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if _CLOSED_HEADING_RE.search(text):
        return None
    return path, text


def _read_json(path: Path, default: Any) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return default
    except (OSError, UnicodeDecodeError) as error:
        raise AdapterError("marker_read_error", "marker state could not be read") from error

    def unique_fields(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate marker field")
            result[key] = value
        return result

    def invalid_constant(value: str) -> None:
        raise ValueError(f"invalid marker constant: {value}")

    def finite_float(value: str) -> float:
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError("non-finite marker number")
        return parsed

    try:
        return json.loads(
            text,
            object_pairs_hook=unique_fields,
            parse_constant=invalid_constant,
            parse_float=finite_float,
        )
    except (ValueError, json.JSONDecodeError, RecursionError) as error:
        raise AdapterError("invalid_marker", "marker state contains invalid JSON") from error


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


@contextmanager
def _marker_lock(path: Path, *, nonblocking: bool = False) -> Iterator[bool]:
    lock_path = path.with_name(f"{path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    acquired = False
    try:
        try:
            flags = fcntl.LOCK_EX | (fcntl.LOCK_NB if nonblocking else 0)
            fcntl.flock(fd, flags)
        except BlockingIOError:
            yield False
            return
        acquired = True
        yield True
    finally:
        if acquired:
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _apply_marker(update: MarkerUpdate, *, locked_path: Path | None = None) -> None:
    def write() -> None:
        if update.data is None:
            update.path.unlink(missing_ok=True)
        else:
            _atomic_write(update.path, json.dumps(update.data, separators=(",", ":")))

    if locked_path is not None:
        if locked_path != update.path:
            raise AdapterError("policy_apply_error", "marker update is outside its lock")
        write()
        return
    with _marker_lock(update.path) as locked:
        if not locked:
            raise AdapterError("policy_apply_error", "marker lock was not acquired")
        write()


def _read_text(path: Path) -> str | None:
    try:
        value = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    return value if value.strip() else None
