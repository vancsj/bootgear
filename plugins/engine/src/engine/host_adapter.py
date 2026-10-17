# pyright: reportImportCycles=false

"""Shared normalization, dispatch, and rendering for engine hooks.

The adapter is intentionally small.  It owns the boundary between a host hook
process and the host-neutral policy module; it does not know about advisors,
mailboxes, or coordinator state.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

from .host_contracts import (
    SUPPORTED_HOSTS,
    EventContract,
    FieldSpec,
    get_contract,
    host_hook_relative_path,
    host_root_environment,
    host_source_relative_path,
    host_task_relative_path,
)

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
    task_command: Path
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
            "task_command": str(self.task_command),
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


def _is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and not isinstance(value, bool) and bool(value)


def _bounded_text(value: str, maximum: int) -> str:
    raw = value.encode("utf-8", errors="replace")
    if len(raw) <= maximum:
        return value
    return raw[:maximum].decode("utf-8", errors="ignore")


def _validate_value(name: str, value: Any, spec: FieldSpec) -> None:
    if value is None:
        if spec.nullable:
            return
        raise AdapterError("invalid_field", f"{name} must not be null")

    if spec.kind == "nullable_text":
        if not isinstance(value, str) or isinstance(value, bool):
            raise AdapterError("invalid_field", f"{name} must be a string or null")
        return
    if spec.kind in {"string", "source", "trigger"}:
        if not _is_nonempty_string(value):
            raise AdapterError("invalid_field", f"{name} must be a non-empty string")
        return
    if spec.kind == "bool":
        if type(value) is not bool:
            raise AdapterError("invalid_field", f"{name} must be a boolean")
        return
    if spec.kind == "json":
        if not _is_json_value(value):
            raise AdapterError("invalid_field", f"{name} must be a JSON value")
        return
    if spec.kind == "mixed":
        return
    raise AdapterError("invalid_contract", f"unknown field kind for {name}: {spec.kind}")


def _is_json_value(value: Any) -> bool:
    pending = [(value, 0)]
    while pending:
        current, depth = pending.pop()
        if current is None or isinstance(current, (str, bool, int)):
            continue
        if isinstance(current, float):
            if not math.isfinite(current):
                return False
            continue
        if isinstance(current, list):
            if depth >= MAX_JSON_DEPTH:
                raise AdapterError("value_too_deep", "JSON value exceeds the maximum nesting depth")
            pending.extend((item, depth + 1) for item in current)
            continue
        if isinstance(current, dict):
            if depth >= MAX_JSON_DEPTH:
                raise AdapterError("value_too_deep", "JSON value exceeds the maximum nesting depth")
            if not all(isinstance(key, str) for key in current):
                return False
            pending.extend((item, depth + 1) for item in current.values())
            continue
        return False
    return True


def _validate_known_fields(raw: Mapping[str, Any], contract: EventContract) -> None:
    fields = contract.fields
    for name, spec in contract.required:
        if name not in raw:
            raise AdapterError("missing_field", f"missing required field: {name}")
        _validate_value(name, raw[name], spec)
    for name, spec in contract.optional:
        if name in raw:
            _validate_value(name, raw[name], spec)

    # The host contracts use these two identity fields as an all-or-nothing
    # pair.  Null is not an absent identity and is therefore rejected.
    if "agent_id" in fields or "agent_type" in fields:
        present_id = "agent_id" in raw
        present_type = "agent_type" in raw
        if present_id != present_type:
            raise AdapterError(
                "contradictory_identity",
                "agent_id and agent_type must be supplied together",
            )
        if present_id and (
            not _is_nonempty_string(raw["agent_id"])
            or not _is_nonempty_string(raw["agent_type"])
        ):
                raise AdapterError(
                    "contradictory_identity",
                    "agent_id and agent_type must be non-empty strings",
                )


def _matcher_value(raw: Mapping[str, Any], contract: EventContract) -> str | None:
    if contract.matcher_field is None:
        return None
    value = raw.get(contract.matcher_field)
    if not _is_nonempty_string(value):
        raise AdapterError(
            "invalid_matcher",
            f"{contract.matcher_field} must be a non-empty string",
        )
    return value


def _check_matcher(contract: EventContract, supplied: str, value: str | None) -> str | None:
    if not isinstance(supplied, str):
        raise AdapterError("invalid_matcher", "matcher pattern must be a string")
    if contract.event == "Stop":
        if supplied != "":
            raise AdapterError("invalid_matcher", "Stop requires an empty matcher pattern")
        return None
    if not supplied:
        raise AdapterError("invalid_matcher", "matcher pattern must be non-empty")
    if supplied != contract.matcher_pattern:
        raise AdapterError(
            "invalid_matcher",
            f"expected matcher pattern {contract.matcher_pattern!r}",
        )
    if value is None or re.fullmatch(supplied, value) is None:
        raise AdapterError(
            "matcher_mismatch",
            f"matcher value does not match {supplied!r}",
        )
    return supplied


def _check_event_values(raw: Mapping[str, Any], contract: EventContract, value: str | None) -> None:
    if contract.event == "SessionStart":
        allowed = (
            {"startup", "clear", "compact"}
            if contract.host == "claude"
            else {"startup", "resume", "clear", "compact"}
        )
        if raw.get("source") not in allowed:
            raise AdapterError("invalid_matcher", "unsupported SessionStart source")
    elif contract.event in {"PreCompact", "PostCompact"}:
        if raw.get("trigger") not in {"manual", "auto"}:
            raise AdapterError("invalid_matcher", "trigger must be manual or auto")
    if contract.event == "Stop" and value is not None:
        raise AdapterError("invalid_matcher", "Stop has no matcher value")


def normalize_event(
    host: str,
    raw: Mapping[str, Any],
    matcher_pattern: str,
    handler_kind: str,
) -> Event:
    """Validate and normalize one fixed-command host invocation."""

    if host not in SUPPORTED_HOSTS:
        raise AdapterError("unsupported_host", f"unsupported host: {host}")
    if not isinstance(raw, Mapping):
        raise AdapterError("invalid_input", "hook input must be a JSON object")
    if not isinstance(handler_kind, str) or not handler_kind:
        raise AdapterError("invalid_handler", "handler must be a non-empty string")

    event = raw.get("hook_event_name")
    if not _is_nonempty_string(event):
        raise AdapterError("invalid_event", "hook_event_name must be a non-empty string")
    event_name = str(event)
    contract = get_contract(host, event_name)
    if contract is None:
        raise AdapterError("unsupported_event", f"unsupported hook event: {event}")
    if handler_kind not in contract.handlers:
        raise AdapterError(
            "unsupported_handler",
            f"{handler_kind!r} is not registered for {host}/{event}",
        )

    _validate_known_fields(raw, contract)
    value = _matcher_value(raw, contract)
    normalized_pattern = _check_matcher(contract, matcher_pattern, value)
    _check_event_values(raw, contract, value)

    payload: dict[str, Any] = {}
    for name in contract.fields:
        if name in raw and name not in {"session_id", "cwd", "hook_event_name", "turn_id"}:
            payload[name] = raw[name]

    turn_id = raw.get("turn_id")
    if turn_id is not None and not _is_nonempty_string(turn_id):
        raise AdapterError("invalid_field", "turn_id must be a non-empty string")

    return Event(
        schema_version=SCHEMA_VERSION,
        host=host,
        session_id=raw["session_id"],
        cwd=raw["cwd"],
        hook_event_name=contract.event,
        manifest_matcher_pattern=normalized_pattern,
        matcher_value=value,
        handler_kind=handler_kind,
        payload=payload,
        turn_id=turn_id,
    )


def adapt(host: str, raw: Mapping[str, Any], matcher_pattern: str, handler_kind: str) -> Event:
    """Public short name for `normalize_event`."""

    return normalize_event(host, raw, matcher_pattern, handler_kind)

def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        return False
    return True


def host_context(
    event: Event,
    *,
    plugin_root: str | os.PathLike[str] | None = None,
    environ: Mapping[str, str] | None = None,
) -> HostContext:
    """Build and validate the host root paths passed to policy."""

    env = os.environ if environ is None else environ
    root_value = plugin_root or env.get(host_root_environment(event.host))
    if not root_value:
        raise AdapterError(
            "invalid_root",
            f"{host_root_environment(event.host)} is required for the {event.host} adapter",
        )
    root = Path(root_value).expanduser().resolve(strict=False)
    source = (root / host_source_relative_path(event.host)).resolve(strict=False)
    hooks = (root / host_hook_relative_path()).resolve(strict=False)
    task = (root / host_task_relative_path(event.host)).resolve(strict=False)
    if not all(_inside(root, path) for path in (source, hooks, task)):
        raise AdapterError("invalid_root", "host paths must remain inside plugin root")
    return HostContext(
        host=event.host,
        plugin_root=root,
        source_dir=source,
        task_command=task,
        hook_dir=hooks,
        cwd=event.cwd,
        session_id=event.session_id,
        event=event.hook_event_name,
        matcher_pattern=event.manifest_matcher_pattern,
        matcher_value=event.matcher_value,
        handler_kind=event.handler_kind,
    )


def dispatch(event: Event, context: HostContext | None = None) -> Intent:
    """Select the static policy for an already validated event."""

    if context is None:
        try:
            context = host_context(event)
        except AdapterError as error:
            return Intent.error_intent(error)
    try:
        from . import policy

        return policy.evaluate(event, context)
    except AdapterError as error:
        return Intent.error_intent(error)
    except Exception as error:  # noqa: BLE001 - fail closed at the host boundary
        return Intent.error_intent(AdapterError("policy_error", str(error) or "policy failed"))


def apply(intent: Intent, context: HostContext) -> None:
    """Apply a policy effect after evaluation has produced a supported intent."""

    if intent.kind in {"error"} or intent.error is not None:
        return
    from . import policy

    policy.apply(intent, context)


def dispatch_and_apply(event: Event, context: HostContext) -> Intent:
    """Evaluate and apply one policy under its marker transaction lock."""

    from . import policy

    contract = get_contract(event.host, event.hook_event_name)
    try:
        with policy.invocation_lock(event, context) as (proceed, locked_path):
            if not proceed:
                return Intent.observe()
            intent = dispatch(event, context)
            if (
                intent.kind != "error"
                and contract is not None
                and intent.kind in contract.capabilities
            ):
                policy.apply(intent, context, locked_path=locked_path)
            return intent
    except AdapterError as error:
        return Intent.error_intent(error)
    except Exception as error:  # noqa: BLE001 - fail closed at the host boundary
        return Intent.error_intent(
            AdapterError("policy_apply_error", str(error) or "policy invocation failed")
        )


normalize = normalize_event
build_context = host_context
apply_intent = apply


def render(intent: Intent, event: Event) -> AdapterOutput:
    """Render a normalized intent using the selected host contract."""

    if intent.kind == "error":
        error = intent.error or AdapterError("adapter_error", intent.reason or "adapter error")
        return AdapterOutput(
            stderr=_bounded_text(f"engine hook adapter: {error.code}: {error.message}\n", MAX_ERROR_BYTES),
            kind="error",
        )
    contract = get_contract(event.host, event.hook_event_name)
    if contract is None or intent.kind not in contract.capabilities:
        error = AdapterError(
            "unsupported_capability",
            f"{intent.kind} is unsupported for {event.host}/{event.hook_event_name}",
        )
        return AdapterOutput(
            stderr=_bounded_text(f"engine hook adapter: {error.code}: {error.message}\n", MAX_ERROR_BYTES),
            kind="error",
        )
    if intent.kind == "observe":
        return AdapterOutput(kind="observe")
    if intent.kind == "add_context":
        content = intent.content or ""
        body = {
            "hookSpecificOutput": {
                "hookEventName": event.hook_event_name,
                "additionalContext": content,
            }
        }
        return AdapterOutput(
            stdout=json.dumps(body, separators=(",", ":")) + "\n",
            kind="add_context",
            context_present=bool(content),
        )
    if intent.kind == "continue":
        if event.host != "codex" or event.hook_event_name != "Stop":
            error = AdapterError(
                "unsupported_capability",
                "continue is supported only for the Codex Stop hook",
            )
            return AdapterOutput(
                stderr=_bounded_text(
                    f"engine hook adapter: {error.code}: {error.message}\n", MAX_ERROR_BYTES
                ),
                kind="error",
            )
        body = {"decision": "block", "reason": intent.reason or intent.content or ""}
        return AdapterOutput(
            stdout=json.dumps(body, separators=(",", ":")) + "\n",
            kind="continue",
        )
    error = AdapterError("invalid_decision", f"unknown decision: {intent.kind}")
    return AdapterOutput(
        stderr=_bounded_text(f"engine hook adapter: {error.code}: {error.message}\n", MAX_ERROR_BYTES),
        kind="error",
    )


def render_decision(intent: Intent, event: Event) -> AdapterOutput:
    return render(intent, event)


def _parse_json(data: bytes) -> Mapping[str, Any]:
    class DuplicateKey(ValueError):
        pass

    def pairs(pairs_list: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs_list:
            if key in result:
                raise DuplicateKey(f"duplicate JSON field: {key}")
            result[key] = value
        return result

    def invalid_constant(value: str) -> None:
        raise ValueError(f"invalid JSON constant: {value}")

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise AdapterError("invalid_input", "stdin is not UTF-8") from error
    try:
        value = json.loads(
            text or "{}",
            object_pairs_hook=pairs,
            parse_constant=invalid_constant,
        )
    except DuplicateKey as error:
        raise AdapterError("invalid_input", str(error)) from error
    except json.JSONDecodeError as error:
        raise AdapterError("invalid_input", f"invalid JSON: {error.msg}") from error
    except ValueError as error:
        raise AdapterError("invalid_input", str(error)) from error
    except RecursionError as error:
        raise AdapterError(
            "value_too_deep", "JSON input exceeds the maximum nesting depth"
        ) from error
    if not isinstance(value, Mapping):
        raise AdapterError("invalid_input", "hook input must be a JSON object")
    return value


def _read_stdin(stream: Any = None) -> bytes:
    stream = sys.stdin if stream is None else stream
    binary = getattr(stream, "buffer", None)
    value = (
        binary.read(MAX_STDIN_BYTES + 1)
        if binary is not None
        else stream.read(MAX_STDIN_BYTES + 1)
    )
    if isinstance(value, str):
        value = value.encode("utf-8")
    if not isinstance(value, bytes):
        raise AdapterError("invalid_input", "stdin did not provide bytes")
    if len(value) > MAX_STDIN_BYTES:
        raise AdapterError("input_too_large", "stdin exceeds 1 MiB")
    return value


def _trace(
    event: Event | None,
    handler: str,
    intent: Intent,
    output: AdapterOutput,
    environ: Mapping[str, str] | None = None,
) -> None:
    env = os.environ if environ is None else environ
    path_value = env.get("BOOTGEAR_HOST_ADAPTER_TRACE_FILE")
    if not path_value:
        return
    row = {
        "event": event.hook_event_name if event is not None else None,
        "matcher": event.manifest_matcher_pattern if event is not None else None,
        "handler": handler,
        "decision": intent.kind,
        "rendered_result": output.kind,
        "context_present": output.context_present,
        "exit": output.exit_code,
    }
    line = json.dumps(row, separators=(",", ":"), sort_keys=True) + "\n"
    if len(line.encode("utf-8")) > MAX_TRACE_LINE_BYTES:
        return
    try:
        trace_path = Path(path_value)
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(trace_path), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.fchmod(fd, 0o600)
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)
    except OSError:
        pass


def _parse_arguments(argv: list[str] | None) -> tuple[str, str]:
    values = list(sys.argv[1:] if argv is None else argv)
    if len(values) != 4:
        raise AdapterError("invalid_arguments", "expected --handler and --matcher-pattern")
    parsed: dict[str, str] = {}
    index = 0
    while index < len(values):
        name = values[index]
        if name not in {"--handler", "--matcher-pattern"} or name in parsed:
            raise AdapterError("invalid_arguments", "expected --handler and --matcher-pattern")
        value = values[index + 1]
        if value.startswith("--") or (name == "--handler" and not value):
            raise AdapterError("invalid_arguments", "expected --handler and --matcher-pattern")
        parsed[name] = value
        index += 2
    if "--handler" not in parsed or "--matcher-pattern" not in parsed:
        raise AdapterError("invalid_arguments", "expected --handler and --matcher-pattern")
    return parsed["--handler"], parsed["--matcher-pattern"]


def run(
    host: str,
    argv: list[str] | None = None,
    *,
    stdin: Any = None,
    stdout: Any = None,
    stderr: Any = None,
    environ: Mapping[str, str] | None = None,
) -> int:
    """Run one installed adapter invocation.  All failures are non-controlling."""

    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    env = os.environ if environ is None else environ
    handler = ""
    event: Event | None = None
    intent = Intent.observe()
    try:
        handler, matcher_pattern = _parse_arguments(argv)
        if not handler:
            raise AdapterError("invalid_arguments", "expected --handler and --matcher-pattern")
        raw = _parse_json(_read_stdin(stdin))
        event = normalize_event(host, raw, matcher_pattern, handler)
        context = host_context(event, environ=env)
        intent = dispatch_and_apply(event, context)
        output = render(intent, event) if event is not None else AdapterOutput(kind="error")
    except AdapterError as error:
        intent = Intent.error_intent(error)
        output = AdapterOutput(
            stderr=_bounded_text(
                f"engine hook adapter: {error.code}: {error.message}\n", MAX_ERROR_BYTES
            ),
            kind="error",
        )
    _trace(event, handler, intent, output, env)
    if output.stdout:
        stdout.write(output.stdout)
    if output.stderr:
        stderr.write(output.stderr)
    return output.exit_code
