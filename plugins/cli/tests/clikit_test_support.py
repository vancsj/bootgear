"""Tests for the shared clikit package with a throwaway parser and catalog."""
import contextlib
import io
import json
import os
from unittest import mock

from bootgear_cli import clikit

EXAMPLES = {
    "a one": "a one <name> --flag x",
    "a two": "a two",
    "b": "b --json",
}
CATALOG = clikit.Catalog(prog="tool", examples=EXAMPLES, frequent=("a one", "b"),
                         legacy_json=frozenset({"a two"}), own_json=frozenset({"b"}),
                         capture=frozenset({"b"}))


def _parser(catalog=CATALOG):
    p = clikit.parser_class(catalog)(prog="tool")
    top = p.add_subparsers(dest="cmd", required=True)
    a = top.add_parser("a")
    a_sub = a.add_subparsers(dest="sub", required=True)
    one = a_sub.add_parser("one")
    one.add_argument("name")
    one.add_argument("--flag", required=True, choices=["x", "y"])
    a_sub.add_parser("two")
    b = top.add_parser("b")
    b.add_argument("--json", action="store_true", help="own json")
    clikit.add_mode_flags(p)
    return p


def _command_of(args):
    return " ".join(part for part in (args.cmd, getattr(args, "sub", None)) if part)


class _Run:
    """Result of one `run` call: exit code (None on return), stdout, stderr."""

    def __init__(self, argv, dispatch, env=None, catalog=CATALOG):
        out, err = io.StringIO(), io.StringIO()
        environ = {k: v for k, v in os.environ.items()
                   if k not in (clikit.ENV_MODE, clikit.ENV_PROG)}
        environ.update(env or {})
        self.code = None
        with mock.patch.dict(os.environ, environ, clear=True), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                clikit.run(_parser(catalog), catalog, _command_of, argv, dispatch)
            except SystemExit as exc:
                self.code = exc.code
        self.out, self.err = out.getvalue(), err.getvalue()

    def err_json(self):
        return json.loads(self.err)["error"]


def _noop(args):
    return None


SESSION_VARIABLES = ("BOOTGEAR_SESSION_ID", "CLAUDE_CODE_SESSION_ID", "CODEX_SESSION_ID")
FAILING_PS = "#!/bin/sh\nexit 1\n"
# The chain above the test process: zsh, codex, bash, then claude at the top.
HOST_CHAIN_PS = """#!/bin/sh
[ "$1 $2 $3" = "-o ppid=,comm= -p" ] || exit 64
case "$4" in
  1001) echo " 1002 /Applications/Codex.app/Contents/Resources/codex" ;;
  1002) echo " 1003 -bash" ;;
  1003) echo "    1 /usr/local/bin/claude" ;;
  *) echo " 1001 /bin/zsh" ;;
esac
"""
# Each call logs its pid and names a new parent that is a plain shell.
ENDLESS_CHAIN_PS = """#!/bin/sh
echo "$4" >> '{calls}'
echo " $(($4 + 1)) /bin/bash"
"""
# The first parent is pid 1; pid 1 itself would print a host process.
INIT_PARENT_PS = """#!/bin/sh
echo "$4" >> '{calls}'
case "$4" in
  1) echo "    0 /usr/local/bin/claude" ;;
  *) echo "    1 /bin/bash" ;;
esac
"""
