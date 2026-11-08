#!/usr/bin/env python3
"""Route bootgear commands and lifecycle events to registered plugins."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import threading
import tomllib
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

CLI_ROOT = Path(__file__).resolve().parents[2]


def _checkout_root() -> Path:
    for ancestor in CLI_ROOT.parents:
        if (ancestor / "plugins" / "cli").resolve() == CLI_ROOT and (ancestor / "codex-plugins").is_dir():
            return ancestor
    return CLI_ROOT


DEFAULT_ROOT = _checkout_root()
BUILT_IN_COMMANDS = {"doctor", "event", "list", "reconcile"}
HOST_COMMAND_TIMEOUT = 5


class GearError(Exception):
    """A registration or routing error suitable for a CLI diagnostic."""


class GearParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        example = shlex.join([str(CLI_ROOT / "bin" / "gear"), "--help"])
        self.exit(2, f"gear: {message}\nexample: {example}\ncommands: list, doctor, reconcile, event, <plugin> <command>\n")


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
    if os.environ.get("BOOTGEAR_HOST") != "codex":
        roots.reverse()
    selected: dict[str, Path] = {}
    for base in roots:
        if base.exists():
            selected.update({path.parent.name: path for path in base.glob("*/gear.toml")})
    registrations = list(selected.values())
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
            stdin=subprocess.DEVNULL,
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

    host = os.environ.get("BOOTGEAR_HOST")
    claude_data, warning = (None, None) if host == "codex" else _host_json(("claude", "plugin", "list", "--json"), "Claude")
    if warning:
        warnings.append(warning)
    if isinstance(claude_data, list):
        caller = Path(os.environ.get("GEAR_CALLER_CWD") or Path.cwd()).resolve()
        for record in claude_data:
            if not isinstance(record, dict) or not record.get("enabled"):
                continue
            project_path = record.get("projectPath")
            if project_path:
                project = Path(project_path).resolve()
                if project != root.resolve() and not caller.is_relative_to(project):
                    continue
            install_path = record.get("installPath")
            if isinstance(install_path, str):
                roots.append(Path(install_path))

    codex_data, warning = (None, None) if host == "claude" else _host_json(("codex", "plugin", "list", "--json"), "Codex")
    if warning:
        warnings.append(warning)
    if isinstance(codex_data, dict):
        for record in codex_data.get("installed", []):
            if not isinstance(record, dict) or not record.get("enabled") or not record.get("installed", True):
                continue
            fields = [record.get(key) for key in ("marketplaceName", "name", "version")]
            if not all(isinstance(value, str) and value and value not in {".", ".."}
                       and "/" not in value and "\\" not in value for value in fields):
                warnings.append("Codex: installed plugin has incomplete cache identity; run cli:setup.")
                continue
            codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
            installed = codex_home.joinpath("plugins", "cache", *(str(value) for value in fields))
            if installed.is_dir():
                roots.append(installed)
            else:
                warnings.append(f"Codex: installed plugin {fields[1]} is missing; run its setup skill.")

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


def _invoke(command: Sequence[str], *, cwd: Path, env: dict[str, str]) -> int:
    """Forward termination signals and wait for the provider's final status."""
    with subprocess.Popen(command, cwd=cwd, env=env) as child:
        previous = {}

        def forward(signum: int, _frame: object) -> None:
            child.send_signal(signum)

        if threading.current_thread() is threading.main_thread():
            for signum in (signal.SIGINT, signal.SIGTERM):
                previous[signum] = signal.signal(signum, forward)
        try:
            return child.wait()
        finally:
            for signum, handler in previous.items():
                signal.signal(signum, handler)


def _run(plugin: Plugin, command: Sequence[str], *, context: dict[str, str],
         caller_cwd: Path | None = None) -> int:
    from bootgear_cli import clikit, runtime

    env = os.environ.copy()
    env["GEAR_CALLER_CWD"] = str(caller_cwd or Path(env.get("GEAR_CALLER_CWD") or Path.cwd()).resolve())
    env.update({f"GEAR_{key.upper()}": value for key, value in context.items()})
    env["CLAUDE_PLUGIN_ROOT"] = str(plugin.root)
    env["PLUGIN_ROOT"] = str(plugin.root)
    if "COMMAND" in context:
        env["BOOTGEAR_PROG"] = clikit.gear_command(plugin.name, context["COMMAND"], root=plugin.repository_root)
    paths = [CLI_ROOT / "src", plugin.root / "src", plugin.root / "scripts"]
    env["PYTHONPATH"] = os.pathsep.join([*(str(path) for path in paths if path.is_dir()),
                                        *([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])])
    executable = _executable(plugin, command)
    try:
        if Path(executable[0]).name in {"python", "python3", "python3.12"}:
            if plugin.name == "cli" and context.get("COMMAND") == "setup":
                result = _invoke((sys.executable, *executable[1:]), cwd=plugin.root, env=env)
            else:
                with runtime.prepared() as interpreter:
                    env["VIRTUAL_ENV"] = str(interpreter.parent.parent)
                    env["PATH"] = str(interpreter.parent) + os.pathsep + env.get("PATH", "")
                    result = _invoke((str(interpreter), *executable[1:]), cwd=plugin.root, env=env)
        else:
            result = _invoke(executable, cwd=plugin.root, env=env)
    except runtime.RuntimeNotReady as exc:
        raise GearError(str(exc)) from exc
    except OSError as exc:
        raise GearError(f"{plugin.name}: could not execute {' '.join(command)}: {exc}") from exc
    return result


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
        raise GearError(f"unknown plugin {plugin_name!r}; use Gear list or reconcile")
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


