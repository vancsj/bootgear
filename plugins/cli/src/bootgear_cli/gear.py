#!/usr/bin/env python3
"""Route bootgear commands and lifecycle events to registered plugins."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import signal
import subprocess
import sys
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from bootgear_cli import hook_loader
from bootgear_cli.registrations import GearError, Plugin, _load_plugin, discover

CLI_ROOT = Path(__file__).resolve().parents[2]


def _checkout_root() -> Path:
    for ancestor in CLI_ROOT.parents:
        if (ancestor / "plugins" / "cli").resolve() == CLI_ROOT:
            return ancestor
    return CLI_ROOT


DEFAULT_ROOT = _checkout_root()
BUILT_IN_COMMANDS = {"doctor", "event", "list", "reconcile"}


class GearParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        example = shlex.join([str(CLI_ROOT / "bin" / "gear"), "--help"])
        self.exit(2, f"example: {example}\ncommands: list, doctor, reconcile, event, <plugin> <command>\ngear: {message}\n")


@dataclass(frozen=True)
class Reconciliation:
    plugins: dict[str, Plugin]
    warnings: tuple[str, ...]
    stored: bool = False  # a host list came from the session store, not a query


def _session_key() -> str | None:
    """The store key of the current session: the environment session id when it is safe."""
    from bootgear_cli import clikit

    return hook_loader.safe_session(clikit.session_id())


def _host_inventory(host: str, source: str, session: str | None, *,
                    refresh: bool) -> tuple[object | None, bool, str | None]:
    try:
        inventory, stored = hook_loader.host_inventory(host, session, refresh=refresh)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, False, f"{source}: could not read {host} plugin inventory: {exc}"
    except (RuntimeError, TypeError, ValueError) as exc:
        return None, False, f"{source}: {exc}"
    return inventory, stored, None


def _host_plugin_roots(root: Path, *,
                       refresh: bool = False, strict: bool = False,
                       host: str | None = None) -> tuple[tuple[Path, ...], tuple[str, ...], bool]:
    """Enabled host plugin roots, the warnings, and whether a host list came from the store.

    The session store is used unless `refresh` asks for a query. A stored record whose
    folder is gone is skipped silently; warnings come from fresh queries.
    Strict setup calls reject query failures and invalid inventory structures."""
    roots: list[Path] = []
    warnings: list[str] = []

    host = host or os.environ.get("BOOTGEAR_HOST")
    session = _session_key()
    claude_data, claude_stored, warning = ((None, False, None) if host == "codex"
                                           else _host_inventory("claude", "Claude", session, refresh=refresh))
    if warning:
        if strict:
            raise GearError(warning)
        warnings.append(warning)
    if strict and host == "claude" and not isinstance(claude_data, list):
        raise GearError("claude plugin list --json returned an invalid installed plugin list.")
    if isinstance(claude_data, list):
        caller = Path(os.environ.get("GEAR_CALLER_CWD") or Path.cwd()).resolve()
        activation = hook_loader.inventory_activation("claude", session, caller)
        seen_ids: set[str] = set()
        for record in claude_data:
            if not isinstance(record, dict) or not record.get("enabled"):
                continue
            if not hook_loader.applies_to(record, activation):
                continue
            identity = record.get("id")
            if isinstance(identity, str):
                if identity in seen_ids:
                    continue
                seen_ids.add(identity)
            install_path = record.get("installPath")
            if isinstance(install_path, str) and Path(install_path).is_dir():
                roots.append(Path(install_path))
            else:
                warnings.append(f"Claude: installed plugin {identity or 'unknown'} is missing; run cli:setup.")

    codex_data, codex_stored, warning = ((None, False, None) if host == "claude"
                                         else _host_inventory("codex", "Codex", session, refresh=refresh))
    if warning:
        if strict:
            raise GearError(warning)
        warnings.append(warning)
    if strict and host == "codex" and (not isinstance(codex_data, dict)
                                      or not isinstance(codex_data.get("installed"), list)):
        raise GearError("codex plugin list returned an invalid installed plugin list.")
    if isinstance(codex_data, dict):
        for record in codex_data.get("installed", []):
            if not isinstance(record, dict) or not record.get("enabled") or not record.get("installed", True):
                continue
            installed = hook_loader.codex_cache_root(record)
            if installed is None:
                warnings.append("Codex: installed plugin has incomplete cache identity; run cli:setup.")
                continue
            if installed.is_dir():
                roots.append(installed)
            else:
                warnings.append(f"Codex: installed plugin {record['name']} is missing; run cli:setup.")

    seen: set[Path] = set()
    unique: list[Path] = []
    for plugin_root in roots:
        resolved = plugin_root.expanduser().resolve()
        if resolved in seen or not resolved.is_dir():
            continue
        seen.add(resolved)
        unique.append(resolved)
    return tuple(unique), tuple(warnings), claude_stored or codex_stored


def reconcile(root: Path, *, refresh: bool = False) -> Reconciliation:
    plugins = discover(root)
    host_roots, warnings, stored = _host_plugin_roots(root, refresh=refresh)
    installed_plugins: dict[str, Plugin] = {}
    for plugin_root in host_roots:
        registration = plugin_root / "gear.toml"
        if not registration.is_file():
            continue
        try:
            plugin = _load_plugin(registration.resolve(), repository_root=root)
        except GearError as exc:
            warnings += (f"{exc}. Run cli:setup to repair that plugin.",)
            continue
        if plugin.name in plugins:
            continue
        if plugin.name in installed_plugins:
            other = installed_plugins[plugin.name].root / "gear.toml"
            raise GearError(f"plugin {plugin.name!r} is registered by both {other} and {registration}")
        installed_plugins[plugin.name] = plugin
    return Reconciliation({**plugins, **installed_plugins}, warnings, stored)


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
                env["PYTHONPATH"] = str(CLI_ROOT / "src")
                result = _invoke((sys.executable, "-P", *executable[1:]),
                                 cwd=Path(env["GEAR_CALLER_CWD"]), env=env)
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


def route_command(
    plugins: dict[str, Plugin],
    plugin_name: str,
    command_name: str,
    args: Sequence[str],
    *,
    caller_cwd: Path | None = None,
) -> int:
    plugin = plugins.get(plugin_name)
    command = plugin.commands.get(command_name) if plugin is not None else None
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
    caller_cwd: Path | None = None,
) -> int:
    reminders = [
        (plugin, reminder)
        for plugin in plugins.values()
        for reminder in plugin.reminders
        if reminder.event == event
    ]
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


def _reconcile_for_route(root: Path, *, refresh: bool = False) -> Reconciliation:
    report = reconcile(root, refresh=refresh)
    _print_warnings(report.warnings)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    os.environ.pop("BOOTGEAR_PROG", None)
    parser = GearParser(prog="gear", description=__doc__,
                        epilog="commands: list, doctor, reconcile, event, <plugin> <command>; example: gear list")
    parser.add_argument("--host", choices=("claude", "codex"),
                        help="the calling host; default: $BOOTGEAR_HOST, else the host of the session environment")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="bootgear repository root")
    output_flags = parser.add_mutually_exclusive_group()
    output_flags.add_argument("--json", action="store_true")
    output_flags.add_argument("--prose", action="store_true")
    parser.add_argument("route", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    from bootgear_cli import clikit

    if host := clikit.host(args.host):
        os.environ["BOOTGEAR_HOST"] = host
    plugins: dict[str, Plugin] = {}
    route = args.route
    root = args.root
    try:
        if route and route[0] in BUILT_IN_COMMANDS and any(value in {"-h", "--help"} for value in route[1:]):
            prefix = [str(CLI_ROOT / "bin" / "gear")]
            if chosen_host := clikit.host(args.host):
                prefix.extend(["--host", chosen_host])
            command = route[0]
            suffix = " <event>" if command == "event" else " [--json|--prose]"
            meanings = {
                "list": "List registered provider commands.",
                "doctor": "Show the selected root and available providers.",
                "reconcile": "Refresh the installed host plugin inventory and report provider commands.",
                "event": "Read host event JSON from stdin and run the registered event handlers.",
            }
            call = shlex.join([*prefix, command])
            example = (f"printf '%s\\n' '{{\"session_id\":\"00000000-0000-4000-8000-000000000001\",\"hook_event_name\":\"SessionStart\",\"cwd\":\".\",\"source\":\"startup\"}}' | {call} SessionStart"
                       if command == "event" else call)
            print(f"usage: {call}{suffix}\n\n{meanings[command]}\nexample: {example}")
            return 0
        root = args.root.resolve()
        caller_cwd = Path(os.environ.get("GEAR_CALLER_CWD") or Path.cwd()).resolve()
        # An installed Gear needs host plugins, except for a `cli` route, which loads from CLI_ROOT.
        installed = root == CLI_ROOT and route[:1] != ["cli"]
        explicit_refresh = route[:1] == ["reconcile"]
        plugins = discover(root)
        use_inventory = installed or (root != DEFAULT_ROOT and route and route[0] not in plugins
                                       and route[0] not in BUILT_IN_COMMANDS and route[0] != "cli")
        if use_inventory and not explicit_refresh:
            plugins = _reconcile_for_route(root).plugins
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
            if route[0] != "event" and len(route) != 1:
                raise GearError(f"{route[0]} accepts only --json or --prose; use --root before the command")
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
            if os.environ.get("BOOTGEAR_HOOK_ACTIVE") == "1":
                raise GearError("Run reconcile outside the hook, then retry.")
            report = reconcile(root, refresh=True)
            _print_warnings(report.warnings)
            _print_list(report.plugins, mode)
            return 1 if report.warnings else 0
        if route[0] == "event":
            if len(route) != 2:
                raise GearError("usage: gear event <event>")
            return route_event(plugins, route[1], caller_cwd=caller_cwd)
        if route[0] in BUILT_IN_COMMANDS:
            raise GearError(f"built-in command {route[0]!r} has invalid arguments")
        if len(route) < 2:
            raise GearError("usage: gear <plugin> <command> [arguments...]")
        return route_command(plugins, route[0], route[1], route[2:], caller_cwd=caller_cwd)
    except GearError as exc:
        from bootgear_cli.clikit import gear_command

        provider = plugins.get(route[0]) if route else None
        if provider is not None and provider.commands:
            command = next(iter(provider.commands))
            example = f"{gear_command(provider.name, command, root=root)} --help"
        else:
            example = shlex.join([str(CLI_ROOT / "bin" / "gear"), "--help"])
        print(f"example: {example}", file=sys.stderr)
        print("commands: list, doctor, reconcile, event, <plugin> <command>", file=sys.stderr)
        print(f"gear: {exc}", file=sys.stderr)
        return 2


def resolve_command(command: str) -> list[str] | None:
    """Return a registered Gear prefix, preferring the current provider."""
    from bootgear_cli.clikit import gear_argv

    root = Path(os.environ.get("GEAR_ROOT") or DEFAULT_ROOT).resolve()
    current = os.environ.get("GEAR_PLUGIN")

    def owners(plugins: dict[str, Plugin]) -> list[str]:
        if current is not None and current in plugins and command in plugins[current].commands:
            return [current]
        if command in plugins and command in plugins[command].commands:
            return [command]
        return [plugin.name for plugin in plugins.values() if command in plugin.commands]

    matches = owners(discover(root))
    if not matches:
        report = reconcile(root)
        matches = owners(report.plugins)
    return gear_argv(matches[0], command) if len(matches) == 1 else None


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
