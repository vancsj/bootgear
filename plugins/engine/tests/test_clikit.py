"""Tests for plugins/engine/src/engine/clikit.py.

Loads the file by path (the same bytes are copied into other plugins) and
drives `run` with a throwaway two-level parser and catalog.
"""
import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

CLIKIT = Path(__file__).resolve().parents[1] / "src" / "engine" / "clikit.py"

_spec = importlib.util.spec_from_file_location("clikit_under_test", CLIKIT)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"could not load {CLIKIT}")
clikit = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = clikit  # dataclass() resolves the module by name
_spec.loader.exec_module(clikit)

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


class ResolveModeTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ)
        patcher.start()
        self.addCleanup(patcher.stop)
        os.environ.pop(clikit.ENV_MODE, None)
        r, w = os.pipe()
        self.pipe = os.fdopen(w, "w")
        self.addCleanup(self.pipe.close)
        self.addCleanup(os.close, r)
        self.file = self.enterContext(tempfile.TemporaryFile("w"))

    def test_all_sinks_default_to_prose(self):
        self.assertEqual(clikit.resolve_mode(False, False, self.pipe), "prose")
        self.assertEqual(clikit.resolve_mode(False, False, self.file), "prose")

    def test_stream_without_fileno_is_prose(self):
        self.assertEqual(clikit.resolve_mode(False, False, io.StringIO()), "prose")

    def test_env_beats_stream(self):
        os.environ[clikit.ENV_MODE] = "prose"
        self.assertEqual(clikit.resolve_mode(False, False, self.pipe), "prose")
        os.environ[clikit.ENV_MODE] = "json"
        self.assertEqual(clikit.resolve_mode(False, False, self.file), "json")

    def test_bogus_env_is_ignored(self):
        os.environ[clikit.ENV_MODE] = "bogus"
        self.assertEqual(clikit.resolve_mode(False, False, self.pipe), "prose")
        self.assertEqual(clikit.resolve_mode(False, False, self.file), "prose")

    def test_flag_beats_env(self):
        os.environ[clikit.ENV_MODE] = "prose"
        self.assertEqual(clikit.resolve_mode(True, False, self.file), "json")
        os.environ[clikit.ENV_MODE] = "json"
        self.assertEqual(clikit.resolve_mode(False, True, self.pipe), "prose")

    def test_both_flags_refuse_with_exit_2(self):
        with self.assertRaises(clikit.Refusal) as ctx:
            clikit.resolve_mode(True, True, self.pipe)
        self.assertEqual(ctx.exception.code, 2)

    def test_argv_mode(self):
        os.environ[clikit.ENV_MODE] = "prose"
        self.assertEqual(clikit.argv_mode(["a", "--json"]), "json")
        os.environ[clikit.ENV_MODE] = "json"
        self.assertEqual(clikit.argv_mode(["a", "--prose"]), "prose")
        self.assertEqual(clikit.argv_mode(["a", "--json", "--prose"]), "json")

    def test_both_flags_through_run_exit_2(self):
        result = _Run(["a", "two", "--json", "--prose"], _noop)
        self.assertEqual(result.code, 2)
        self.assertIn("--json and --prose are mutually exclusive", result.err)
        self.assertIn("example: tool a two", result.err)


class CallerPathTest(unittest.TestCase):
    def test_absolute_path_untouched(self):
        with mock.patch.dict(os.environ, {clikit.ENV_CALLER_CWD: "/caller"}):
            self.assertEqual(clikit.caller_path("/abs/x"), Path("/abs/x"))

    def test_relative_joins_caller_cwd(self):
        with mock.patch.dict(os.environ, {clikit.ENV_CALLER_CWD: "/caller"}):
            self.assertEqual(clikit.caller_path("rel/x"), Path("/caller/rel/x"))

    def test_relative_without_caller_cwd_joins_cwd(self):
        with mock.patch.dict(os.environ):
            os.environ.pop(clikit.ENV_CALLER_CWD, None)
            self.assertEqual(clikit.caller_path("rel"), Path(os.getcwd()) / "rel")

    def test_tilde_expands(self):
        with mock.patch.dict(os.environ, {clikit.ENV_CALLER_CWD: "/caller"}):
            self.assertEqual(clikit.caller_path("~/x"), Path.home() / "x")


