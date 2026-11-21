"""Host-neutral policies for the engine hook adapter.

Each handler has a side-effect-free evaluation phase and a separate apply phase.
Evaluation may inspect the existing session ledger and marker state, but it
never writes a marker or emits host JSON. The adapter only calls apply after
validation and capability selection have succeeded.
"""
from __future__ import annotations

import math
import re
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from bootgear_cli.clikit import gear_command

from .host_adapter import AdapterError, Event, HostContext, Intent
from .policy_markers import (
    _CLOSED_HEADING_RE,
    MarkerUpdate,
    _active_ledger,
    _apply_marker,
    _ledger_path,
    _marker_lock,
    _marker_path,
    _read_json,
    _read_text,
)
from .policy_state_nudge import _state_nudge
from .subagent_state import has_running_descendant
from .validate_standard import rule_headings

_RAPID_SECONDS: Final = 30
_MAX_NUDGES: Final = 1
_MAX_TURNS: Final = 32
_CODEX_RUNTIME_SOURCES: Final = frozenset({"startup", "resume", "clear", "fork"})
_STANDARD_FILES: Final = ("review-standard", "test-standard")
_STANDARDS_HEADER: Final = "Standards (read each file in full before you judge or write):"
_QUESTION_RETRY_MARKER: Final = "question_retry_state"
_QUESTION_RETRY_SECONDS: Final = 30

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
    f"{gear_command('engine', 'task')} session recall --dir "
    "<session-dir> before anything else — re-read the session ledger's "
    "settlement from disk rather than trusting whatever this compaction "
    "summarized."
)
_CODEX_SESSION_ID_MISSING: Final = (
    "Codex did not provide a session_id. Do not start or resume an engine run "
    "with a generated UUID; obtain the host session identity first."
)


@dataclass(frozen=True)
class Policy:
    name: str
    evaluator: Callable[[Event, HostContext], Intent]

    def evaluate(self, event: Event, context: HostContext) -> Intent:
        return self.evaluator(event, context)


def _event_marker(event: Event, context: HostContext) -> Path | None:
    if event.handler_kind == "question_boundary" and event.hook_event_name == "PreToolUse":
        return _marker_path(context, _QUESTION_RETRY_MARKER)
    if (
        event.host == "codex"
        and event.handler_kind == "session_recall"
        and event.hook_event_name == "SessionStart"
        and event.payload.get("source") in _CODEX_RUNTIME_SOURCES
    ):
        return _marker_path(context, "stop_reminder_state")
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


def _principles(context: HostContext, settlement: dict[str, Any] | None) -> str | None:
    user_dir = ".claude" if context.host == "claude" else ".codex"
    sections: list[str] = []
    user_text = _read_text(Path.home() / user_dir / "principles.md")
    if user_text:
        sections.append(f"[user]\n{user_text.strip()}")
    project_text = _read_text(Path(context.cwd) / ".bootgear" / "config" / "principles.md")
    if project_text:
        sections.append(f"[project]\n{project_text.strip()}")
    if settlement:
        task = settlement.get("principles")
        if isinstance(task, str) and task.strip():
            sections.append(f"[task]\n{task.strip()}")
    return "\n\n".join(sections) if sections else None


def _standards(context: HostContext) -> str | None:
    lines: list[str] = []
    for name in _STANDARD_FILES:
        relative = f".bootgear/config/{name}.md"
        text = _read_text(Path(context.cwd) / relative)
        if text is None:
            continue
        rules = ", ".join(
            f"{rule_id} [{severity}]" for rule_id, severity in rule_headings(text)
        )
        lines.append(f"[{name}] {relative}: {rules}" if rules else f"[{name}] {relative}")
    if not lines:
        return None
    return "\n".join([_STANDARDS_HEADER, *lines])


