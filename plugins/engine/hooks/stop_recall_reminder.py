#!/usr/bin/env python3
"""Nudge toward `recall` whenever a turn ends during an active engine run.

`execute` is meant to keep looping until `/goal` resolves, but a turn can
still end for reasons outside `execute`'s own control — a long response
budget, an interruption, a host-level stop. When the next turn picks the
run back up, it must not rely on whatever the ending turn's own context
happened to remember about the settlement or the open todos; it needs to
re-read them from the ledger, the same discipline `recall` already applies
after a compaction (see `recall/SKILL.md`).

This hook returns Stop `additionalContext`, which keeps the conversation open
for one further turn. It does not emit a blocking decision; the host marks the
continuation through `stop_hook_active`.

Confirmed (not assumed) via the Claude Code hooks reference: there is no
`CLAUDE_SESSION_ID` environment variable available to a hook command —
that substitution only exists in skill body text. A hook command instead
gets `session_id` (along with `cwd` and the rest of the common fields) as
JSON piped to its stdin. The run's ledger is
`~/.bootgear/session/<session_id>.md`; the nudge marker sits beside it.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

# Mirrors session.py's own `_heading_re("closed")` exactly: a heading line
# is "## closed" alone on its line, at column 0. A looser substring check
# would false-positive on a decision or pitch whose own free-text body
# happens to quote the literal string "## closed" somewhere inside it.
_CLOSED_HEADING_RE = re.compile(r"(?m)^## closed\s*$")

# Seconds within which a repeat stop attempt counts as "rapid" and keeps
# nudging instead of resetting to a fresh attempt 1. Real work between
# attempts (>= this many seconds) means the model is genuinely progressing,
# not trying to stop repeatedly, so the counter resets rather than nudging.
_RAPID_SECONDS = 30

# Nudge on rapid attempt 1; the 2nd rapid attempt in a row is let through
# silently and the counter resets to 0. Never blocks (no exit 2) either way.
_MAX_NUDGES = 1

REMINDER_MESSAGE = (
    "An engine run is active in this session ({run_id}). Before treating "
    "this as a natural stopping point, call `recall` to re-read the "
    "settlement and open todos from the ledger, and check state against "
    "`/goal`'s succeeded/failed conditions — don't rely on this turn's own "
    "memory of them."
)


def _session_dir() -> Path:
    return Path.home() / ".bootgear" / "session"


def _active_run_id(hook_input: dict) -> str | None:
    run_id = hook_input.get("session_id")
    if not run_id:
        return None
    ledger_path = _session_dir() / f"{run_id}.md"
    if not ledger_path.exists():
        return None
    text = ledger_path.read_text()
    if _CLOSED_HEADING_RE.search(text):
        return None
    return run_id


def _marker_path(base: Path, run_id: str) -> Path:
    return base / f".{run_id}.stop_reminder_state"


def _read_marker(base: Path, run_id: str) -> tuple[int, float]:
    """(nudge_count, last_nudge_at). Missing or corrupt marker = fresh."""
    try:
        data = json.loads(_marker_path(base, run_id).read_text())
        return int(data["nudge_count"]), float(data["last_nudge_at"])
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return 0, 0.0


def _write_marker(base: Path, run_id: str, nudge_count: int, last_nudge_at: float) -> None:
    try:
        _marker_path(base, run_id).write_text(
            json.dumps({"nudge_count": nudge_count, "last_nudge_at": last_nudge_at})
        )
    except OSError:
        pass


def _should_nudge(base: Path, run_id: str) -> bool:
    """Bounded nag loop, not a cooldown: nudge on rapid attempt 1; the 2nd
    rapid attempt in a row is let through silently and resets the counter.
    30s+ of real work since the last nudge also resets to a fresh attempt 1.
    Order matters — the rapid-reset check (a) must run before the
    exhausted-count check (b), or a stale old count near the cap would wrongly
    allow through what is actually a fresh attempt 1."""
    nudge_count, last_nudge_at = _read_marker(base, run_id)
    now = time.time()
    if now - last_nudge_at >= _RAPID_SECONDS:
        _write_marker(base, run_id, 1, now)
        return True
    if nudge_count >= _MAX_NUDGES:
        _write_marker(base, run_id, 0, last_nudge_at)
        return False
    _write_marker(base, run_id, nudge_count + 1, now)
    return True


def main() -> None:
    try:
        hook_input = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return
    run_id = _active_run_id(hook_input)
    if run_id is None:
        return
    if hook_input.get("stop_hook_active") is True:
        return
    if not _should_nudge(_session_dir(), run_id):
        return
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "Stop",
            "additionalContext": REMINDER_MESSAGE.format(run_id=run_id),
        }
    }))


if __name__ == "__main__":
    main()
