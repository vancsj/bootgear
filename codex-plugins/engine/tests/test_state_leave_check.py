"""CLI-level tests for a node's `reminder.leave_check` program gate.

Drives the host `task` wrapper as a subprocess against scratch ledgers. The
check program is a scratch shell script found through PATH; the host lookup
test runs a scratch copy of the plugin so a program can be placed in its
`scripts/` directory without touching the real plugin tree.
"""
import os
import shutil
import stat
import subprocess
import tempfile
import textwrap
import time
import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
TASK_REL = Path("scripts") / "task"
TASK_BIN = PLUGIN_DIR / TASK_REL
PROGRAM = "engine-test-leave-check"

SETTLEMENT_HEAD = """\
task_type: ticket-to-pr
approach: smoke test
principles: none
source_of_truth:
  scope: ticket
debate_threshold: any
debate_round_cap: 10
convergence_policy: unanimous
consented_stop_allowed: true
debate_roster: [main-agent, independent-reviewer, adversarial-reviewer]
debate_party_config: {}
spec_skill: spec
test_skill: test
review_skill: review
autonomy:
  no_further_questions: true
  permitted_mutations: [edit files]
goal:
  succeeded: smoke test passes
  failed: never
state_machine: |
"""


def _machine(program=PROGRAM):
    return f"""\
name: gated
nodes:
  clarify:
    next: [gate]
  gate:
    reminder:
      leave: "The check passed."
      leave_check: [{program}, "{{slate}}", --dir, "{{converge_dir}}"]
    next: [done]
  done:
    next: [succeeded]
  succeeded:
    terminal: true
  failed:
    terminal: true
"""


# Records its argv one per line (and its output mode beside it), prints
# CHECK_LINES numbered lines, then sleeps CHECK_SLEEP seconds (in a child, so
# a timeout must kill the group) and exits CHECK_EXIT.
CHECK_SCRIPT = """\
#!/bin/sh
: > "$CHECK_ARGV_FILE"
printf '%s' "${BOOTGEAR_OUTPUT:-}" > "$CHECK_ARGV_FILE.mode"
for a in "$@"; do printf '%s\\n' "$a" >> "$CHECK_ARGV_FILE"; done
i=1
while [ "$i" -le "${CHECK_LINES:-0}" ]; do echo "line $i"; i=$((i + 1)); done
echo "to stderr" >&2
if [ -n "${CHECK_SLEEP:-}" ]; then sleep "$CHECK_SLEEP"; fi
exit "${CHECK_EXIT:-0}"
"""


def _write_program(directory: Path, name: str, body: str = CHECK_SCRIPT) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


class LeaveCheckSchemaTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="engine-leave-check-schema-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _validate(self, reminder_lines):
        path = self.tmp / "machine.yaml"
        path.write_text(
            "name: m\nnodes:\n  clarify:\n    reminder:\n"
            + "".join(f"      {line}\n" for line in reminder_lines)
            + "    next: [succeeded]\n"
            "  succeeded:\n    terminal: true\n  failed:\n    terminal: true\n"
        )
        return subprocess.run([str(TASK_BIN), "state", "validate", str(path)],
                              capture_output=True, text=True, check=False)

    def test_valid_leave_check(self):
        result = self._validate([
            'leave: "done"',
            'leave_check: [converge, gate, "{slate}", --dir, "{converge_dir}"]',
        ])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(": ok", result.stdout)

    def test_invalid_values_are_each_listed(self):
        cases = {
            "leave_check: []": "must be a non-empty list of strings",
            "leave_check: converge": "must be a non-empty list of strings",
            'leave_check: [converge, ""]': "`reminder.leave_check[1]` must be a non-empty string",
            "leave_check: [converge, 3]": "`reminder.leave_check[1]` must be a non-empty string",
            'leave_check: [converge, "{Slate}"]': "is not a {name} placeholder",
            'leave_check: [converge, "{a-b}"]': "is not a {name} placeholder",
            'leave_check: [converge, "{slate"]': "is not a {name} placeholder",
            'leave_check: [converge, "x}"]': "is not a {name} placeholder",
        }
        for line, expected in cases.items():
            with self.subTest(line=line):
                result = self._validate(['leave: "done"', line])
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn(expected, result.stdout)

    def test_leave_check_requires_leave(self):
        result = self._validate(["leave_check: [converge, gate]"])
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("`reminder.leave_check` requires `reminder.leave`", result.stdout)

    def test_every_problem_is_listed(self):
        result = self._validate(['leave_check: [converge, "", "{X}"]'])
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("3 problem(s) found", result.stdout)


