#!/usr/bin/env python3
"""Nudge toward a state transition when an active engine run's `## state`
has gone stale — `execute` can spend many tool calls investigating,
implementing, and verifying without ever calling `session.py state
transition`, and nothing else in the loop catches that drift until `Stop`.

This fires on `PostToolUse` (the only event close to a time-based cadence
Codex hooks support — there is no cron-style trigger) but only emits
a nudge once real wall-clock time has passed since the run's last recorded
activity, debounced by its own marker file, so it does not fire on every
single tool call.

Finds the run's ledger at `~/.bootgear/session/<session_id>.md`,
session.py's `DEFAULT_DIR`; the debounce marker sits beside it.

Uses the tested `session.py` CLI reader (`session read --section state --json`)
rather than hand-parsing the ledger, per the same principle
`session_start_recall.py` and `stop_recall_reminder.py` already follow for
their own sections. A debounce marker's own `last_checked_at` field gates
the subprocess call itself, not just the nudge: `uv run` costs tens to
hundreds of milliseconds, and this hook runs on every tool call, so paying
that cost unconditionally would add real, serialized latency to ordinary
tool use.

Ages a run by the ledger's own recorded time, not a filesystem timestamp:
`cmd_init` writes `started: <time>` into `## state` alongside `current:`,
and `cmd_transition` preserves that line instead of folding it into the
transition log. The ledger file's mtime/ctime cannot serve as the signal,
because every ordinary `record-decision`/`record-pitch` write resets both
(`_write_atomic`'s `os.replace` bumps them), which would silently suppress
the nudge for the run that most needs it: one accumulating unrelated work
without transitioning. A ledger with no `started:` line has unknown age;
this hook never nudges it, rather than guessing from an unreliable stat.

The debounce marker reuses `session.py`'s own atomic-write pattern
(`_write_atomic`, copied rather than imported — hooks run as standalone
scripts outside the `engine` package) rather than the sibling hook's plain
`write_text`: a `PostToolUse` hook fires far more often than `Stop`, and
parallel tool calls start their hooks concurrently, so the read-modify-write
also holds a non-blocking lock (`_try_lock`). Subagent tool calls are
skipped outright. The marker records
which transition it last nudged about (not just a timestamp), so it cannot
mistake two distinct transitions inside the same clock minute for "nothing
changed," and a fresh transition always clears a stale nudge.

The nudge message says the node "looks stale," not that the run is
"stuck" — `execute` explicitly allows one node to span many iterations
(reading, implementing, and testing are all legitimate work with no state
transition in between), so elapsed time alone is a prompt to check, not
proof anything is wrong.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

_CLOSED_HEADING_RE = re.compile(r"(?m)^## closed\s*$")
_TERMINAL_NODES = {"succeeded", "failed"}

# How stale ## state must be, in seconds, before this hook says anything.
_STALE_SECONDS = 5 * 60

# Below this, skip even the `session read` subprocess — a hook firing on
# every tool call would otherwise spawn it dozens of times a minute for no
# reason once a nudge has already fired recently.
_MIN_RECHECK_SECONDS = 60

REMINDER_MESSAGE = (
    "This engine run's state ({run_id}, node '{node}') hasn't recorded a "
    "transition in over {minutes} minutes. That doesn't necessarily mean "
    "the run is stuck — one node can legitimately span several tool calls "
    "— but check whether the current work has actually moved past this "
    "node and, if so, call `session.py state transition` to record it."
)

# Escalates exactly once per identity (see `_last_activity`), never past this
# one wording — a node still stale after the repeat interval below gets this
# once, then silence for that same identity. Never a claim about what
# specifically wasn't done, only that the same identity was already flagged
# once. A missing follow-up is never proof the prior nudge was consciously
# rejected, only that no transition happened to land before this check;
# escalating anyway is a deliberate choice to escalate on absence of
# evidence, not on confirmed non-response. A new identity (any real
# transition, even one that lands back on the same node name) resets to the
# base message.
ESCALATED_REMINDER_MESSAGE = (
    "This engine run's state ({run_id}, node '{node}') was already flagged "
    "as stale and still hasn't recorded a transition ({minutes} minutes "
    "now). If the work has genuinely moved past this node, call "
    "`session.py state transition` now; if not, that's also worth "
    "confirming rather than leaving open."
)

# Separate from _MIN_RECHECK_SECONDS: that gate throttles the subprocess
# call itself; this one decides whether a still-stale identity has gone long
# enough *since its base nudge* to earn the one escalation. They must stay
# decoupled: a debounce keyed on the same "have we nudged this identity"
# state that gates the escalation check would block the second nudge
# outright, making escalation unreachable.
_ESCALATE_AFTER_SECONDS = 15 * 60

# How many past nudge events state_nudge_state's `nudges` list keeps.
# Bounded so a long-running node doesn't grow the marker file without
# limit; nothing in this hook reads it back for the escalation decision
# (that only needs `last_nudged_identity`, `identity_first_nudged_at`, and
# `escalated_for_identity`) — it exists purely for the after-the-fact
# correlation against the ledger's own transition log.
_MAX_NUDGE_HISTORY = 50


def _ledger_path(run_id: str) -> Path:
    return Path.home() / ".bootgear" / "session" / f"{run_id}.md"


def _active_run(hook_input: dict) -> tuple[str, Path] | None:
    run_id = hook_input.get("session_id")
    if not run_id:
        return None
    ledger_path = _ledger_path(run_id)
    if not ledger_path.is_file():
        return None
    return run_id, ledger_path


def _write_atomic(path: Path, text: str) -> None:
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp",
                                     dir=path.parent)
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def _marker_path(ledger_path: Path, run_id: str) -> Path:
    return ledger_path.parent / f".{run_id}.state_nudge_state"


def _read_marker(marker_path: Path) -> dict:
    try:
        data = json.loads(marker_path.read_text())
    except (OSError, ValueError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_marker(marker_path: Path, data: dict) -> None:
    try:
        _write_atomic(marker_path, json.dumps(data))
    except OSError:
        pass


def _try_lock(marker_path: Path) -> tuple[bool, int | None]:
    """Non-blocking exclusive lock guarding the marker's read-modify-write.

    Returns (proceed, fd to close). proceed is False only when another hook
    process holds the lock — it is already checking this run. When the lock
    file cannot be created or locked for any other reason, proceeds
    unlocked (fd None) rather than silently dropping the nudge."""
    try:
        fd = os.open(str(marker_path) + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
    except OSError:
        return True, None
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return False, None
    except OSError:
        os.close(fd)
        return True, None
    return True, fd


def _run_state_section(plugin_dir: Path, run_id: str, session_dir: str) -> dict | None:
    """`session read --section state --json`: `current`, `started` and the
    parsed `transitions`, or None when the read fails."""
    task_bin = plugin_dir / "scripts" / "task"
    try:
        result = subprocess.run(
            [str(task_bin), "session", "read", run_id,
             "--dir", session_dir, "--section", "state", "--json"],
            capture_output=True, text=True, timeout=15, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        state = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    return state if isinstance(state, dict) else None


def _parse_minute_ts(raw: str) -> float | None:
    try:
        return datetime.strptime(raw, "%Y-%m-%d %H:%M").astimezone().timestamp()
    except ValueError:
        return None


def _last_activity(state: dict) -> tuple[str, float | None, int]:
    """(current_node, last_activity_epoch_or_None, transition_index).

    `transition_index` is the count of transition-log entries in
    `## state` (0 when the run hasn't transitioned since `started:`). It
    exists because the ledger writer itself (`session.py`'s timestamp
    helper), not just this hook's reader, truncates to the minute — two
    genuinely distinct transitions can share an identical epoch, so epoch
    alone cannot tell "nothing changed" from "something changed within the
    same clock minute." An intermediate transition that goes stale and gets
    nudged on its own, followed by a second real transition landing in the
    same minute, would be silently suppressed under an epoch-only or
    node-only identity. `transition_index` is monotonic per-ledger
    regardless of clock resolution, so it disambiguates that case without
    needing finer-grained ledger timestamps.

    Prefers the most recent transition-log timestamp for the epoch. Falls
    back to `started:` (written by `cmd_init`) when
    there have been zero transitions yet. Returns None for the epoch only
    when neither exists — a ledger written before `started:` existed — in
    which case the caller treats age as unknown and never nudges: no
    filesystem timestamp (mtime/ctime) survives an ordinary ledger write, so
    there is no safe heuristic fallback left to use."""
    node = state.get("current") or ""
    transitions = state.get("transitions") or []
    transition_index = len(transitions)
    if transitions:
        return node, _parse_minute_ts(transitions[-1]["at"]), transition_index
    started = state.get("started")
    if started:
        return node, _parse_minute_ts(started), transition_index
    return node, None, transition_index


def main() -> None:
    try:
        hook_input = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return
    # A subagent's tool call carries the parent's session_id plus an
    # agent_id. The nudge is for the session driving the run.
    if hook_input.get("agent_id"):
        return
    active = _active_run(hook_input)
    if active is None:
        return
    run_id, ledger_path = active

    text = ledger_path.read_text()
    if _CLOSED_HEADING_RE.search(text):
        return

    marker_path = _marker_path(ledger_path, run_id)
    proceed, lock_fd = _try_lock(marker_path)
    if not proceed:
        return
    try:
        _check(run_id, ledger_path, marker_path)
    finally:
        if lock_fd is not None:
            os.close(lock_fd)


def _check(run_id: str, ledger_path: Path, marker_path: Path) -> None:
    now = time.time()
    marker = _read_marker(marker_path)
    last_checked_at = marker.get("last_checked_at", 0.0)
    if now - last_checked_at < _MIN_RECHECK_SECONDS:
        return
    marker["last_checked_at"] = now
    _write_marker(marker_path, marker)

    plugin_dir = Path(__file__).resolve().parent.parent
    state = _run_state_section(plugin_dir, run_id, str(ledger_path.parent))
    if state is None:
        return

    node, last_activity_epoch, transition_index = _last_activity(state)
    if node in _TERMINAL_NODES:
        return
    if last_activity_epoch is None:
        # Neither a transition nor a `started:` line exists. No filesystem
        # timestamp (mtime/ctime) survives an ordinary ledger write
        # (`_write_atomic`'s `os.replace` bumps both on every
        # record-decision/record-pitch call), so there is no safe
        # heuristic. Age is unknown; never nudge rather than guess.
        return

    elapsed = max(0.0, now - last_activity_epoch)
    if elapsed < _STALE_SECONDS:
        return

    # Identity is (node, activity epoch, transition_index) rather than any
    # single field alone: the ledger writer truncates timestamps to the
    # minute, so epoch alone can't tell two same-minute transitions apart,
    # and node alone can't tell a real revisit (test-code -> fix ->
    # test-code) from "nothing happened." transition_index disambiguates
    # both. A marker with no `last_nudged_identity` takes the base-only
    # path below on its first check, rather than escalating on an identity
    # it never recorded; that same call writes `last_nudged_identity`, so
    # later checks escalate normally.
    identity = [node, last_activity_epoch, transition_index]
    last_identity = marker.get("last_nudged_identity")
    first_check_for_identity = last_identity != identity

    if first_check_for_identity:
        marker["last_nudged_identity"] = identity
        marker["identity_first_nudged_at"] = now
        marker["escalated_for_identity"] = False
        message = REMINDER_MESSAGE
    else:
        # Same identity as the last nudge: escalate exactly once, after a
        # separate repeat interval, then go silent for this identity.
        # Decoupled from `_MIN_RECHECK_SECONDS` (which only throttles the
        # subprocess call) and from identity dedup itself: a debounce keyed
        # on "already nudged this identity" would block the second nudge
        # outright, so a genuine unbroken stall would be nudged once, ever.
        if marker.get("escalated_for_identity"):
            return
        first_nudged_at = marker.get("identity_first_nudged_at")
        if first_nudged_at is None:
            # Start the repeat interval now rather than never.
            marker["identity_first_nudged_at"] = now
            _write_marker(marker_path, marker)
            return
        if now - first_nudged_at < _ESCALATE_AFTER_SECONDS:
            return
        marker["escalated_for_identity"] = True
        message = ESCALATED_REMINDER_MESSAGE

    history = marker.get("nudges") or []
    history.append({
        "at": now, "node": node, "activity": last_activity_epoch,
        "transition_index": transition_index,
    })
    marker["nudges"] = history[-_MAX_NUDGE_HISTORY:]
    _write_marker(marker_path, marker)

    minutes = int(elapsed // 60)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": message.format(
                run_id=run_id, node=node, minutes=minutes,
            ),
        }
    }))


if __name__ == "__main__":
    main()
