"""Evaluate reminders for a stale Engine state."""

from __future__ import annotations

import json
import math
import subprocess
import time
from datetime import datetime
from typing import Any, Final

from bootgear_cli.clikit import gear_argv, gear_command

from .host_adapter import AdapterError, Event, HostContext, Intent
from .policy_markers import (
    MarkerUpdate,
    _active_ledger,
    _ledger_path,
    _marker_path,
    _read_json,
)

_STALE_SECONDS: Final = 5 * 60
_MIN_RECHECK_SECONDS: Final = 60
_ESCALATE_AFTER_SECONDS: Final = 15 * 60
_MAX_NUDGE_HISTORY: Final = 50
_TERMINAL_NODES: Final = frozenset({"succeeded", "failed"})
_ESCALATED_MESSAGE: Final = (
    "This engine run's state ({run_id}, node '{node}') was already flagged "
    "as stale and still hasn't recorded a transition ({minutes} minutes "
    "now). If the work has genuinely moved past this node, run "
    "{transition_command} now; if not, that's also worth "
    "confirming rather than leaving open."
)


def _parse_minute_ts(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M").astimezone().timestamp()
    except ValueError:
        return None


def _last_activity(state: dict[str, Any]) -> tuple[str, float | None, int]:
    node = state.get("current") or ""
    transitions = state.get("transitions") or []
    if not isinstance(transitions, list):
        transitions = []
    index = len(transitions)
    if transitions and isinstance(transitions[-1], dict):
        return node, _parse_minute_ts(transitions[-1].get("at")), index
    return node, _parse_minute_ts(state.get("started")), index


def _run_state(context: HostContext) -> dict[str, Any] | None:
    ledger = _ledger_path(context)
    try:
        result = subprocess.run(
            [
                *gear_argv("engine", "task", host=context.host),
                "session",
                "read",
                context.session_id,
                "--dir",
                str(ledger.parent),
                "--section",
                "state",
                "--json",
            ],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        value = json.loads(result.stdout)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _state_nudge(event: Event, context: HostContext) -> Intent:
    if event.payload.get("agent_id") is not None:
        return Intent.observe()
    active = _active_ledger(context)
    if active is None:
        return Intent.observe()
    marker = _marker_path(context, "state_nudge_state")
    marker_value = _read_json(marker, {})
    if not isinstance(marker_value, dict):
        raise AdapterError("invalid_marker", "State nudge marker has invalid structure")
    for name in ("last_checked_at", "identity_first_nudged_at"):
        value = marker_value.get(name)
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
        ):
            raise AdapterError("invalid_marker", "State nudge marker has invalid structure")
    if "escalated_for_identity" in marker_value and type(
        marker_value["escalated_for_identity"]
    ) is not bool:
        raise AdapterError("invalid_marker", "State nudge marker has invalid structure")
    if "nudges" in marker_value and not isinstance(marker_value["nudges"], list):
        raise AdapterError("invalid_marker", "State nudge marker has invalid structure")
    now = time.time()
    last_checked = marker_value.get("last_checked_at", 0.0)
    if isinstance(last_checked, (int, float)) and now - last_checked < _MIN_RECHECK_SECONDS:
        return Intent.observe()
    marker_value["last_checked_at"] = now
    update = MarkerUpdate(marker, marker_value)
    state = _run_state(context)
    if state is None:
        return Intent.observe(update)
    node, last_activity, transition_index = _last_activity(state)
    if node in _TERMINAL_NODES or last_activity is None:
        return Intent.observe(update)
    elapsed = max(0.0, now - last_activity)
    if elapsed < _STALE_SECONDS:
        return Intent.observe(update)
    identity = [node, last_activity, transition_index]
    transition_command = f"`{gear_command('engine', 'task', host=context.host)} state transition`"
    if marker_value.get("last_nudged_identity") != identity:
        marker_value["last_nudged_identity"] = identity
        marker_value["identity_first_nudged_at"] = now
        marker_value["escalated_for_identity"] = False
        message = (
            "This engine run's state ({run_id}, node '{node}') hasn't recorded a "
            "transition in over {minutes} minutes. That doesn't necessarily mean "
            "the run is stuck — one node can legitimately span several tool calls "
            "— but check whether the current work has actually moved past this "
            f"node and, if so, run {transition_command} to record it."
        )
    else:
        if marker_value.get("escalated_for_identity"):
            return Intent.observe(update)
        first = marker_value.get("identity_first_nudged_at")
        if not isinstance(first, (int, float)) or now - first < _ESCALATE_AFTER_SECONDS:
            return Intent.observe(update)
        marker_value["escalated_for_identity"] = True
        message = _ESCALATED_MESSAGE
    history = marker_value.get("nudges")
    if not isinstance(history, list):
        history = []
    history.append(
        {
            "at": now,
            "node": node,
            "activity": last_activity,
            "transition_index": transition_index,
        }
    )
    marker_value["nudges"] = history[-_MAX_NUDGE_HISTORY:]
    text = message.format(run_id=event.session_id, node=node, minutes=int(elapsed // 60),
                          transition_command=transition_command)
    return Intent.add_context(text, update)