class _LeaveCheckLedger(unittest.TestCase):
    task_bin = TASK_BIN

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="engine-leave-check-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.session_dir = self.tmp / "session"
        self.session_dir.mkdir()
        self.bin_dir = self.tmp / "bin"
        _write_program(self.bin_dir, PROGRAM)
        self.argv_file = self.tmp / "argv.txt"
        self.env = {
            **os.environ,
            "PATH": f"{self.bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
            "CHECK_ARGV_FILE": str(self.argv_file),
        }
        for key in ("CHECK_EXIT", "CHECK_SLEEP", "CHECK_LINES",
                    "ENGINE_LEAVE_CHECK_TIMEOUT", "PLUGIN_ROOT"):
            self.env.pop(key, None)
        self.run_id = "test-run"
        self.ledger = self.session_dir / f"{self.run_id}.md"

    def _init(self, machine=None):
        settlement = self.tmp / "settlement.txt"
        settlement.write_text(
            SETTLEMENT_HEAD
            + textwrap.indent(machine or _machine(), "  ")
            + f"session_dir: {self.session_dir}\n"
        )
        result = self._task("session", "init", self.run_id,
                            "--settlement-file", str(settlement))
        self.assertEqual(result.returncode, 0, result.stderr)
        result = self._move("gate")
        self.assertEqual(result.returncode, 0, result.stderr)

    def _task(self, *args, **env):
        return subprocess.run(
            [str(self.task_bin), *args, "--dir", str(self.session_dir)],
            capture_output=True, text=True, check=False,
            env={**self.env, **env},
        )

    def _move(self, dest, *extra, **env):
        return self._task("state", "transition", self.run_id, "--to", dest,
                          "--reason", f"to {dest}", *extra, **env)

    def _leave(self, *extra, dest="done", **env):
        return self._move(dest, "--confirm-leave", *extra, **env)

    def _assert_refused_unchanged(self, *extra, dest="done", confirm=True, **env):
        before = self.ledger.read_bytes()
        if confirm:
            result = self._leave(*extra, dest=dest, **env)
        else:
            result = self._move(dest, *extra, **env)
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertEqual(self.ledger.read_bytes(), before)
        self.assertNotIn("Traceback", result.stderr)
        return result

    def _log_lines(self):
        return [line for line in self.ledger.read_text().splitlines()
                if line.startswith("- ")]



class LeaveCheckTransitionTest(_LeaveCheckLedger):
    def test_pass_substitutes_args_without_a_shell_and_logs_the_argv(self):
        self._init()
        slate = "slate one; $(echo pwned) `id`"
        result = self._leave("--leave-arg", f"slate={slate}",
                             "--leave-arg", "converge_dir=/abs/dir")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.argv_file.read_text().splitlines(),
                         [slate, "--dir", "/abs/dir"])
        resolved = shutil.which(PROGRAM, path=self.env["PATH"])
        self.assertTrue(self._log_lines()[-1].endswith(
            f"gate -> done (to done) [leave_check exit 0: {resolved} {slate} "
            f"--dir /abs/dir]"), self._log_lines()[-1])
        self.assertIn("current: done", self.ledger.read_text())

    def test_check_prints_prose_whatever_the_callers_mode(self):
        self._init()
        result = self._leave("--leave-arg", "slate=s", "--leave-arg", "converge_dir=/d",
                             BOOTGEAR_OUTPUT="json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(Path(f"{self.argv_file}.mode").read_text(), "prose")

    def test_nonzero_exit_is_refused_quoting_the_last_40_lines(self):
        self._init()
        result = self._assert_refused_unchanged(
            "--leave-arg", "slate=s", "--leave-arg", "converge_dir=/d",
            CHECK_EXIT="3", CHECK_LINES="50")
        self.assertIn("'gate' leave_check exited 3", result.stderr)
        self.assertIn("line 50", result.stderr)
        self.assertIn("line 12", result.stderr)
        self.assertNotIn("line 11\n", result.stderr)
        self.assertIn("to stderr", result.stderr)

    def test_timeout_is_refused(self):
        self._init()
        started = time.monotonic()
        result = self._assert_refused_unchanged(
            "--leave-arg", "slate=s", "--leave-arg", "converge_dir=/d",
            CHECK_SLEEP="30", CHECK_LINES="1", ENGINE_LEAVE_CHECK_TIMEOUT="1")
        self.assertLess(time.monotonic() - started, 20)
        self.assertIn("'gate' leave_check timed out after 1s", result.stderr)
        self.assertIn("line 1", result.stderr)

    def test_missing_program_is_refused_without_a_traceback(self):
        self._init(_machine(program="engine-no-such-leave-check-program"))
        result = self._assert_refused_unchanged(
            "--leave-arg", "slate=s", "--leave-arg", "converge_dir=/d")
        self.assertIn("leave_check program 'engine-no-such-leave-check-program' "
                      "not found — install the plugin that provides it",
                      result.stderr)

    def test_missing_extra_and_empty_args_are_refused(self):
        self._init()
        cases = {
            ("--leave-arg", "slate=s"):
                "placeholder '{converge_dir}' has no --leave-arg converge_dir=<value>",
            ("--leave-arg", "slate=s", "--leave-arg", "converge_dir=/d",
             "--leave-arg", "other=x"):
                "--leave-arg 'other' matches no placeholder",
            ("--leave-arg", "slate=", "--leave-arg", "converge_dir=/d"):
                "--leave-arg 'slate' has an empty value",
            ("--leave-arg", "slate", "--leave-arg", "converge_dir=/d"):
                "--leave-arg 'slate' is not name=value",
            ("--leave-arg", "slate=--help", "--leave-arg", "converge_dir=/d"):
                "--leave-arg 'slate' starts with '-'",
        }
        for extra, expected in cases.items():
            with self.subTest(extra=extra):
                result = self._assert_refused_unchanged(*extra)
                self.assertIn(expected, result.stderr)
                self.assertFalse(self.argv_file.exists())

    def test_every_arg_problem_is_listed(self):
        self._init()
        result = self._assert_refused_unchanged("--leave-arg", "slate=",
                                                "--leave-arg", "other=x")
        self.assertIn("3 problem(s) found", result.stderr)

    def test_leave_arg_on_a_node_without_leave_check_is_refused(self):
        self._init()
        self.assertEqual(self._leave("--leave-arg", "slate=s",
                                     "--leave-arg", "converge_dir=/d").returncode, 0)
        result = self._assert_refused_unchanged("--leave-arg", "slate=s",
                                                dest="succeeded", confirm=False)
        self.assertIn("has no leave_check", result.stderr)

    def test_failed_is_legal_without_the_check(self):
        self._init()
        result = self._leave(dest="failed", CHECK_EXIT="1")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.argv_file.exists())
        self.assertIn("current: failed", self.ledger.read_text())
        self.assertNotIn("[leave_check", self._log_lines()[-1])

    def test_failed_needs_no_confirm_leave(self):
        self._init()
        result = self._move("failed")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("current: failed", self.ledger.read_text())
        self.assertTrue(self._log_lines()[-1].endswith("gate -> failed (to failed)"),
                        self._log_lines()[-1])

    def test_passing_check_without_confirm_leave_is_refused(self):
        self._init()
        result = self._assert_refused_unchanged(
            "--leave-arg", "slate=s", "--leave-arg", "converge_dir=/d",
            confirm=False)
        self.assertIn("Pass --confirm-leave", result.stderr)

    def test_confirm_leave_never_bypasses_a_failing_check(self):
        self._init()
        result = self._assert_refused_unchanged(
            "--leave-arg", "slate=s", "--leave-arg", "converge_dir=/d",
            CHECK_EXIT="1")
        self.assertIn("'gate' leave_check exited 1", result.stderr)

    def test_confirm_leave_never_bypasses_missing_args(self):
        self._init()
        result = self._assert_refused_unchanged()
        self.assertIn("has no --leave-arg slate=<value>", result.stderr)