class ParserWiringTest(unittest.TestCase):
    def test_leaf_commands_walks_nested_subparsers(self):
        self.assertEqual(set(clikit.leaf_commands(_parser())), set(EXAMPLES))

    def test_mode_flags_added_and_own_json_kept(self):
        leaves = clikit.leaf_commands(_parser())
        for name, leaf in leaves.items():
            self.assertIn("--prose", leaf._option_string_actions, name)
            self.assertIn("--json", leaf._option_string_actions, name)
        self.assertEqual(leaves["b"]._option_string_actions["--json"].help, "own json")

    def test_display_prog_honours_env(self):
        with mock.patch.dict(os.environ, {clikit.ENV_PROG: "/p/scripts/tool"}):
            self.assertEqual(CATALOG.command("a two"), "/p/scripts/tool a two")


class RefusalRenderingTest(unittest.TestCase):
    def test_parse_error_prose(self):
        result = _Run(["a", "one", "n"], _noop, {clikit.ENV_MODE: "prose"})
        self.assertEqual(result.code, 2)
        self.assertEqual(result.err.splitlines(), [
            "tool a one: error: the following arguments are required: --flag",
            "example: tool a one <name> --flag x",
            "commands: a two, b",
            "  tool b --json",
        ])
        self.assertNotIn("usage:", result.err)

    def test_parse_error_json_uses_run_argv(self):
        result = _Run(["a", "one", "n", "--flag", "z", "--json"], _noop,
                      {clikit.ENV_MODE: "prose"})
        self.assertEqual(result.code, 2)
        error = result.err_json()
        self.assertEqual(error["command"], "a one")
        self.assertIn("invalid choice: 'z'", error["message"])
        self.assertEqual(error["problems"], [])
        self.assertEqual(error["example"], "tool a one <name> --flag x")
        self.assertEqual(error["commands"], ["a two", "b"])
        self.assertEqual(error["examples"], {"b": "tool b --json"})
        self.assertNotIn("lines", error)

    def test_unrecognized_arguments_arrive_on_root(self):
        result = _Run(["a", "two", "--nope"], _noop, {clikit.ENV_MODE: "json"})
        self.assertEqual(result.code, 2)
        error = result.err_json()
        self.assertEqual(error["command"], "a two")
        self.assertEqual(error["message"], "tool: error: unrecognized arguments: --nope")

    def test_non_leaf_command_has_no_example(self):
        prose = _Run(["a"], _noop, {clikit.ENV_MODE: "prose"})
        self.assertEqual(prose.code, 2)
        self.assertTrue(prose.err.startswith("tool a: error: "))
        self.assertNotIn("example:", prose.err)
        self.assertIn("commands: a one, a two, b", prose.err)
        self.assertIn("  tool a one <name> --flag x", prose.err)
        error = _Run(["a"], _noop, {clikit.ENV_MODE: "json"}).err_json()
        self.assertEqual(error["command"], "a")
        self.assertIsNone(error["example"])
        self.assertEqual(error["commands"], ["a one", "a two", "b"])

    def test_sys_exit_str_prose_and_json(self):
        def dispatch(args):
            sys.exit("bad ledger at /x")

        prose = _Run(["a", "two"], dispatch, {clikit.ENV_MODE: "prose"})
        self.assertEqual(prose.code, 1)
        self.assertEqual(prose.err.splitlines()[:2],
                         ["bad ledger at /x", "example: tool a two"])
        error = _Run(["a", "two"], dispatch, {clikit.ENV_MODE: "json"}).err_json()
        self.assertEqual(error["message"], "bad ledger at /x")
        self.assertEqual(error["command"], "a two")

    def test_grouped_refusal_prose_and_json(self):
        problems = [("", "loose"), ("missing section", "## todos"),
                    ("bad todo", "- [?] a"), ("missing section", "## pitches")]

        def dispatch(args):
            clikit.refuse("malformed ledger at /x: 4 problem(s)", problems, code=3)

        prose = _Run(["a", "two"], dispatch, {clikit.ENV_MODE: "prose"})
        self.assertEqual(prose.code, 3)
        self.assertEqual(prose.err.splitlines()[:7], [
            "malformed ledger at /x: 4 problem(s)",
            "  - loose",
            "  missing section (2):",
            "    - ## todos",
            "    - ## pitches",
            "  bad todo (1):",
            "    - - [?] a",
        ])
        json_run = _Run(["a", "two"], dispatch, {clikit.ENV_MODE: "json"})
        self.assertEqual(json_run.code, 3)
        self.assertEqual(json_run.err_json()["problems"], [
            {"kind": "", "items": ["loose"]},
            {"kind": "missing section", "items": ["## todos", "## pitches"]},
            {"kind": "bad todo", "items": ["- [?] a"]},
        ])

    def test_int_exit_passes_through_silently(self):
        result = _Run(["a", "two"], lambda args: sys.exit(4), {clikit.ENV_MODE: "json"})
        self.assertEqual(result.code, 4)
        self.assertEqual(result.err, "")


