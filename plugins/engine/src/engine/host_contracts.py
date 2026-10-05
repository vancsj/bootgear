"""Host-specific contracts for the small engine hook adapter.

The contract table is deliberately data, rather than a collection of
conditionals in the command wrapper.  Both packaged engine copies contain
the same table; the wrapper only chooses the host name and the host-native
root environment.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

HOST_CLAUDE: Final = "claude"
HOST_CODEX: Final = "codex"
SUPPORTED_HOSTS: Final = frozenset({HOST_CLAUDE, HOST_CODEX})
SUPPORTED_EVENTS: Final = frozenset(
    {"SessionStart", "Stop", "PostToolUse", "PreCompact", "PostCompact"}
)


@dataclass(frozen=True)
class HostRoot:
    environment: str
    source: Path
    hooks: Path
    task: Path


HOST_ROOTS: Final[dict[str, HostRoot]] = {
    HOST_CLAUDE: HostRoot(
        environment="CLAUDE_PLUGIN_ROOT",
        source=Path("src"),
        hooks=Path("hooks"),
        task=Path("bin") / "task",
    ),
    HOST_CODEX: HostRoot(
        environment="PLUGIN_ROOT",
        source=Path("src"),
        hooks=Path("hooks"),
        task=Path("scripts") / "task",
    ),
}


@dataclass(frozen=True)
class FieldSpec:
    """A known input field and the type policy applied to it."""

    kind: str
    nullable: bool = False
    required: bool = False
    values: tuple[str, ...] = ()


@dataclass(frozen=True)
class EventContract:
    """The checked-in contract for one host/event pair."""

    host: str
    event: str
    matcher_pattern: str
    matcher_field: str | None
    required: tuple[tuple[str, FieldSpec], ...]
    optional: tuple[tuple[str, FieldSpec], ...]
    handlers: tuple[str, ...]
    capabilities: frozenset[str]

    @property
    def fields(self) -> dict[str, FieldSpec]:
        return dict(self.required + self.optional)

    @property
    def required_names(self) -> tuple[str, ...]:
        return tuple(name for name, _ in self.required)


def _required(*names: str, kind: str = "string") -> tuple[tuple[str, FieldSpec], ...]:
    return tuple((name, FieldSpec(kind=kind, required=True)) for name in names)


def _optional(
    *names: str,
    kind: str = "string",
    nullable: bool = False,
) -> tuple[tuple[str, FieldSpec], ...]:
    return tuple((name, FieldSpec(kind=kind, nullable=nullable)) for name in names)


def _contract(
    host: str,
    event: str,
    matcher_pattern: str,
    matcher_field: str | None,
    required: tuple[tuple[str, FieldSpec], ...],
    optional: tuple[tuple[str, FieldSpec], ...],
    handlers: tuple[str, ...],
    capabilities: frozenset[str],
) -> EventContract:
    return EventContract(
        host=host,
        event=event,
        matcher_pattern=matcher_pattern,
        matcher_field=matcher_field,
        required=required,
        optional=optional,
        handlers=handlers,
        capabilities=capabilities,
    )


_COMMON_REQUIRED = _required("session_id", "cwd", "hook_event_name")
_COMMON_OPTIONAL = _optional("turn_id")
_NULLABLE_TEXT = ("transcript_path", "model", "permission_mode")


def _host_contracts(host: str) -> dict[str, EventContract]:
    if host == HOST_CLAUDE:
        return {
            "SessionStart": _contract(
                host,
                "SessionStart",
                "compact",
                "source",
                _COMMON_REQUIRED + _required("source"),
                _COMMON_OPTIONAL + _optional(*_NULLABLE_TEXT, nullable=True),
                ("session_recall",),
                frozenset({"observe", "add_context"}),
            ),
            "Stop": _contract(
                host,
                "Stop",
                "",
                None,
                _COMMON_REQUIRED + _required("stop_hook_active", kind="bool"),
                _COMMON_OPTIONAL
                + _optional("last_assistant_message", kind="nullable_text", nullable=True),
                ("stop_reminder",),
                frozenset({"observe", "add_context"}),
            ),
            "PostToolUse": _contract(
                host,
                "PostToolUse",
                ".*",
                "tool_name",
                _COMMON_REQUIRED
                + _required("tool_name")
                + _required("tool_input", "tool_response", kind="json"),
                _COMMON_OPTIONAL
                + _optional("tool_use_id", "agent_id", "agent_type")
                + _optional("permission_mode", nullable=True),
                ("state_nudge",),
                frozenset({"observe", "add_context"}),
            ),
            "PreCompact": _contract(
                host,
                "PreCompact",
                "manual|auto",
                "trigger",
                _COMMON_REQUIRED + _required("trigger"),
                _COMMON_OPTIONAL
                + _optional("custom_instructions", kind="nullable_text", nullable=True),
                ("compaction_observe",),
                frozenset({"observe"}),
            ),
            "PostCompact": _contract(
                host,
                "PostCompact",
                "manual|auto",
                "trigger",
                _COMMON_REQUIRED + _required("trigger"),
                _COMMON_OPTIONAL
                + _optional("compact_summary", kind="nullable_text", nullable=True),
                ("compaction_observe",),
                frozenset({"observe"}),
            ),
        }
    if host == HOST_CODEX:
        return {
            "SessionStart": _contract(
                host,
                "SessionStart",
                "^(startup|resume|compact)$",
                "source",
                _COMMON_REQUIRED + _required("source"),
                _COMMON_OPTIONAL + _optional(*_NULLABLE_TEXT, nullable=True),
                ("session_recall",),
                frozenset({"observe", "add_context"}),
            ),
            "Stop": _contract(
                host,
                "Stop",
                "",
                None,
                _COMMON_REQUIRED
                + _required("turn_id")
                + _required("stop_hook_active", kind="bool"),
                _optional("last_assistant_message", kind="nullable_text", nullable=True)
                + _optional("permission_mode", nullable=True),
                ("stop_reminder",),
                frozenset({"observe", "add_context", "continue"}),
            ),
            "PostToolUse": _contract(
                host,
                "PostToolUse",
                ".*",
                "tool_name",
                _COMMON_REQUIRED
                + _required("turn_id", "tool_name", "tool_use_id")
                + _required("tool_input", kind="json"),
                _optional("tool_response", kind="json")
                + _optional("agent_id", "agent_type")
                + _optional("permission_mode", nullable=True),
                ("state_nudge", "stop_reminder"),
                frozenset({"observe", "add_context"}),
            ),
            "PreCompact": _contract(
                host,
                "PreCompact",
                "manual|auto",
                "trigger",
                _COMMON_REQUIRED + _required("turn_id", "trigger"),
                (),
                ("compaction_observe",),
                frozenset({"observe"}),
            ),
            "PostCompact": _contract(
                host,
                "PostCompact",
                "manual|auto",
                "trigger",
                _COMMON_REQUIRED + _required("turn_id", "trigger"),
                (),
                ("compaction_observe",),
                frozenset({"observe"}),
            ),
        }
    raise ValueError(f"unsupported host: {host}")


HOST_CONTRACTS: Final[dict[str, dict[str, EventContract]]] = {
    host: _host_contracts(host) for host in (HOST_CLAUDE, HOST_CODEX)
}


def get_contract(host: str, event: str) -> EventContract | None:
    return HOST_CONTRACTS.get(host, {}).get(event)


def expected_handler(host: str, event: str, handler: str) -> bool:
    contract = get_contract(host, event)
    return contract is not None and handler in contract.handlers


def host_root_environment(host: str) -> str:
    try:
        return HOST_ROOTS[host].environment
    except KeyError as error:
        raise ValueError(f"unsupported host: {host}") from error


def host_task_relative_path(host: str) -> Path:
    try:
        return HOST_ROOTS[host].task
    except KeyError as error:
        raise ValueError(f"unsupported host: {host}") from error


def host_source_relative_path(host: str) -> Path:
    try:
        return HOST_ROOTS[host].source
    except KeyError as error:
        raise ValueError(f"unsupported host: {host}") from error


def host_hook_relative_path() -> Path:
    return Path("hooks")
