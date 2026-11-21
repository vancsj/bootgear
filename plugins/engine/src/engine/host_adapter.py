# pyright: reportImportCycles=false

"""Shared normalization, dispatch, and rendering for engine hooks.

The adapter is intentionally small.  It owns the boundary between a host hook
process and the host-neutral policy module; it does not know about advisors,
mailboxes, or coordinator state.
"""
from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .host_contracts import (
    get_contract,
    host_hook_relative_path,
    host_root_environment,
    host_source_relative_path,
)
from .host_event_input import (
    _parse_json,
    _read_stdin,
    adapt,  # noqa: F401
    normalize_event,
)
from .host_types import (
    MAX_ERROR_BYTES,
    MAX_TRACE_LINE_BYTES,
    AdapterError,
    AdapterOutput,
    Event,
    HostContext,
    Intent,
    _bounded_text,
)


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
    if not all(_inside(root, path) for path in (source, hooks)):
        raise AdapterError("invalid_root", "host paths must remain inside plugin root")
    return HostContext(
        host=event.host,
        plugin_root=root,
        source_dir=source,
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
        if event.hook_event_name == "PreToolUse":
            body = {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": error.message,
                }
            }
            return AdapterOutput(stdout=json.dumps(body, separators=(",", ":")) + "\n",
                                 kind="deny")
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
    if intent.kind == "deny":
        if event.hook_event_name != "PreToolUse":
            error = AdapterError(
                "unsupported_capability", "deny is supported only for PreToolUse"
            )
            return AdapterOutput(
                stderr=_bounded_text(
                    f"engine hook adapter: {error.code}: {error.message}\n", MAX_ERROR_BYTES
                ),
                kind="error",
            )
        body = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": intent.reason or intent.content or "Blocked by Engine policy.",
            }
        }
        return AdapterOutput(stdout=json.dumps(body, separators=(",", ":")) + "\n",
                             kind="deny")
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
