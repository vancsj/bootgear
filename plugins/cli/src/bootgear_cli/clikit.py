"""Shared CLI output: prose or JSON by reader, runnable refusals, caller paths.

Providers import this package through Gear's prepared Python path.

    mode       --json/--prose > $BOOTGEAR_OUTPUT > prose
    refusals   stderr; prose lines or one JSON error object, with the failing
               command's example, its sibling commands and the frequent ones
    paths      relative path arguments resolve against $GEAR_CALLER_CWD
    session    explicit value > $BOOTGEAR_SESSION_ID > the session variable of `host()` > the other one
    host       explicit value > $BOOTGEAR_HOST > the host whose session variable is set; with
               both set, the nearest claude or codex ancestor process, else claude
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import shlex
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar, NoReturn, TextIO, TypeVar, overload

from bootgear_cli import host_context

host = host_context.host
missing_session = host_context.missing_session
session_id = host_context.session_id

ENV_MODE = "BOOTGEAR_OUTPUT"
ENV_PROG = "BOOTGEAR_PROG"
ENV_CALLER_CWD = "GEAR_CALLER_CWD"
MODES = frozenset({"prose", "json"})
NEXT_PREFIX = "next: "
_NamespaceT = TypeVar("_NamespaceT")


def gear_argv(plugin: str, command: str, *, root: str | Path | None = None,
              host: str | None = None) -> list[str]:
    """Return the current Gear executable and registered command prefix."""
    cli_root = Path(__file__).resolve().parents[2]
    argv = [str(cli_root / "bin" / "gear")]
    host = host or os.environ.get("BOOTGEAR_HOST")
    if host in {"claude", "codex"}:
        argv.extend(["--host", host])
    selected_root = root or os.environ.get("GEAR_ROOT")
    if selected_root:
        from bootgear_cli.gear import DEFAULT_ROOT

        selected_root = Path(selected_root).resolve()
        if selected_root != DEFAULT_ROOT:
            argv.extend(["--root", str(selected_root)])
    return [*argv, plugin, command]


def gear_command(plugin: str, command: str, *, root: str | Path | None = None,
                 host: str | None = None) -> str:
    return shlex.join(gear_argv(plugin, command, root=root, host=host))


def current_program(plugin: str, command: str) -> str:
    return os.environ.get(ENV_PROG) or gear_command(plugin, command)


def argv_template(template: str, markers: tuple[str, ...]) -> list[str]:
    """Parse a command with each marker in exactly one whole argument."""
    argv = shlex.split(template)
    if not argv or not argv[0] or argv[0].startswith("-") or argv[0] in markers:
        raise ValueError("the template must start with an executable")
    invalid = [marker for marker in markers if argv.count(marker) != 1
               or sum(arg.count(marker) for arg in argv) != 1]
    if invalid:
        raise ValueError(f"expected each as one whole argument: {', '.join(invalid)}")
    return argv


# ---------------------------------------------------------------------------
# mode


def _default_mode(_stream: TextIO | None) -> str:
    env = os.environ.get(ENV_MODE)
    if env in MODES:
        return env
    return "prose"


def resolve_mode(json_flag: bool, prose_flag: bool, stream: TextIO | None = None) -> str:
    """Output mode for a parsed command; `stream` defaults to the current stdout.

    Raises a usage `Refusal` (exit 2) when both flags are given."""
    if json_flag and prose_flag:
        raise Refusal("--json and --prose are mutually exclusive", code=2)
    if json_flag:
        return "json"
    if prose_flag:
        return "prose"
    return _default_mode(stream)


def argv_mode(argv: list[str]) -> str:
    """`resolve_mode` over raw argv, for errors raised before flags are parsed.

    Both flags present count as neither."""
    json_flag, prose_flag = "--json" in argv, "--prose" in argv
    if json_flag != prose_flag:
        return "json" if json_flag else "prose"
    return _default_mode(None)


# ---------------------------------------------------------------------------
# paths


def caller_cwd() -> Path:
    """The invoking caller's working directory: $GEAR_CALLER_CWD, else cwd."""
    return Path(os.environ.get(ENV_CALLER_CWD) or os.getcwd())