def _session_recall(event: Event, context: HostContext) -> Intent:
    payload = event.payload
    source = payload.get("source")
    update = None
    if context.host == "codex" and source in _CODEX_RUNTIME_SOURCES:
        marker = _marker_path(context, "stop_reminder_state")
        state = _normalise_codex_marker(
            _read_json(marker, {"turns": [], "nudge_count": 0, "last_nudge_at": 0.0})
        )
        state["runtime_started_at"] = time.time()
        update = MarkerUpdate(marker, state)
    active = _active_ledger(context)
    if context.host == "codex":
        identity = (
            f"Codex session_id: {event.session_id}. It is the engine run id. Engine commands "
            "read it from the session environment; omit <run-id> and never generate a replacement."
            if isinstance(event.session_id, str) and event.session_id
            else _CODEX_SESSION_ID_MISSING
        )
        parts = [identity]
        if active is not None and source == "compact":
            parts.insert(0, _CODEX_SESSION_NUDGE)
    else:
        parts = [_SESSION_NUDGE] if active is not None and source == "compact" else []
    if active is None:
        return Intent.add_context("\n\n".join(parts), update) if parts else Intent.observe(update)
    settlement = _read_settlement(active[1])
    goal = _goal_text(settlement)
    if goal:
        label = "goal" if context.host == "codex" else "/goal"
        parts.append(f"This run's {label}:\n{goal}")
    principles = _principles(context, settlement)
    if principles:
        parts.append(f"Merged principles (user/project/task):\n{principles}")
    standards = _standards(context)
    if standards:
        parts.append(standards)
    return Intent.add_context("\n\n".join(parts), update) if parts else Intent.observe(update)


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
    if "runtime_started_at" in value:
        started = value["runtime_started_at"]
        if isinstance(started, bool) or not isinstance(started, (int, float)) or not math.isfinite(started):
            raise AdapterError("invalid_marker", "Codex runtime boundary has invalid structure")
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
    if any(
        task["type"] == "subagent" and task["status"] == "running"
        for task in event.payload.get("background_tasks", [])
    ):
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
    if has_running_descendant(event.session_id, state.get("runtime_started_at")):
        return Intent.observe()
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


def _question_boundary(event: Event, context: HostContext) -> Intent:
    path = _ledger_path(context)
    if not path.is_file():
        return Intent.observe()
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise AdapterError("ledger_read_error", "active Engine ledger could not be read") from error
    if _CLOSED_HEADING_RE.search(text):
        return Intent.observe()
    settlement = _read_settlement(text)
    if settlement is None:
        raise AdapterError("invalid_settlement", "active Engine ledger has an invalid settlement")
    autonomy = settlement.get("autonomy")
    if not isinstance(autonomy, dict) or autonomy.get("no_further_questions") is not True:
        return Intent.observe()

    marker_path = _marker_path(context, _QUESTION_RETRY_MARKER)
    state = _read_json(marker_path, {})
    now = time.monotonic()
    denied_at = state.get("denied_at") if isinstance(state, dict) else None
    if isinstance(denied_at, float) and 0 <= now - denied_at <= _QUESTION_RETRY_SECONDS:
        return Intent.observe(MarkerUpdate(marker_path, None))
    return Intent.deny(
        "An Engine run is active with no_further_questions: true. "
        f"If you still need to ask, retry within {_QUESTION_RETRY_SECONDS} seconds.",
        MarkerUpdate(marker_path, {"denied_at": now}),
    )


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
    ("claude", "SessionStart", "startup|clear|compact", "session_recall"): Policy(
        "session_recall", _session_recall
    ),
    ("claude", "Stop", None, "stop_reminder"): Policy("stop_reminder", _stop_claude),
    ("claude", "PreToolUse", "^AskUserQuestion$", "question_boundary"): Policy(
        "question_boundary", _question_boundary
    ),
    ("claude", "PostToolUse", ".*", "state_nudge"): Policy("state_nudge", _state_nudge),
    ("claude", "PreCompact", "manual|auto", "compaction_observe"): Policy(
        "compaction_observe", _compaction_observe
    ),
    ("claude", "PostCompact", "manual|auto", "compaction_observe"): Policy(
        "compaction_observe", _compaction_observe
    ),
    ("codex", "SessionStart", "^(startup|resume|clear|compact|fork)$", "session_recall"): Policy(
        "session_recall", _session_recall
    ),
    ("codex", "Stop", None, "stop_reminder"): Policy("stop_reminder", _stop_codex),
    ("codex", "PreToolUse", "^request_user_input$", "question_boundary"): Policy(
        "question_boundary", _question_boundary
    ),
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
