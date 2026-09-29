#!/usr/bin/env python3
"""Route bootgear commands and lifecycle events to registered plugins."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ROOT = Path(__file__).resolve().parents[1]
BUILT_IN_COMMANDS = {"doctor", "event", "list", "reconcile"}
HOST_COMMAND_TIMEOUT = 5


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


@dataclass(frozen=True)
class Reconciliation:
    plugins: dict[str, Plugin]
    warnings: tuple[str, ...]


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
    roots = [root / "plugins", root / "codex-plugins"]
    registrations = [path for base in roots if base.exists() for path in base.glob("*/gear.toml")]
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


def _host_json(command: Sequence[str], source: str) -> tuple[object | None, str | None]:
    if shutil.which(command[0]) is None:
        return None, None
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=HOST_COMMAND_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, f"{source}: could not query {' '.join(command)}: {exc}"
    if result.returncode != 0:
        detail = result.stderr.strip() or f"exit code {result.returncode}"
        return None, f"{source}: {' '.join(command)} failed: {detail}"
    try:
        return json.loads(result.stdout), None
    except json.JSONDecodeError as exc:
        return None, f"{source}: {' '.join(command)} returned invalid JSON: {exc}"


def _host_plugin_roots(root: Path) -> tuple[tuple[Path, ...], tuple[str, ...]]:
    roots: list[Path] = []
    warnings: list[str] = []

    claude_data, warning = _host_json(("claude", "plugin", "list", "--json"), "Claude")
    if warning:
        warnings.append(warning)
    if isinstance(claude_data, list):
        for record in claude_data:
            if not isinstance(record, dict) or not record.get("enabled"):
                continue
            project_path = record.get("projectPath")
            if project_path and Path(project_path).resolve() != root.resolve():
                continue
            install_path = record.get("installPath")
            if isinstance(install_path, str):
                roots.append(Path(install_path))

    codex_data, warning = _host_json(("codex", "plugin", "list", "--json"), "Codex")
    if warning:
        warnings.append(warning)
    if isinstance(codex_data, dict):
        for record in codex_data.get("installed", []):
            if not isinstance(record, dict) or not record.get("enabled") or not record.get("installed"):
                continue
            source = record.get("source")
            if isinstance(source, dict) and isinstance(source.get("path"), str):
                roots.append(Path(source["path"]))

    seen: set[Path] = set()
    unique: list[Path] = []
    for plugin_root in roots:
        resolved = plugin_root.expanduser().resolve()
        if resolved in seen or not resolved.is_dir():
            continue
        seen.add(resolved)
        unique.append(resolved)
    return tuple(unique), tuple(warnings)


def reconcile(root: Path) -> Reconciliation:
    plugins = discover(root)
    host_roots, warnings = _host_plugin_roots(root)
    installed_plugins: dict[str, Plugin] = {}
    for plugin_root in host_roots:
        registration = plugin_root / "gear.toml"
        if not registration.is_file():
            continue
        plugin = _load_plugin(registration.resolve(), repository_root=root)
        if plugin.name in plugins:
            continue
        if plugin.name in installed_plugins:
            other = installed_plugins[plugin.name].root / "gear.toml"
            raise GearError(f"plugin {plugin.name!r} is registered by both {other} and {registration}")
        installed_plugins[plugin.name] = plugin
    return Reconciliation({**plugins, **installed_plugins}, warnings)


def _executable(plugin: Plugin, command: Sequence[str]) -> tuple[str, ...]:
    executable = command[0]
    if executable.startswith(("./", "../")):
        resolved = (plugin.root / executable).resolve()
        try:
            resolved.relative_to(plugin.root.resolve())
        except ValueError as exc:
            raise GearError(f"{plugin.name}: executable escapes plugin root: {executable}") from exc
        if not resolved.is_file():
            raise GearError(f"{plugin.name}: executable does not exist: {resolved}")
        return (str(resolved), *command[1:])
    return tuple(command)


def _run(plugin: Plugin, command: Sequence[str], *, context: dict[str, str],
         caller_cwd: Path | None = None) -> int:
    env = os.environ.copy()
    env["GEAR_CALLER_CWD"] = str((caller_cwd or Path.cwd()).resolve())
    env.update({f"GEAR_{key.upper()}": value for key, value in context.items()})
    try:
        result = subprocess.run(
            _executable(plugin, command), cwd=plugin.root, env=env, check=False
        )
    except OSError as exc:
        raise GearError(f"{plugin.name}: could not execute {' '.join(command)}: {exc}") from exc
    return result.returncode


def _plugin_context(plugin: Plugin, **extra: str) -> dict[str, str]:
    return {
        "ROOT": str(plugin.repository_root),
        "PLUGIN_ROOT": str(plugin.root),
        "PLUGIN": plugin.name,
        **extra,
    }


def _refreshed_plugins(refresh: Callable[[], Reconciliation | dict[str, Plugin]]) -> dict[str, Plugin]:
    result = refresh()
    return result.plugins if isinstance(result, Reconciliation) else result


def route_command(
    plugins: dict[str, Plugin],
    plugin_name: str,
    command_name: str,
    args: Sequence[str],
    *,
    refresh: Callable[[], Reconciliation | dict[str, Plugin]] | None = None,
    caller_cwd: Path | None = None,
) -> int:
    plugin = plugins.get(plugin_name)
    command = plugin.commands.get(command_name) if plugin is not None else None
    if command is None and refresh is not None:
        return route_command(
            _refreshed_plugins(refresh),
            plugin_name,
            command_name,
            args,
            caller_cwd=caller_cwd,
        )
    if plugin is None:
        raise GearError(f"unknown plugin {plugin_name!r}; use `gear.py list` or `gear.py reconcile`")
    if command is None:
        available = ", ".join(sorted(plugin.commands)) or "none"
        raise GearError(f"unknown command {plugin_name} {command_name!r}; available: {available}")
    return _run(
        plugin,
        (*command, *args),
        context=_plugin_context(plugin, COMMAND=command_name),
        caller_cwd=caller_cwd,
    )


def route_event(
    plugins: dict[str, Plugin],
    event: str,
    *,
    refresh: Callable[[], Reconciliation | dict[str, Plugin]] | None = None,
    caller_cwd: Path | None = None,
) -> int:
    reminders = [
        (plugin, reminder)
        for plugin in plugins.values()
        for reminder in plugin.reminders
        if reminder.event == event
    ]
    if not reminders and refresh is not None:
        return route_event(_refreshed_plugins(refresh), event, caller_cwd=caller_cwd)
    seen: set[str] = set()
    for plugin, reminder in sorted(reminders, key=lambda item: (item[1].order, item[0].name, item[1].dedupe)):
        if reminder.dedupe in seen:
            continue
        seen.add(reminder.dedupe)
        code = _run(
            plugin,
            reminder.executable,
            context=_plugin_context(plugin, EVENT=event),
            caller_cwd=caller_cwd,
        )
        if code == 0:
            continue
        if reminder.severity == "gate":
            return code
        print(
            f"gear: reminder {plugin.name}:{event} failed with exit code {code}",
            file=sys.stderr,
        )
    return 0


def _print_list(plugins: dict[str, Plugin]) -> None:
    for plugin in sorted(plugins.values(), key=lambda item: item.name):
        for command in sorted(plugin.commands):
            print(f"{plugin.name} {command}")
        for reminder in sorted(plugin.reminders, key=lambda item: (item.event, item.order)):
            print(f"{plugin.name} @{reminder.event}")


def _print_warnings(warnings: Sequence[str]) -> None:
    for warning in warnings:
        print(f"gear: {warning}", file=sys.stderr)


def _reconcile_for_route(root: Path) -> Reconciliation:
    report = reconcile(root)
    _print_warnings(report.warnings)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gear.py", description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="bootgear repository root")
    parser.add_argument("route", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    try:
        root = args.root.resolve()
        caller_cwd = Path.cwd().resolve()
        plugins = discover(root)
        route = args.route
        if not route:
            parser.error("a plugin command or built-in command is required")
        if route[0] == "list":
            _print_list(plugins)
            return 0
        if route[0] == "doctor":
            print(f"root: {root}")
            print(f"plugins: {', '.join(sorted(plugins)) or 'none'}")
            return 0
        if route[0] == "reconcile":
            report = reconcile(root)
            _print_warnings(report.warnings)
            _print_list(report.plugins)
            return 1 if report.warnings else 0
        if route[0] == "event":
            if len(route) != 2:
                raise GearError("usage: gear.py event <event>")
            return route_event(plugins, route[1], refresh=lambda: _reconcile_for_route(root),
                               caller_cwd=caller_cwd)
        if route[0] in BUILT_IN_COMMANDS:
            raise GearError(f"built-in command {route[0]!r} has invalid arguments")
        if len(route) < 2:
            raise GearError("usage: gear.py <plugin> <command> [arguments...]")
        return route_command(plugins, route[0], route[1], route[2:],
                             refresh=lambda: _reconcile_for_route(root),
                             caller_cwd=caller_cwd)
    except GearError as exc:
        print(f"gear: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
