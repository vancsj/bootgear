"""Read provider registrations and discover available Gear commands."""

from __future__ import annotations

import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path


class GearError(Exception):
    """A registration or routing error suitable for a CLI diagnostic."""

@dataclass(frozen=True)
class Reminder:
    event: str
    executable: tuple[str, ...]
    severity: str
    order: int
    dedupe: str

@dataclass(frozen=True)
class Plugin:
    name: str
    root: Path
    repository_root: Path
    commands: dict[str, tuple[str, ...]]
    reminders: tuple[Reminder, ...]

def _strings(value: object, *, field: str, source: Path) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or not all(isinstance(item, str) for item in value):
        raise GearError(f"{source}: {field} must be a non-empty list of strings")
    return tuple(value)

def _plugin_name(value: object, source: Path) -> str:
    if not isinstance(value, str) or not value or "/" in value or "\\" in value:
        raise GearError(f"{source}: plugin name must be a non-empty name")
    return value

def _load_plugin(path: Path, *, repository_root: Path) -> Plugin:
    try:
        with path.open("rb") as stream:
            document = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise GearError(f"could not read {path}: {exc}") from exc

    plugin = document.get("plugin")
    if not isinstance(plugin, dict):
        raise GearError(f"{path}: missing [plugin] table")
    name = _plugin_name(plugin.get("name"), path)

    commands_value = document.get("commands", {})
    if not isinstance(commands_value, dict):
        raise GearError(f"{path}: commands must be a table")
    commands: dict[str, tuple[str, ...]] = {}
    for command, definition in commands_value.items():
        if not isinstance(command, str) or not command or "/" in command:
            raise GearError(f"{path}: invalid command name {command!r}")
        if not isinstance(definition, dict):
            raise GearError(f"{path}: commands.{command} must be a table")
        commands[command] = _strings(definition.get("exec"), field=f"commands.{command}.exec", source=path)

    reminders_value = document.get("reminders", {})
    if not isinstance(reminders_value, dict):
        raise GearError(f"{path}: reminders must be a table")
    reminders: list[Reminder] = []
    for event, definition in reminders_value.items():
        if not isinstance(event, str) or not event or "/" in event:
            raise GearError(f"{path}: invalid reminder event {event!r}")
        if not isinstance(definition, dict):
            raise GearError(f"{path}: reminders.{event} must be a table")
        severity = definition.get("severity", "reminder")
        if severity not in {"reminder", "gate"}:
            raise GearError(f"{path}: reminders.{event}.severity must be reminder or gate")
        order = definition.get("order", 100)
        if not isinstance(order, int):
            raise GearError(f"{path}: reminders.{event}.order must be an integer")
        dedupe = definition.get("dedupe", f"{name}:{event}")
        if not isinstance(dedupe, str) or not dedupe:
            raise GearError(f"{path}: reminders.{event}.dedupe must be a non-empty string")
        reminders.append(Reminder(
            event=event,
            executable=_strings(definition.get("exec"), field=f"reminders.{event}.exec", source=path),
            severity=severity,
            order=order,
            dedupe=dedupe,
        ))

    return Plugin(
        name=name,
        root=path.parent,
        repository_root=repository_root,
        commands=commands,
        reminders=tuple(reminders),
    )

def _registration_paths(root: Path, plugin_roots: Sequence[Path]) -> list[Path]:
    registrations = list((root / "plugins").glob("*/gear.toml"))
    registrations.extend(plugin_root / "gear.toml" for plugin_root in plugin_roots)
    seen: set[Path] = set()
    unique: list[Path] = []
    for path in sorted(registrations):
        resolved = path.resolve()
        if resolved in seen or not resolved.is_file():
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique

def _load_plugins(root: Path, registrations: Sequence[Path]) -> dict[str, Plugin]:
    plugins: dict[str, Plugin] = {}
    for path in registrations:
        plugin = _load_plugin(path, repository_root=root)
        if plugin.name in plugins:
            other = plugins[plugin.name].root / "gear.toml"
            raise GearError(f"plugin {plugin.name!r} is registered by both {other} and {path}")
        plugins[plugin.name] = plugin
    return plugins

def discover(root: Path, plugin_roots: Sequence[Path] = ()) -> dict[str, Plugin]:
    return _load_plugins(root, _registration_paths(root, plugin_roots))
