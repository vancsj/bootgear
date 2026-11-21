"""Shared data types used by the Engine host adapter."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

MAX_STDIN_BYTES: Final = 1024 * 1024
MAX_TRACE_LINE_BYTES: Final = 4 * 1024
MAX_ERROR_BYTES: Final = 1024
MAX_JSON_DEPTH: Final = 128
SCHEMA_VERSION: Final = 1


class AdapterError(Exception):
    """A bounded, non-controlling adapter failure."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


@dataclass(frozen=True)
class Event:
    """The host-neutral event passed to a policy."""

    host: str
    session_id: str
    cwd: str
    hook_event_name: str
    manifest_matcher_pattern: str | None
    matcher_value: str | None
    handler_kind: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    turn_id: str | None = None
    schema_version: int = SCHEMA_VERSION

    @property
    def event(self) -> str:
        """Compatibility alias for callers that call the event name `event`."""

        return self.hook_event_name

    @property
    def matcher_pattern(self) -> str | None:
        return self.manifest_matcher_pattern

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": self.schema_version,
            "host": self.host,
            "session_id": self.session_id,
            "cwd": self.cwd,
            "hook_event_name": self.hook_event_name,
            "manifest_matcher_pattern": self.manifest_matcher_pattern,
            "matcher_value": self.matcher_value,
            "handler_kind": self.handler_kind,
            "payload": dict(self.payload),
        }
        if self.turn_id is not None:
            result["turn_id"] = self.turn_id
        return result

    def to_dict(self) -> dict[str, Any]:
        return self.as_dict()


@dataclass(frozen=True)
class HostContext:
    """Host/runtime paths and event metadata made available to policies."""

    host: str
    plugin_root: Path
    source_dir: Path
    hook_dir: Path
    cwd: str
    session_id: str
    event: str
    matcher_pattern: str | None
    matcher_value: str | None
    handler_kind: str

    @property
    def hook_event_name(self) -> str:
        return self.event

    def as_dict(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "plugin_root": str(self.plugin_root),
            "source_dir": str(self.source_dir),
            "hook_dir": str(self.hook_dir),
            "cwd": self.cwd,
            "session_id": self.session_id,
            "event": self.event,
            "matcher_pattern": self.matcher_pattern,
            "matcher_value": self.matcher_value,
            "handler_kind": self.handler_kind,
        }


@dataclass(frozen=True)
class Intent:
    """A policy result before host rendering."""

    kind: str
    content: str | None = None
    reason: str | None = None
    effect: Any = None
    error: AdapterError | None = None

    @classmethod
    def observe(cls, effect: Any = None) -> Intent:
        return cls("observe", effect=effect)

    @classmethod
    def add_context(cls, content: str, effect: Any = None) -> Intent:
        return cls("add_context", content=content, effect=effect)

    @classmethod
    def continue_(cls, reason: str, effect: Any = None) -> Intent:
        return cls("continue", content=reason, reason=reason, effect=effect)

    @classmethod
    def deny(cls, reason: str, effect: Any = None) -> Intent:
        return cls("deny", content=reason, reason=reason, effect=effect)

    @classmethod
    def error_intent(cls, error: AdapterError) -> Intent:
        return cls("error", reason=error.message, error=error)

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"kind": self.kind}
        if self.content is not None:
            result["content"] = self.content
        if self.reason is not None and self.reason != self.content:
            result["reason"] = self.reason
        if self.error is not None:
            result["error"] = self.error.as_dict()
        return result

    def to_dict(self) -> dict[str, Any]:
        return self.as_dict()


@dataclass(frozen=True)
class AdapterOutput:
    """The process result returned by the renderer."""

    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    kind: str = "observe"
    context_present: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit": self.exit_code,
            "kind": self.kind,
            "context_present": self.context_present,
        }


NormalizedEvent = Event
Decision = Intent
Output = AdapterOutput


def _bounded_text(value: str, maximum: int) -> str:
    raw = value.encode("utf-8", errors="replace")
    if len(raw) <= maximum:
        return value
    return raw[:maximum].decode("utf-8", errors="ignore")