def caller_path(value: str | Path) -> Path:
    """argparse `type=` for path arguments: `~` expands; a relative path joins
    `caller_cwd()`; an absolute path is unchanged."""
    path = Path(value).expanduser()
    if path.is_absolute():
        return path
    return caller_cwd() / path


# ---------------------------------------------------------------------------
# catalog and parser wiring


@dataclass(frozen=True)
class Catalog:
    """Per-CLI registry that refusals and `run` read.

    `examples` maps each leaf command (space-joined path) to its argv after the
    program. `legacy_json` commands own a pure format `--json`; `own_json`
    commands own a `--json` that changes content or exit
    code and never counts as the mode flag; `capture` commands have their
    prose captured into `{"lines"}` in JSON mode."""

    prog: str
    examples: dict[str, str]
    frequent: tuple[str, ...] = ()
    legacy_json: frozenset[str] = frozenset()
    own_json: frozenset[str] = frozenset()
    capture: frozenset[str] = frozenset()
    invalid_command_hints: dict[str, str] = field(default_factory=dict)

    def display_prog(self) -> str:
        return os.environ.get(ENV_PROG) or self.prog

    def command(self, rest: str) -> str:
        return f"{self.display_prog()} {rest}"


class _CatalogParser(argparse.ArgumentParser):
    catalog: ClassVar[Catalog]
    # argv `run` is parsing, so a parse error's mode follows run(argv=...)
    argv: ClassVar[list[str] | None] = None
    _input_problems: list[str]

    def _check_value(self, action: argparse.Action, value: Any) -> None:
        try:
            super()._check_value(action, value)
        except argparse.ArgumentError as exc:
            if isinstance(action, argparse._SubParsersAction):
                if hint := self.catalog.invalid_command_hints.get(value):
                    raise argparse.ArgumentError(action, f"{exc.message}; {hint}") from exc
                raise
            self._input_problems.append(str(exc))

    @overload
    def parse_known_args(self, args: Iterable[str] | None = None, namespace: None = None) -> tuple[argparse.Namespace, list[str]]: ...

    @overload
    def parse_known_args(self, args: Iterable[str] | None, namespace: _NamespaceT) -> tuple[_NamespaceT, list[str]]: ...

    @overload
    def parse_known_args(self, *, namespace: _NamespaceT) -> tuple[_NamespaceT, list[str]]: ...

    def parse_known_args(self, args: Iterable[str] | None = None, namespace: Any = None) -> Any:
        self._input_problems = []
        result = super().parse_known_args(args, namespace)
        if self._input_problems:
            message = self._input_problems[0] if len(self._input_problems) == 1 else "invalid argument values"
            self.error(message)
        return result

    def format_help(self) -> str:
        text = super().format_help()
        example = command_example(self.catalog, _command_of_prog(self.catalog, self.prog))
        return text + (f"\nexample: {example}\n" if example else "")

    def error(self, message: str) -> NoReturn:
        argv = type(self).argv
        mode = argv_mode(sys.argv[1:] if argv is None else argv)
        problems = getattr(self, "_input_problems", [])
        refusal = Refusal(f"{self.prog}: error: {message}",
                          (("invalid argument", item) for item in problems) if len(problems) > 1 else (), code=2)
        render_refusal(self.catalog, _command_of_prog(self.catalog, self.prog), refusal, mode)
        sys.exit(2)


def parser_class(catalog: Catalog) -> type[argparse.ArgumentParser]:
    """ArgumentParser subclass whose parse errors render a usage refusal and
    exit 2. Subparsers inherit it from the root parser."""
    return type("CatalogParser", (_CatalogParser,), {"catalog": catalog})


def command_example(catalog: Catalog, command: str | None) -> str | None:
    """Return the command's example, or one leaf example under its group."""
    key = command if command in catalog.examples else next(
        (leaf for leaf in catalog.examples if not command or leaf.startswith(command + " ")),
        None,
    )
    return catalog.command(catalog.examples[key]) if key is not None else None


def add_help_examples(parser: argparse.ArgumentParser, catalog: Catalog) -> None:
    """Add Catalog examples to a provider's custom parser and its subparsers."""
    def visit(node: argparse.ArgumentParser, path: str) -> None:
        if node.formatter_class is argparse.HelpFormatter:
            node.formatter_class = argparse.RawDescriptionHelpFormatter
        example = command_example(catalog, path or None)
        if example:
            node.epilog = "\n".join(filter(None, [node.epilog, f"example: {example}"]))
        for action in _subparsers(node):
            for name, child in action.choices.items():
                visit(child, " ".join(filter(None, [path, name])))

    visit(parser, "")


