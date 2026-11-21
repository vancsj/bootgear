"""CLI output contract for the public Gear `engine task` route: prose by default, explicit JSON with
`--prose`, runnable refusals (example, sibling commands, frequent examples),
every ledger problem in one refusal, caller-relative paths, and `next` steps.

Drives the real wrapper as a subprocess; `BOOTGEAR_OUTPUT` is removed from the
child env so the prose default is what gets tested.
"""
import json
import os
import shlex
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any

from bootgear_cli import runtime
from gear_commands import TASK as TASK_COMMAND
from gear_commands import display
from settlement_fixture import valid_settlement

PLUGIN_DIR = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PLUGIN_DIR.parents[1]
PROG = display("engine", "task")
FREQUENT = ("session recall", "session record-decision", "state transition")

SMOKE_MACHINE = """\
name: smoke
nodes:
  clarify:
    next: [succeeded]
    reminder:
      do: check the output contract
  succeeded:
    terminal: true
  failed:
    terminal: true
"""

SETTLEMENT = valid_settlement(SMOKE_MACHINE, approach="output contract test",
                              succeeded="output contract holds", failed="never")

MACHINE = """\
name: tiny
nodes:
  clarify:
    next: [succeeded]
  succeeded:
    terminal: true
  failed:
    terminal: true
"""

# Probe run inside the plugin's own environment: every example parses with
# the real parser into its own leaf, and the examples cover every leaf.
PROBE = """
import json, shlex
from engine import cli
from bootgear_cli.clikit import leaf_commands
parser = cli.build_parser()
bad = {}
for leaf, example in cli.EXAMPLES.items():
    try:
        args = parser.parse_args(shlex.split(example))
    except SystemExit as exc:
        bad[leaf] = f"exit {exc.code}"
        continue
    if f"{args.group} {args.cmd}" != leaf:
        bad[leaf] = f"parsed as {args.group} {args.cmd}"
    elif any(getattr(args, name, None) is not None for name in ("run_id", "text", "outcome")):
        bad[leaf] = "passes the run id or a positional operand"
print(json.dumps({"leaves": sorted(leaf_commands(parser)),
                  "examples": sorted(cli.EXAMPLES), "bad": bad,
                  "frequent": list(cli.CATALOG.frequent)}))
"""


def _env(**extra):
    env = {k: v for k, v in os.environ.items()
           if k not in ("BOOTGEAR_OUTPUT", "BOOTGEAR_PROG", "GEAR_CALLER_CWD",
                        "VIRTUAL_ENV", "BOOTGEAR_TEST_HOME", "BOOTGEAR_TEST_DATA")}
    paths = [str(PLUGIN_DIR / "src"), str(REPOSITORY_ROOT / "plugins" / "cli" / "src")]
    if env.get("PYTHONPATH"):
        paths.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(paths)
    if os.environ.get("BOOTGEAR_TEST_HOME"):
        env["HOME"] = os.environ["BOOTGEAR_TEST_HOME"]
    if os.environ.get("BOOTGEAR_TEST_DATA"):
        env["XDG_DATA_HOME"] = os.environ["BOOTGEAR_TEST_DATA"]
    env.update(extra)
    return env


