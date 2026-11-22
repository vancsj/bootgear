"""Track advisor seat liveness and touch hook timestamps."""

from __future__ import annotations

import fcntl
import json
import math
import time
from pathlib import Path

from channel_store import (
    CHANNEL_PATTERN,
    atomic_write,
    channel_lock,
    other_role,
    read_channel_record,
    read_json_object,
)

LIVE_CANDIDATE_WINDOW_SECONDS = 48 * 3600
HEARTBEAT_INTERVAL_SECONDS = 3
HEARTBEAT_TTL_SECONDS = 10
HEARTBEAT_MAX_FAILURES = 3
HEARTBEAT_MAX_AGE_SECONDS = 6180
# A max_age stop keeps the seat live this long for the restart; max-age + grace stays under
# Claude Code's 2-hour background task cap.
RESTART_GRACE_SECONDS = 720
HOOK_NUDGE_INTERVAL_SECONDS = 60


def _as_float(value: object) -> float | None:
    return value if isinstance(value, (int, float)) else None


def _stamp(value: object) -> float | None:
    """`value` as a finite positive timestamp, or None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        return None
    return float(value)


def _within_ttl(value: object) -> bool:
    stamp = _stamp(value)
    return stamp is not None and 0 <= time.time() - stamp <= HEARTBEAT_TTL_SECONDS


def seat_beating(record: dict[str, object], role: str) -> bool:
    """Whether `<role>_seen_at`, the heartbeat's stamp, is 0-TTL seconds old."""
    return _within_ttl(record.get(f"{role}_seen_at"))


def seat_fresh(record: dict[str, object], role: str) -> bool:
    """Whether the heartbeat stamp or the hook stamp `<role>_hook_seen_at` is 0-TTL seconds old."""
    return seat_beating(record, role) or _within_ttl(record.get(f"{role}_hook_seen_at"))


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


def reserved_listener_live(record: dict[str, object]) -> bool:
    return (_within_ttl(record.get("listener_heartbeat_at"))
            or seat_restarting(record, "listener"))


def seat_busy(record: dict[str, object], role: str) -> bool:
    """Whether `role` last set the channel to busy: it is working on a request, not silent."""
    return record.get("state") == "busy" and record.get("state_role") == role


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
        and "reservation" not in c
        and max(_as_float(c.get("created_at")) or 0, _as_float(c.get("updated_at")) or 0) >= cutoff
        and seat_live(c, other) is True
        and c.get(f"{my_role}_owner") in (None, session)
    ]
    return sorted(candidates, key=lambda c: _as_float(c.get("updated_at")) or 0, reverse=True)


def owned_channels(root: Path, session: str) -> list[tuple[dict[str, object], str]]:
    """The open channel updated within the last 48 hours where `session` holds a seat, with that
    seat's role: the most recently updated one (ties: the higher number), or an empty list."""
    try:
        entries = list((root / "channels").iterdir())
    except OSError:
        return []
    cutoff = time.time() - LIVE_CANDIDATE_WINDOW_SECONDS
    found: list[tuple[dict[str, object], str, int]] = []
    for entry in entries:
        if not CHANNEL_PATTERN.fullmatch(entry.name):
            continue
        record = read_json_object(entry / "channel.json")
        if (record is None or record.get("channel") != entry.name or record.get("state") == "closed"
                or max(_as_float(record.get("created_at")) or 0, _as_float(record.get("updated_at")) or 0) < cutoff):
            continue
        role = next((r for r in ("listener", "asker") if record.get(f"{r}_owner") == session), None)
        if role is not None:
            found.append((record, role, int(entry.name)))
    if not found:
        return []
    record, role, _ = max(found, key=lambda item: (_as_float(item[0].get("updated_at")) or 0, item[2]))
    return [(record, role)]


STATUS_KEYS = ("channel", "role", "state", "peer_live", "heartbeat", "unread", "last_read", "owed", "next")


def _recent(value: object, now: float, seconds: float) -> bool:
    stamp = _stamp(value)
    return stamp is not None and 0 <= now - stamp < seconds


def _reminder_due(record: dict[str, object], role: str, now: float) -> bool:
    return (not seat_beating(record, role)
            and not _recent(record.get(f"{role}_hook_nudged_at"), now, HOOK_NUDGE_INTERVAL_SECONDS))


def hook_touch(root: Path, session: str, now: float, remind: bool = True) -> list[tuple[dict[str, object], str]]:
    """Stamp `<role>_hook_seen_at` on the session's channel. With `remind`, return the seats whose
    stopped heartbeat is due a restart reminder, marking `<role>_hook_nudged_at`."""
    due: list[tuple[dict[str, object], str]] = []
    for record, role in owned_channels(root, session):
        if not (remind and _reminder_due(record, role, now)) and _recent(
                record.get(f"{role}_hook_seen_at"), now, HEARTBEAT_INTERVAL_SECONDS):
            continue
        path = root / "channels" / str(record["channel"])
        lock = channel_lock(path)
        try:
            current = read_json_object(path / "channel.json")
            if current is None or current.get("state") == "closed" or current.get(f"{role}_owner") != session:
                continue
            current[f"{role}_hook_seen_at"] = now
            if remind and _reminder_due(current, role, now):
                current[f"{role}_hook_nudged_at"] = now
                due.append((current, role))
            atomic_write(path / "channel.json", json.dumps(current) + "\n")
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
            lock.close()
    return due


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
        if role == "listener" and "reservation" in record:
            record["listener_heartbeat_at"] = record["listener_seen_at"]
        record.pop(f"{role}_restart_until", None)
        atomic_write(path / "channel.json", json.dumps(record) + "\n")
        return None
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()