def event_help(plugin: str, command: str, inputs: str, payload: dict[str, Any],
               arguments: str = "") -> bool:
    """Print event input help before the handler reads stdin; return whether help was requested."""
    if not any(value in {"-h", "--help"} for value in sys.argv[1:]):
        return False
    program = current_program(plugin, command)
    call = " ".join(filter(None, [program, arguments]))
    print(f"usage: {call} < event.json\n\nEvent input: {inputs}\n"
          f"example: printf '%s\\n' {shlex.quote(json.dumps(payload))} | {call}")
    return True


def _command_of_prog(catalog: Catalog, prog: str) -> str | None:
    if prog == catalog.prog:
        return None
    if prog.startswith(f"{catalog.prog} "):
        return prog[len(catalog.prog) + 1:] or None
    _, _, rest = prog.partition(" ")
    return rest or None


def _subparsers(parser: argparse.ArgumentParser) -> list[argparse._SubParsersAction]:
    return [a for a in parser._actions if isinstance(a, argparse._SubParsersAction)]


def leaf_commands(parser: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    """Every leaf subparser keyed by its space-joined command path; an alias
    maps to the same parser as its first name and is skipped."""
    leaves: dict[str, argparse.ArgumentParser] = {}
    seen: set[int] = set()

    def walk(node: argparse.ArgumentParser, path: tuple[str, ...]) -> None:
        actions = _subparsers(node)
        if not actions:
            if path:
                leaves[" ".join(path)] = node
            return
        for action in actions:
            for name, child in action.choices.items():
                if id(child) in seen:
                    continue
                seen.add(id(child))
                walk(child, (*path, name))

    walk(parser, ())
    return leaves


def add_mode_flags(parser: argparse.ArgumentParser) -> None:
    """Give every leaf `--json` (unless it already owns one) and `--prose`."""
    for leaf in leaf_commands(parser).values():
        if "--json" not in leaf._option_string_actions:
            leaf.add_argument("--json", action="store_true", dest="json",
                              help="print JSON")
        if "--prose" not in leaf._option_string_actions:
            leaf.add_argument("--prose", action="store_true", dest="prose",
                              help="print prose (default)")


def run(parser: argparse.ArgumentParser, catalog: Catalog,
        command_of: Callable[[argparse.Namespace], str | None],
        argv: list[str] | None = None,
        dispatch: Callable[[argparse.Namespace], Any] | None = None) -> None:
    """Parse, resolve `args.output_mode`, dispatch (default `args.func(args)`),
    and render every refusal: a raised `Refusal` or a `sys.exit(str)`. Int
    exit codes pass through unchanged."""
    raw = sys.argv[1:] if argv is None else list(argv)
    if isinstance(parser, _CatalogParser):
        cls = type(parser)
        previous, cls.argv = cls.argv, raw
        try:
            args, extra = parser.parse_known_args(raw)
        finally:
            cls.argv = previous
    else:
        args, extra = parser.parse_known_args(raw)
    command = command_of(args)
    mode = argv_mode(raw)
    if extra:
        refusal = Refusal(f"{parser.prog}: error: unrecognized arguments: {' '.join(extra)}",
                          code=2)
        render_refusal(catalog, command, refusal, mode)
        sys.exit(2)

    call = dispatch or (lambda a: a.func(a))
    buffer: io.StringIO | None = None
    try:
        own = command in catalog.own_json
        json_flag = bool(getattr(args, "json", False))
        mode = resolve_mode(json_flag and not own, bool(getattr(args, "prose", False)))
        args.output_mode = mode
        if command in catalog.legacy_json:
            args.json = mode == "json"
        if mode == "json" and command in catalog.capture and not (own and json_flag):
            buffer = io.StringIO()
            exit_exc: SystemExit | None = None
            try:
                with contextlib.redirect_stdout(buffer):
                    call(args)
            except SystemExit as exc:
                if isinstance(exc, Refusal) or isinstance(exc.code, str):
                    raise
                exit_exc = exc
            print(dumps(_captured(buffer)))
            if exit_exc is not None:
                raise exit_exc
        else:
            call(args)
    except Refusal as refusal:
        if buffer is not None:
            refusal.lines = [*buffer.getvalue().splitlines(), *refusal.lines]
        render_refusal(catalog, command, refusal, mode)
        sys.exit(refusal.code)
    except SystemExit as exc:
        if not isinstance(exc.code, str):
            raise
        refusal = Refusal(exc.code, code=1)
        if buffer is not None:
            refusal.lines = buffer.getvalue().splitlines()
        render_refusal(catalog, command, refusal, mode)
        sys.exit(refusal.code)


def _captured(buffer: io.StringIO) -> dict[str, Any]:
    lines = buffer.getvalue().splitlines()
    if lines and lines[-1].startswith(NEXT_PREFIX):
        return {"lines": lines[:-1], "next": lines[-1][len(NEXT_PREFIX):]}
    return {"lines": lines}


# ---------------------------------------------------------------------------
# output


def dumps(obj: Any) -> str:
    """Compact one-line JSON, non-ASCII kept."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def emit(mode: str, data: dict[str, Any], prose: str | list[str],
         next: str | None = None, *, json_text: str | None = None) -> None:
    """Print a command result on stdout: JSON (`json_text` verbatim when given,
    else `data` plus `next`), or prose ending with a `next:` line."""
    if mode == "json":
        if json_text is not None:
            print(json_text)
        else:
            print(dumps({**data, "next": next} if next else data))
        return
    for line in [prose] if isinstance(prose, str) else prose:
        print(line)
    if next:
        print(f"{NEXT_PREFIX}{next}")


# ---------------------------------------------------------------------------
# refusals


class Refusal(SystemExit):
    """A refused command: one message plus (kind, item) problems; kind "" is an
    unheaded item. `code` is the int exit code; `lines` holds stdout captured
    before the refusal."""

    def __init__(self, message: str, problems: Iterable[tuple[str, str]] = (),
                 code: int = 1, lines: Iterable[str] = ()) -> None:
        super().__init__(code)
        self.message = message
        self.problems: list[tuple[str, str]] = list(problems)
        self.code = code
        self.lines: list[str] = list(lines)


def refuse(message: str, problems: Iterable[tuple[str, str]] = (), code: int = 1) -> NoReturn:
    raise Refusal(message, problems, code)


def group(problems: Iterable[tuple[str, str]]) -> list[tuple[str, list[str]]]:
    """One entry per kind, kinds in first-seen order, items in input order."""
    grouped: dict[str, list[str]] = {}
    for kind, item in problems:
        grouped.setdefault(kind, []).append(item)
    return list(grouped.items())


def render_refusal(catalog: Catalog, command: str | None, refusal: Refusal,
                   mode: str) -> None:
    """Write the refusal to stderr as prose lines or one JSON error object."""
    example = command_example(catalog, command)
    prefix = (command.rpartition(" ")[0] if command in catalog.examples else command) or ""
    others = [leaf for leaf in catalog.examples if leaf != command]
    if prefix:
        others.sort(key=lambda leaf: not leaf.startswith(prefix + " "))
    others = others[:5]
    frequent = {leaf: catalog.command(catalog.examples[leaf])
                for leaf in catalog.frequent if leaf != command and leaf in catalog.examples}
    grouped = group(refusal.problems)
    if mode == "json":
        error: dict[str, Any] = {
            "command": command,
            "message": refusal.message,
            "problems": [{"kind": kind, "items": items} for kind, items in grouped],
            "example": example,
            "commands": others,
            "examples": frequent,
        }
        if refusal.lines:
            error["lines"] = refusal.lines
        print(dumps({"error": error}), file=sys.stderr)
        return
    out: list[str] = []
    if example:
        out.append(f"example: {example}")
    if others:
        out.append(f"commands: {', '.join(others)}")
    out.extend(f"  {line}" for line in frequent.values())
    out.append(refusal.message)
    for kind, items in grouped:
        if kind:
            out.append(f"  {kind} ({len(items)}):")
            out.extend(f"    - {item}" for item in items)
        else:
            out.extend(f"  - {item}" for item in items)
    print("\n".join(out), file=sys.stderr)