class CliOutputTestCase(unittest.TestCase):
    task_command = TASK_COMMAND
    prog = PROG
    frequent = FREQUENT

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="engine-cli-output-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.data = self.tmp / "data"
        runtimes = self.data / "bootgear" / "runtimes"
        runtimes.parent.mkdir(parents=True)
        runtimes.symlink_to(runtime.environment_path().parent, target_is_directory=True)
        for name, value in (("BOOTGEAR_TEST_HOME", str(self.home)),
                            ("BOOTGEAR_TEST_DATA", str(self.data))):
            previous = os.environ.get(name)
            os.environ[name] = value

            def restore(key=name, old=previous):
                if old is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = old

            self.addCleanup(restore)
        self.session_dir = self.tmp / "session"
        self.run_id = "out-run"
        settlement = self.tmp / "settlement.txt"
        settlement.write_text(SETTLEMENT)
        result = self._task("session", "init", self.run_id, "--dir",
                            str(self.session_dir), "--settlement-file", str(settlement))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.ledger = self.session_dir / f"{self.run_id}.md"

    def _task(self, *args, stdout: Any = subprocess.PIPE, cwd=None, **env):
        return subprocess.run([*self.task_command, *args], stdout=stdout,
                              stderr=subprocess.PIPE, text=True, check=False,
                              cwd=cwd, env=_env(**env))

    def _json_task(self, *args, **env):
        """Request JSON explicitly for a machine-readable assertion."""
        if "--json" not in args and "--prose" not in args:
            args = (*args, "--json")
        return self._task(*args, **env)

    def _session(self, cmd, *args, **env):
        return self._json_task("session", cmd, self.run_id, "--dir",
                               str(self.session_dir), *args, **env)

    def _assert_refusal_lines(self, stderr, command, example):
        """The example, sibling commands and frequent examples come first; the message and
        its problems are the last lines."""
        lines = stderr.splitlines()
        self.assertEqual(lines[0], f"example: {self.prog} {example}", stderr)
        self.assertTrue(lines[1].startswith("commands: "), stderr)
        for leaf in self.frequent:
            if leaf != command:
                self.assertTrue(any(line.startswith(f"  {self.prog} {leaf} ") for line in lines[2:]), stderr)
        self.assertFalse(lines[-1].startswith(("example: ", "commands: ", f"  {self.prog} ")), stderr)

    def _validate_party_config(self, parties_yaml: str, name: str):
        settlement = self.tmp / f"{name}.txt"
        settlement.write_text(SETTLEMENT.replace(
            "debate_party_config: {}\n", "debate_party_config:\n  parties:\n" + parties_yaml))
        return self._task("session", "validate", name, "--dir", str(self.session_dir),
                          "--settlement-file", str(settlement), "--prose")

    # --- state current ----------------------------------------------------

    def _init_run(self, run_id, settlement_text):
        settlement = self.tmp / f"{run_id}-settlement.txt"
        settlement.write_text(settlement_text)
        result = self._task("session", "init", run_id, "--dir",
                            str(self.session_dir), "--settlement-file", str(settlement))
        self.assertEqual(result.returncode, 0, result.stderr)

    def _init_run_raw(self, run_id, settlement_text):
        """Init a run, then replace its ledger settlement with `settlement_text`,
        which `init` itself refuses."""
        self._init_run(run_id, SETTLEMENT)
        ledger = self.session_dir / f"{run_id}.md"
        head, rest = ledger.read_text().split("## settlement\n", 1)
        _, tail = rest.split("\n\n## decisions", 1)
        ledger.write_text(f"{head}## settlement\n{settlement_text.rstrip(chr(10))}"
                          f"\n\n## decisions{tail}")

    def _current(self, run_id=None, *extra):
        return self._task("state", "current", run_id or self.run_id, "--dir",
                          str(self.session_dir), *extra)

    def _current_json(self, run_id=None):
        result = self._json_task("state", "current", run_id or self.run_id, "--dir",
                                 str(self.session_dir))
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    # --- close requires the matching terminal node -----------------------

    def _transition(self, dest):
        result = self._task("state", "transition", self.run_id, "--dir",
                            str(self.session_dir), "--to", dest, "--reason", "r",
                            "--prose")
        self.assertEqual(result.returncode, 0, result.stderr)

    def _close_args(self, outcome):
        return ("close", outcome, "--reason", "r") if outcome == "failed" else ("close", outcome)

    def _refused_close_fix(self, outcome, first_line):
        """Refuse `close <outcome>`, check the refusal's first line, and run
        the command it names, with its placeholders filled in."""
        result = self._session(*self._close_args(outcome), "--prose")
        self.assertEqual(result.returncode, 1, result.stderr)
        line = result.stderr.splitlines()[-1]
        self.assertTrue(line.startswith(first_line), line)
        self.assertNotIn("## closed", self.ledger.read_text())
        argv = shlex.split(line.split(" — run: ", 1)[1])
        prefix = shlex.split(self.prog)
        self.assertEqual(argv[:len(prefix)], prefix)
        argv = [self.prog, *argv[len(prefix):]]
        self.assertEqual(argv[0], self.prog)
        args = (a if not a.startswith("<") else "r" for a in argv[1:])
        fixed = subprocess.run([*self.task_command, *args], capture_output=True, text=True,
                                check=False, env=_env())
        self.assertEqual(fixed.returncode, 0, fixed.stderr)
        return argv


    def _exported_session(self, cmd, *args):
        return self._task("session", cmd, self.run_id, "--dir", str(self.session_dir),
                          *args, BOOTGEAR_OUTPUT="json")