def _copy_plugin(dest: Path) -> Path:
    root = dest / "plugin"
    shutil.copytree(PLUGIN_DIR, root, ignore=shutil.ignore_patterns(
        ".venv", "__pycache__", "*.pyc", ".pytest_cache", "tests"))
    return root


class HostLookupTest(_LeaveCheckLedger):
    """Codex host: argv[0] resolves to `<plugin-root>/scripts/<argv0>` when
    that exists and is executable, else by PATH."""

    def setUp(self):
        super().setUp()
        self.plugin_root = _copy_plugin(self.tmp)
        self.task_bin = self.plugin_root / TASK_REL
        self.scripts_program = _write_program(
            self.plugin_root / "scripts", PROGRAM,
            "#!/bin/sh\necho from-scripts > \"$CHECK_ARGV_FILE\"\n")

    def test_plugin_scripts_program_wins_over_path(self):
        self._init()
        result = self._leave("--leave-arg", "slate=s",
                             "--leave-arg", "converge_dir=/d")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.argv_file.read_text(), "from-scripts\n")
        self.assertTrue(self._log_lines()[-1].endswith(
            f"[leave_check exit 0: {self.scripts_program.resolve()} s --dir /d]"),
            self._log_lines()[-1])

    def test_program_in_plugin_scripts_is_found_off_path(self):
        (self.bin_dir / PROGRAM).unlink()
        self._init()
        result = self._leave("--leave-arg", "slate=s",
                             "--leave-arg", "converge_dir=/d")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.argv_file.read_text(), "from-scripts\n")

    def test_non_executable_scripts_file_falls_back_to_path(self):
        self.scripts_program.chmod(0o644)
        self._init()
        result = self._leave("--leave-arg", "slate=s",
                             "--leave-arg", "converge_dir=/d")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.argv_file.read_text().splitlines(),
                         ["s", "--dir", "/d"])

    def test_absent_scripts_file_falls_back_to_path(self):
        self.scripts_program.unlink()
        self._init()
        result = self._leave("--leave-arg", "slate=s",
                             "--leave-arg", "converge_dir=/d")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.argv_file.read_text().splitlines(),
                         ["s", "--dir", "/d"])


if __name__ == "__main__":
    unittest.main()