def _print_list(plugins: dict[str, Plugin], mode: str = "prose") -> None:
    if mode == "json":
        print(json.dumps({"plugins": {plugin.name: {
            "commands": sorted(plugin.commands), "events": sorted(reminder.event for reminder in plugin.reminders),
        } for plugin in sorted(plugins.values(), key=lambda item: item.name)}}))
        return
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
    os.environ.pop("BOOTGEAR_PROG", None)
    parser = GearParser(prog="gear", description=__doc__)
    parser.add_argument("--host", choices=("claude", "codex"), default=os.environ.get("BOOTGEAR_HOST"))
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="bootgear repository root")
    output_flags = parser.add_mutually_exclusive_group()
    output_flags.add_argument("--json", action="store_true")
    output_flags.add_argument("--prose", action="store_true")
    parser.add_argument("route", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.host:
        os.environ["BOOTGEAR_HOST"] = args.host
    plugins: dict[str, Plugin] = {}
    route = args.route
    root = args.root
    try:
        root = args.root.resolve()
        caller_cwd = Path(os.environ.get("GEAR_CALLER_CWD") or Path.cwd()).resolve()
        plugins = _reconcile_for_route(root).plugins if root == CLI_ROOT else discover(root)
        if "cli" not in plugins and (CLI_ROOT / "gear.toml").is_file():
            plugins["cli"] = _load_plugin(CLI_ROOT / "gear.toml", repository_root=root)
        route = args.route
        if not route:
            parser.error("a plugin command or built-in command is required")
        mode = os.environ.get("BOOTGEAR_OUTPUT", "prose")
        if route[0] in BUILT_IN_COMMANDS:
            json_flag = args.json or "--json" in route[1:]
            prose_flag = args.prose or "--prose" in route[1:]
            if json_flag and prose_flag:
                raise GearError("--json and --prose are mutually exclusive")
            mode = "json" if json_flag else "prose" if prose_flag else mode
            route = [value for value in route if value not in {"--json", "--prose"}]
        elif args.json or args.prose:
            os.environ["BOOTGEAR_OUTPUT"] = "json" if args.json else "prose"
        if route[0] == "list":
            _print_list(plugins, mode)
            return 0
        if route[0] == "doctor":
            if mode == "json":
                print(json.dumps({"root": str(root), "plugins": sorted(plugins)}))
            else:
                print(f"root: {root}")
                print(f"plugins: {', '.join(sorted(plugins)) or 'none'}")
            return 0
        if route[0] == "reconcile":
            report = reconcile(root)
            _print_warnings(report.warnings)
            _print_list(report.plugins, mode)
            return 1 if report.warnings else 0
        if route[0] == "event":
            if len(route) != 2:
                raise GearError("usage: gear event <event>")
            return route_event(plugins, route[1], refresh=lambda: _reconcile_for_route(root),
                               caller_cwd=caller_cwd)
        if route[0] in BUILT_IN_COMMANDS:
            raise GearError(f"built-in command {route[0]!r} has invalid arguments")
        if len(route) < 2:
            raise GearError("usage: gear <plugin> <command> [arguments...]")
        return route_command(plugins, route[0], route[1], route[2:],
                             refresh=lambda: _reconcile_for_route(root),
                             caller_cwd=caller_cwd)
    except GearError as exc:
        print(f"gear: {exc}", file=sys.stderr)
        from bootgear_cli.clikit import gear_command

        provider = plugins.get(route[0]) if route else None
        if provider is not None and provider.commands:
            command = next(iter(provider.commands))
            example = f"{gear_command(provider.name, command, root=root)} --help"
        else:
            example = shlex.join([str(CLI_ROOT / "bin" / "gear"), "--help"])
        print(f"example: {example}", file=sys.stderr)
        print("commands: list, doctor, reconcile, event, <plugin> <command>", file=sys.stderr)
        return 2


def resolve_command(command: str) -> list[str] | None:
    """Return a registered Gear prefix, preferring the current provider."""
    from bootgear_cli.clikit import gear_argv

    root = Path(os.environ.get("GEAR_ROOT") or DEFAULT_ROOT).resolve()
    plugins = discover(root)
    current = os.environ.get("GEAR_PLUGIN")
    if current in plugins and command in plugins[current].commands:
        return gear_argv(current, command)
    if command in plugins and command in plugins[command].commands:
        return gear_argv(command, command)
    matches = [plugin.name for plugin in plugins.values() if command in plugin.commands]
    if not matches:
        plugins = reconcile(root).plugins
        if current in plugins and command in plugins[current].commands:
            return gear_argv(current, command)
        if command in plugins and command in plugins[command].commands:
            return gear_argv(command, command)
        matches = [plugin.name for plugin in plugins.values() if command in plugin.commands]
    if len(matches) == 1:
        return gear_argv(matches[0], command)
    return None


def entrypoint() -> NoReturn:
    code = main()
    if code < 0:
        signum = -code
        if signum not in {signal.SIGKILL, signal.SIGSTOP}:
            signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)
    raise SystemExit(code)


if __name__ == "__main__":
    entrypoint()
