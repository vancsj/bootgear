"""Read Codex descendant activity from its persisted runtime records."""
from __future__ import annotations

import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from datetime import datetime
from pathlib import Path

from .host_adapter import AdapterError

_DESCENDANTS = """
WITH RECURSIVE tree(id) AS (
    SELECT ?
    UNION
    SELECT e.child_thread_id FROM thread_spawn_edges e
    JOIN tree ON e.parent_thread_id = tree.id
)
SELECT t.rollout_path FROM tree
JOIN threads t ON t.id = tree.id
JOIN thread_spawn_edges e ON e.child_thread_id = t.id
WHERE t.id != ? AND e.status = 'open'
"""
_LIFECYCLE = frozenset({"task_started", "task_complete", "turn_aborted"})


def _reverse_lines(path: Path) -> Iterator[bytes]:
    with path.open("rb") as stream:
        position = stream.seek(0, os.SEEK_END)
        buffer = b""
        trailing = True
        while position:
            size = min(position, 65536)
            position -= size
            stream.seek(position)
            parts = (stream.read(size) + buffer).split(b"\n")
            buffer = parts[0]
            for line in reversed(parts[1:]):
                if trailing:
                    trailing = False
                    continue
                if line:
                    yield line
        if buffer and not trailing:
            yield buffer


def _rollout_running(path: Path, runtime_started_at: float) -> bool:
    for line in _reverse_lines(path):
        item = json.loads(line)
        if not isinstance(item, dict):
            raise TypeError("invalid rollout record")
        if item.get("type") != "event_msg":
            continue
        payload = item.get("payload")
        if not isinstance(payload, dict):
            raise TypeError("invalid lifecycle record")
        kind = payload.get("type")
        if kind not in _LIFECYCLE:
            continue
        if kind != "task_started":
            return False
        timestamp = item.get("timestamp")
        if not isinstance(timestamp, str):
            raise TypeError("missing lifecycle timestamp")
        return datetime.fromisoformat(timestamp).timestamp() >= runtime_started_at
    return False


def has_running_descendant(session_id: str, runtime_started_at: float | None) -> bool:
    """Return positive running evidence from the current root's saved snapshot."""
    if runtime_started_at is None:
        return False
    try:
        home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
        database = home / "state_5.sqlite"
        try:
            database.stat()
        except FileNotFoundError:
            return False
        with closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=1)) as connection:
            rows = connection.execute(_DESCENDANTS, (session_id, session_id)).fetchall()
        return any(_rollout_running(Path(row[0]), runtime_started_at) for row in rows)
    except (OSError, sqlite3.Error, ValueError, TypeError) as error:
        raise AdapterError("subagent_state_error", "Codex subagent state could not be read") from error