class ModeWiringTest(unittest.TestCase):
    def test_output_mode_and_legacy_json(self):
        seen = {}

        def dispatch(args):
            seen.update(mode=args.output_mode, json=args.json)

        _Run(["a", "two"], dispatch, {clikit.ENV_MODE: "json"})
        self.assertEqual(seen, {"mode": "json", "json": True})
        _Run(["a", "two"], dispatch, {clikit.ENV_MODE: "prose"})
        self.assertEqual(seen, {"mode": "prose", "json": False})

    def test_own_json_flag_is_not_the_mode_flag(self):
        seen = {}

        def dispatch(args):
            seen.update(mode=args.output_mode, json=args.json)
            print("own shape")

        result = _Run(["b", "--json"], dispatch, {clikit.ENV_MODE: "prose"})
        self.assertEqual(seen, {"mode": "prose", "json": True})
        self.assertEqual(result.out, "own shape\n")

    def test_own_json_flag_skips_capture_in_json_mode(self):
        result = _Run(["b", "--json"], lambda args: print('{"own":1}'),
                      {clikit.ENV_MODE: "json"})
        self.assertEqual(result.out, '{"own":1}\n')


class CaptureTest(unittest.TestCase):
    def test_lines_captured_and_next_lifted(self):
        def dispatch(args):
            print("line one")
            print("line two")
            print("next: tool save")

        result = _Run(["b"], dispatch, {clikit.ENV_MODE: "json"})
        self.assertIsNone(result.code)
        self.assertEqual(json.loads(result.out),
                         {"lines": ["line one", "line two"], "next": "tool save"})

    def test_prose_mode_is_not_captured(self):
        result = _Run(["b"], lambda args: print("line"), {clikit.ENV_MODE: "prose"})
        self.assertEqual(result.out, "line\n")

    def test_int_exit_reraised_after_json(self):
        def dispatch(args):
            print("status: degraded")
            sys.exit(3)

        result = _Run(["b"], dispatch, {clikit.ENV_MODE: "json"})
        self.assertEqual(result.code, 3)
        self.assertEqual(json.loads(result.out), {"lines": ["status: degraded"]})

    def test_refusal_carries_buffered_lines(self):
        def dispatch(args):
            print("EXISTING")
            print("  q1 -> slug-a")
            clikit.refuse("restates an existing question")

        result = _Run(["b"], dispatch, {clikit.ENV_MODE: "json"})
        self.assertEqual(result.code, 1)
        self.assertEqual(result.out, "")
        error = result.err_json()
        self.assertEqual(error["message"], "restates an existing question")
        self.assertEqual(error["lines"], ["EXISTING", "  q1 -> slug-a"])

    def test_sys_exit_str_carries_buffered_lines(self):
        def dispatch(args):
            print("context")
            sys.exit("refused")

        result = _Run(["b"], dispatch, {clikit.ENV_MODE: "json"})
        self.assertEqual(result.code, 1)
        self.assertEqual(result.err_json()["lines"], ["context"])


class EmitTest(unittest.TestCase):
    def _emit(self, *args, **kwargs):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            clikit.emit(*args, **kwargs)
        return out.getvalue()

    def test_json_with_next(self):
        self.assertEqual(self._emit("json", {"id": "F1", "é": 1}, "FILE F1", "go"),
                         '{"id":"F1","é":1,"next":"go"}\n')

    def test_json_text_verbatim(self):
        self.assertEqual(self._emit("json", {}, "x", json_text='{\n  "a": 1\n}'),
                         '{\n  "a": 1\n}\n')

    def test_prose_lines_then_next(self):
        self.assertEqual(self._emit("prose", {}, ["a", "b"], "go"), "a\nb\nnext: go\n")
        self.assertEqual(self._emit("prose", {}, "a"), "a\n")


if __name__ == "__main__":
    unittest.main()
