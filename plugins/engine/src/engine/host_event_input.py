"""Decode and validate native host hook inputs."""

from __future__ import annotations

import json
import math
import re
import sys
from collections.abc import Mapping
from typing import Any

from .host_contracts import (
    SUPPORTED_HOSTS,
    EventContract,
    FieldSpec,
    get_contract,
)
from .host_types import (
    MAX_JSON_DEPTH,
    MAX_STDIN_BYTES,
    SCHEMA_VERSION,
    AdapterError,
    Event,
)


def _is_nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and not isinstance(value, bool) and bool(value)


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
    if spec.kind == "task_list":
        if not isinstance(value, list):
            raise AdapterError("invalid_field", f"{name} must be an array")
        invalid = [
            str(index) for index, item in enumerate(value)
            if not isinstance(item, dict)
            or any(not _is_nonempty_string(item.get(key)) for key in ("type", "status"))
        ]
        if invalid:
            raise AdapterError(
                "invalid_field",
                f"{name} entries need non-empty type and status; invalid indices: {', '.join(invalid)}",
            )
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
            else {"startup", "resume", "clear", "compact", "fork"}
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
    if "background_tasks" in payload:
        payload["background_tasks"] = [
            {"type": item["type"], "status": item["status"]}
            for item in payload["background_tasks"]
        ]

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
