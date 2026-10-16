"""Host-neutral policies for the engine hook adapter.

Each handler has a side-effect-free evaluation phase and a separate apply phase.
Evaluation may inspect the existing session ledger and marker state, but it
never writes a marker or emits host JSON. The adapter only calls apply after
validation and capability selection have succeeded.
"""
from __future__ import annotations

import fcntl
import json
import math
import os
import re
import subprocess
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Final

from .host_adapter import AdapterError, Event, HostContext, Intent

_CLOSED_HEADING_RE: Final = re.compile(r"(?m)^## closed\s*$")
_RAPID_SECONDS: Final = 30
_MAX_NUDGES: Final = 1
_MAX_TURNS: Final = 32
_STALE_SECONDS: Final = 5 * 60
_MIN_RECHECK_SECONDS: Final = 60
_ESCALATE_AFTER_SECONDS: Final = 15 * 60
_MAX_NUDGE_HISTORY: Final = 50
_TERMINAL_NODES: Final = frozenset({"succeeded", "failed"})

_REMINDER_MESSAGE: Final = (
    "An engine run is active in this session ({run_id}). Before treating "
    "this as a natural stopping point, call recall to re-read the "
    "settlement and open todos from the ledger, and check state against "
    "/goal's succeeded/failed conditions — don't rely on this turn's own "
    "memory of them."
)
_SESSION_NUDGE: Final = (
    "This session just compacted. If an engine run is active, call "
    "recall now, before anything else — re-read the session ledger's "
    "settlement from disk rather than trusting whatever this compaction "
    "summarized it as."
)
_CODEX_SESSION_NUDGE: Final = (
    "This session just compacted. If an engine run is active, run "
    "<plugin-root>/scripts/task session recall <run-id> --dir "
    "<session-dir> outside the sandbox with host-level access before "
    "anything else — re-read the session ledger's settlement from disk "
    "rather than trusting whatever this compaction summarized."
)
_CODEX_SESSION_ID_MISSING: Final = (
    "Codex did not provide a session_id. Do not start or resume an engine run "
    "with a generated UUID; obtain the host session identity first."
)
_ESCALATED_MESSAGE: Final = (
    "This engine run's state ({run_id}, node '{node}') was already flagged "
    "as stale and still hasn't recorded a transition ({minutes} minutes "
    "now). If the work has genuinely moved past this node, call "
    "session.py state transition now; if not, that's also worth "
    "confirming rather than leaving open."
)


@dataclass(frozen=True)
class MarkerUpdate:
    path: Path
    data: dict[str, Any]


@dataclass(frozen=True)
class Policy:
    name: str
    evaluator: Callable[[Event, HostContext], Intent]

    def evaluate(self, event: Event, context: HostContext) -> Intent:
        return self.evaluator(event, context)


def _ledger_path(context: HostContext) -> Path:
    return Path.home() / ".bootgear" / "session" / f"{context.session_id}.md"


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
    if locked_path is not None:
        if locked_path != update.path:
            raise AdapterError("policy_apply_error", "marker update is outside its lock")
        _atomic_write(update.path, json.dumps(update.data, separators=(",", ":")))
        return
    with _marker_lock(update.path) as locked:
        if not locked:
            raise AdapterError("policy_apply_error", "marker lock was not acquired")
        _atomic_write(update.path, json.dumps(update.data, separators=(",", ":")))


def _event_marker(event: Event, context: HostContext) -> Path | None:
    if event.handler_kind == "stop_reminder" and event.hook_event_name in {
        "Stop",
        "PostToolUse",
    }:
        return _marker_path(context, "stop_reminder_state")
    if event.handler_kind == "state_nudge" and event.hook_event_name == "PostToolUse":
        return _marker_path(context, "state_nudge_state")
    return None


@contextmanager
def invocation_lock(event: Event, context: HostContext) -> Iterator[tuple[bool, Path | None]]:
    marker = _event_marker(event, context)
    if marker is None:
        yield True, None
        return
    nonblocking = (
        event.hook_event_name == "PostToolUse" and event.handler_kind == "state_nudge"
    )
    with _marker_lock(marker, nonblocking=nonblocking) as acquired:
        yield acquired, marker if acquired else None


