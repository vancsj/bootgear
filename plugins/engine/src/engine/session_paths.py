"""Map a host session id to its active Engine ledger directory."""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

_RUN_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]*\Z")


class SessionPathError(RuntimeError):
    """The active Engine session path cannot be read safely."""


def _registration_path(session_id: str, default_dir: Path) -> Path:
    if not _RUN_ID_RE.fullmatch(session_id):
        raise SessionPathError("session id is invalid")
    return default_dir / ".active" / f"{session_id}.json"


def _read_registration(session_id: str, default_dir: Path) -> Path | None:
    registration = _registration_path(session_id, default_dir)
    try:
        raw = registration.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError) as error:
        raise SessionPathError("active session path could not be read") from error
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, RecursionError) as error:
        raise SessionPathError("active session path contains invalid JSON") from error
    if (not isinstance(value, dict) or set(value) != {"session_dir"}
            or not isinstance(value.get("session_dir"), str)):
        raise SessionPathError("active session path has an invalid structure")
    directory = Path(value["session_dir"])
    if not directory.is_absolute():
        raise SessionPathError("active session path must be absolute")
    return directory.resolve()


def active_ledger_path(session_id: str, default_dir: Path) -> Path:
    """Return the registered ledger, or the host's default ledger when none is registered."""
    directory = _read_registration(session_id, default_dir)
    path = (directory or default_dir) / f"{session_id}.md"
    if directory is not None and not path.is_file():
        raise SessionPathError("registered active session ledger is missing")
    return path


def _is_closed(path: Path) -> bool:
    try:
        return "\n## closed\n" in f"\n{path.read_text(encoding='utf-8')}\n"
    except FileNotFoundError:
        return True
    except (OSError, UnicodeError):
        return False


def _write_registration(path: Path, directory: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=f"{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"session_dir": str(directory)}, separators=(",", ":")))
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def register_session_path(session_id: str, session_dir: Path, default_dir: Path) -> bool:
    """Register a custom open ledger so runtime hooks can find the current session."""
    directory = session_dir.resolve()
    default = default_dir.resolve()
    registration = _registration_path(session_id, default)
    existing = _read_registration(session_id, default)
    default_ledger = default / f"{session_id}.md"
    if directory != default and default_ledger.is_file() and not _is_closed(default_ledger):
        raise SessionPathError("another open Engine ledger exists in the default session directory")
    if (existing is not None and existing != directory
            and not _is_closed(existing / f"{session_id}.md")):
        raise SessionPathError("another open Engine ledger is registered for this session id")
    if directory == default:
        changed = existing is not None
        registration.unlink(missing_ok=True)
        return changed
    if existing == directory:
        return False
    _write_registration(registration, directory)
    return True


def unregister_session_path(session_id: str, session_dir: Path, default_dir: Path) -> None:
    """Remove the registration only when it still points to the closing ledger."""
    registration = _registration_path(session_id, default_dir.resolve())
    try:
        existing = _read_registration(session_id, default_dir.resolve())
    except SessionPathError:
        registration.unlink(missing_ok=True)
        return
    if existing == session_dir.resolve():
        registration.unlink(missing_ok=True)
