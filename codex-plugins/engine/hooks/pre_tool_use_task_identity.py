"""Add Codex's session identity to a registered Gear executable call."""
from __future__ import annotations

import ast
import json
import os
import re
import shlex
import sys
import tomllib
from pathlib import Path

_SESSION_ID_RE = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,254}\Z")
_SHELL_PUNCTUATION = frozenset(";&|<>()!")


def _plugin_root() -> Path | None:
    root = os.environ.get("PLUGIN_ROOT")
    path = Path(root).expanduser() if root else Path(__file__).resolve().parent.parent
    try:
        return path.resolve(strict=True)
    except OSError:
        return None


def _task_commands(plugin_root: Path) -> set[tuple[str, str]] | None:
    """Read the literal command catalog without importing or running engine code."""
    source_path = plugin_root / "src" / "engine" / "cli.py"
    try:
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
    except (OSError, UnicodeError, SyntaxError):
        return None

    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == "EXAMPLES"
                   for target in node.targets):
            continue
        try:
            examples = ast.literal_eval(node.value)
        except (ValueError, TypeError):
            return None
        if not isinstance(examples, dict) or not examples:
            return None
        commands: set[tuple[str, str]] = set()
        for key in examples:
            if not isinstance(key, str):
                return None
            parts = key.split()
            if len(parts) != 2:
                return None
            commands.add((parts[0], parts[1]))
        return commands
    return None


def _tokens(command: object) -> list[str] | None:
    if not isinstance(command, str) or not command:
        return None
    if any((ord(char) < 0x20 and char != "\t") or ord(char) == 0x7F
           for char in command):
        return None
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>()")
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        return None
    if not tokens:
        return None
    if any(token and all(char in _SHELL_PUNCTUATION for char in token)
           for token in tokens):
        return None
    if any(any(char in token for char in "$`#") for token in tokens):
        return None
    return tokens


def _is_executable(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def _resolve_executable(token: str, hook_input: dict) -> Path | None:
    cwd_value = hook_input.get("cwd")
    if cwd_value is not None and not isinstance(cwd_value, str):
        return None
    base = Path(cwd_value).expanduser() if cwd_value else Path.cwd()
    candidate = Path(token).expanduser()
    if candidate.is_absolute() or "/" in token:
        if not candidate.is_absolute():
            candidate = base / candidate
    else:
        candidate = None
        for entry in os.environ.get("PATH", "").split(os.pathsep):
            directory = Path(entry or ".")
            if not directory.is_absolute():
                directory = base / directory
            possible = directory / token
            if _is_executable(possible):
                candidate = possible
                break
        if candidate is None:
            return None
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return None
    if candidate.is_symlink():
        try:
            invocation_directory = candidate.parent.resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            return None
        if invocation_directory != resolved.parent:
            return None
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        return None
    return resolved


def _registered_executable(executable: Path) -> bool:
    """Match a resolved executable to a command in its gear.toml."""
    for plugin_root in (executable.parent, *executable.parent.parents):
        registration = plugin_root / "gear.toml"
        if not registration.is_file():
            continue
        try:
            document = tomllib.loads(registration.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, tomllib.TOMLDecodeError):
            return False
        plugin = document.get("plugin")
        if not isinstance(plugin, dict):
            return False
        name = plugin.get("name")
        if (not isinstance(name, str) or not name or "/" in name or "\\" in name):
            return False
        commands = document.get("commands", {})
        if not isinstance(commands, dict) or not commands:
            return False
        try:
            plugin_path = plugin_root.resolve(strict=True)
        except (OSError, RuntimeError, ValueError):
            return False
        for command_name, definition in commands.items():
            if (not isinstance(command_name, str) or not command_name
                    or "/" in command_name or not isinstance(definition, dict)):
                return False
            argv = definition.get("exec")
            if (not isinstance(argv, list) or not argv
                    or not all(isinstance(item, str) for item in argv)):
                return False
            target = argv[0]
            target_path = Path(target)
            if target_path.is_absolute():
                expected_path = target_path
            elif "/" in target:
                expected_path = plugin_root / target
            else:
                continue
            try:
                expected = expected_path.resolve(strict=True)
                if not target_path.is_absolute():
                    expected.relative_to(plugin_path)
            except (OSError, RuntimeError, ValueError):
                continue
            if expected == executable:
                return True
        return False
    return False


def _codex_task_executable(executable: Path, plugin_root: Path) -> bool:
    expected = plugin_root / "scripts" / "task"
    try:
        return (expected.is_file() and os.access(expected, os.X_OK)
                and not expected.is_symlink()
                and expected.resolve(strict=True) == executable)
    except (OSError, RuntimeError, ValueError):
        return False


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _updated_command(hook_input: object) -> str | None:
    if not isinstance(hook_input, dict):
        return None
    if hook_input.get("hook_event_name") != "PreToolUse":
        return None
    if hook_input.get("tool_name") != "Bash":
        return None

    session_id = hook_input.get("session_id")
    if not isinstance(session_id, str) or not _SESSION_ID_RE.fullmatch(session_id):
        return None
    tool_input = hook_input.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    command = tool_input.get("command")
    tokens = _tokens(command)
    if tokens is None:
        return None

    executable = _resolve_executable(tokens[0], hook_input)
    if executable is None:
        return None

    plugin_root = _plugin_root()
    if plugin_root is not None and _codex_task_executable(executable, plugin_root):
        known_commands = _task_commands(plugin_root)
        if (len(tokens) < 3 or known_commands is None
                or (tokens[1], tokens[2]) not in known_commands):
            return None
    elif not _registered_executable(executable):
        return None

    return f"export BOOTGEAR_SESSION_ID={_shell_quote(session_id)} && {command}"


def main() -> None:
    try:
        hook_input = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return
    updated = _updated_command(hook_input)
    if updated is None:
        return
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "updatedInput": {"command": updated},
        }
    }))


if __name__ == "__main__":
    main()