def _read_settlement(text: str) -> dict[str, Any] | None:
    match = re.search(r"(?m)^## settlement\n(.*?)(?=\n## |\Z)", text, re.DOTALL)
    if match is None:
        return None
    try:
        import yaml
    except ImportError:
        return None
    try:
        value = yaml.safe_load(match.group(1))
    except (yaml.YAMLError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _goal_text(settlement: dict[str, Any] | None) -> str | None:
    if not settlement:
        return None
    goal = settlement.get("goal")
    if isinstance(goal, str) and goal.strip():
        return goal.strip()
    if isinstance(goal, dict):
        succeeded = goal.get("succeeded")
        failed = goal.get("failed")
        if (
            isinstance(succeeded, str)
            and succeeded.strip()
            and isinstance(failed, str)
            and failed.strip()
        ):
            return f"succeeded when {succeeded.strip()}\nfailed when {failed.strip()}"
    return None


def _read_text(path: Path) -> str | None:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    return value or None


def _principles(context: HostContext, settlement: dict[str, Any] | None) -> str | None:
    user_dir = ".claude" if context.host == "claude" else ".codex"
    sections: list[str] = []
    user_text = _read_text(Path.home() / user_dir / "principles.md")
    if user_text:
        sections.append(f"[user]\n{user_text}")
    project_text = _read_text(Path(context.cwd) / ".bootgear" / "config" / "principles.md")
    if project_text:
        sections.append(f"[project]\n{project_text}")
    if settlement:
        task = settlement.get("principles")
        if isinstance(task, str) and task.strip():
            sections.append(f"[task]\n{task.strip()}")
    return "\n\n".join(sections) if sections else None


def _session_recall(event: Event, context: HostContext) -> Intent:
    payload = event.payload
    source = payload.get("source")
    active = _active_ledger(context)
    if context.host == "codex":
        identity = (
            f"Codex session_id: {event.session_id}. Use this exact value as the engine "
            "run-id; do not generate a UUID or other replacement."
            if isinstance(event.session_id, str) and event.session_id
            else _CODEX_SESSION_ID_MISSING
        )
        if active is None:
            return Intent.add_context(identity)
        message = identity
        if source == "compact":
            message = f"{_CODEX_SESSION_NUDGE}\n\n{message}"
    else:
        if active is None:
            return Intent.observe()
        message = _SESSION_NUDGE
    settlement = _read_settlement(active[1])
    goal = _goal_text(settlement)
    if goal:
        label = "goal" if context.host == "codex" else "/goal"
        message = f"{message}\n\nThis run's {label}:\n{goal}"
    principles = _principles(context, settlement)
    if principles:
        message = f"{message}\n\nMerged principles (user/project/task):\n{principles}"
    return Intent.add_context(message)


def _should_nudge(state: dict[str, Any], now: float) -> bool:
    count = state.get("nudge_count", 0)
    last = state.get("last_nudge_at", 0.0)
    if not isinstance(count, int) or not isinstance(last, (int, float)):
        count, last = 0, 0.0
    if now - last >= _RAPID_SECONDS:
        state["nudge_count"] = 1
        state["last_nudge_at"] = now
        return True
    if count >= _MAX_NUDGES:
        state["nudge_count"] = 0
        return False
    state["nudge_count"] = count + 1
    state["last_nudge_at"] = now
    return True


def _normalise_codex_marker(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AdapterError("invalid_marker", "Codex reminder marker has invalid structure")
    turns = value.get("turns", [])
    if not isinstance(turns, list):
        raise AdapterError("invalid_marker", "Codex reminder marker has invalid structure")
    if any(
        not isinstance(turn, dict)
        or not isinstance(turn.get("turn_id"), str)
        or not turn.get("turn_id")
        or ("stop_seen" in turn and type(turn["stop_seen"]) is not bool)
        or ("fallback_reminded" in turn and type(turn["fallback_reminded"]) is not bool)
        for turn in turns
    ):
        raise AdapterError("invalid_marker", "Codex reminder marker has invalid structure")
    count = value.get("nudge_count", 0)
    last = value.get("last_nudge_at", 0.0)
    if (
        type(count) is not int
        or count < 0
        or isinstance(last, bool)
        or not isinstance(last, (int, float))
        or not math.isfinite(last)
    ):
        raise AdapterError("invalid_marker", "Codex reminder marker has invalid structure")
    value["turns"] = turns[-_MAX_TURNS:]
    return value


def _turn(state: dict[str, Any], turn_id: str) -> dict[str, Any] | None:
    for turn in reversed(state["turns"]):
        if turn["turn_id"] == turn_id:
            return turn
    return None


def _stop_claude(event: Event, context: HostContext) -> Intent:
    active = _active_ledger(context)
    if active is None or event.payload.get("stop_hook_active") is True:
        return Intent.observe()
    marker = _marker_path(context, "stop_reminder_state")
    state = _read_json(marker, {"nudge_count": 0, "last_nudge_at": 0.0})
    if not isinstance(state, dict):
        raise AdapterError("invalid_marker", "Claude reminder marker has invalid structure")
    count = state.get("nudge_count", 0)
    last = state.get("last_nudge_at", 0.0)
    if (
        type(count) is not int
        or count < 0
        or isinstance(last, bool)
        or not isinstance(last, (int, float))
        or not math.isfinite(last)
    ):
        raise AdapterError("invalid_marker", "Claude reminder marker has invalid structure")
    should_emit = _should_nudge(state, time.time())
    update = MarkerUpdate(marker, state)
    if not should_emit:
        return Intent.observe(update)
    message = _REMINDER_MESSAGE.format(run_id=event.session_id)
    return Intent.add_context(message, update)


def _stop_codex(event: Event, context: HostContext) -> Intent:
    active = _active_ledger(context)
    if active is None:
        return Intent.observe()
    marker = _marker_path(context, "stop_reminder_state")
    state = _normalise_codex_marker(
        _read_json(marker, {"turns": [], "nudge_count": 0, "last_nudge_at": 0.0})
    )
    turn_id = event.turn_id
    if not turn_id:
        return Intent.error_intent(AdapterError("invalid_field", "Codex Stop/PostToolUse needs turn_id"))
    current = _turn(state, turn_id)
    should_emit = False
    if event.hook_event_name == "Stop":
        if current is None:
            current = {"turn_id": turn_id, "stop_seen": False, "fallback_reminded": False}
            state["turns"].append(current)
        current["stop_seen"] = True
        if event.payload.get("stop_hook_active") is not True:
            should_emit = _should_nudge(state, time.time())
    else:
        if current is None:
            previous = state["turns"][-1] if state["turns"] else None
            current = {"turn_id": turn_id, "stop_seen": False, "fallback_reminded": False}
            state["turns"].append(current)
            if (
                previous is not None
                and not previous.get("stop_seen", False)
                and not previous.get("fallback_reminded", False)
            ):
                previous["fallback_reminded"] = True
                should_emit = _should_nudge(state, time.time())
    state["turns"] = state["turns"][-_MAX_TURNS:]
    update = MarkerUpdate(marker, state)
    if not should_emit:
        return Intent.observe(update)
    message = _REMINDER_MESSAGE.format(run_id=event.session_id)
    if event.hook_event_name == "Stop":
        return Intent.continue_(message, update)
    return Intent.add_context(message, update)


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
                str(context.task_command),
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
    if marker_value.get("last_nudged_identity") != identity:
        marker_value["last_nudged_identity"] = identity
        marker_value["identity_first_nudged_at"] = now
        marker_value["escalated_for_identity"] = False
        message = (
            "This engine run's state ({run_id}, node '{node}') hasn't recorded a "
            "transition in over {minutes} minutes. That doesn't necessarily mean "
            "the run is stuck — one node can legitimately span several tool calls "
            "— but check whether the current work has actually moved past this "
            "node and, if so, call session.py state transition to record it."
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
    text = message.format(run_id=event.session_id, node=node, minutes=int(elapsed // 60))
    return Intent.add_context(text, update)


def _compaction_observe(event: Event, context: HostContext) -> Intent:
    return Intent.observe()


def _policy_key(event: Event) -> tuple[str, str, str | None, str]:
    return (
        event.host,
        event.hook_event_name,
        event.manifest_matcher_pattern,
        event.handler_kind,
    )


POLICY_TABLE: dict[tuple[str, str, str | None, str], Policy] = {
    ("claude", "SessionStart", "compact", "session_recall"): Policy(
        "session_recall", _session_recall
    ),
    ("claude", "Stop", None, "stop_reminder"): Policy("stop_reminder", _stop_claude),
    ("claude", "PostToolUse", ".*", "state_nudge"): Policy("state_nudge", _state_nudge),
    ("claude", "PreCompact", "manual|auto", "compaction_observe"): Policy(
        "compaction_observe", _compaction_observe
    ),
    ("claude", "PostCompact", "manual|auto", "compaction_observe"): Policy(
        "compaction_observe", _compaction_observe
    ),
    ("codex", "SessionStart", "^(startup|resume|compact)$", "session_recall"): Policy(
        "session_recall", _session_recall
    ),
    ("codex", "Stop", None, "stop_reminder"): Policy("stop_reminder", _stop_codex),
    ("codex", "PostToolUse", ".*", "state_nudge"): Policy("state_nudge", _state_nudge),
    ("codex", "PostToolUse", ".*", "stop_reminder"): Policy(
        "stop_reminder", _stop_codex
    ),
    ("codex", "PreCompact", "manual|auto", "compaction_observe"): Policy(
        "compaction_observe", _compaction_observe
    ),
    ("codex", "PostCompact", "manual|auto", "compaction_observe"): Policy(
        "compaction_observe", _compaction_observe
    ),
}
HANDLER_MAP = POLICY_TABLE


def resolve(event: Event) -> Policy:
    handler = POLICY_TABLE.get(_policy_key(event))
    if handler is None:
        raise AdapterError("unsupported_handler", f"no static policy for {_policy_key(event)!r}")
    return handler


def evaluate(event: Event, context: HostContext) -> Intent:
    return resolve(event).evaluate(event, context)


def apply(
    intent: Intent,
    context: HostContext,
    *,
    locked_path: Path | None = None,
) -> None:
    if intent.effect is None:
        return
    if not isinstance(intent.effect, MarkerUpdate):
        raise AdapterError("policy_apply_error", "unknown policy effect")
    _apply_marker(intent.effect, locked_path=locked_path)
