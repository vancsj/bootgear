"""Session ID defaults and next-command paths for the Engine CLI."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from settlement_fixture import valid_settlement

PLUGIN_DIR = Path(__file__).resolve().parents[1]
TASK_BIN = PLUGIN_DIR / "scripts" / "task"
MACHINE = """\
name: identity-fixture
nodes:
  clarify:
    next: [succeeded]
  succeeded:
    terminal: true
  failed:
    terminal: true
"""


class SessionIdentityTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="engine-session-identity-")).resolve()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.project = self.tmp / "project"
        self.project.mkdir()
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.default_dir = self.home / ".bootgear" / "session"
        self.custom_dir = self.tmp / "custom-session"
        self.settlement_file = self.tmp / "settlement.txt"
        self.settlement_file.write_text(valid_settlement(MACHINE))

    def _env(self, **extra):
        env = {key: value for key, value in os.environ.items()
               if key not in ("BOOTGEAR_OUTPUT", "BOOTGEAR_PROG", "BOOTGEAR_SESSION_ID",
                              "CLAUDE_CODE_SESSION_ID", "GEAR_CALLER_CWD", "VIRTUAL_ENV")}
        env.update({"BOOTGEAR_OUTPUT": "prose", "HOME": str(self.home)})
        env.update(extra)
        return env

    def _task(self, *args, **env):
        return subprocess.run([str(TASK_BIN), *args], capture_output=True, text=True,
                              check=False, cwd=self.project, env=self._env(**env))

    def _init(self, run_id, *, default_dir=False):
        args = ["session", "init", run_id]
        if not default_dir:
            args.extend(("--dir", str(self.custom_dir)))
        args.extend(("--settlement-file", str(self.settlement_file), "--prose"))
        result = self._task(*args)
        self.assertEqual(result.returncode, 0, result.stderr)
        return self.default_dir if default_dir else self.custom_dir

    def _read(self, *args, **env):
        return self._task("session", "read", *args, "--prose", **env)

    def test_explicit_positional_id_wins_over_both_environment_ids(self):
        self._init("explicit-id")
        self._init("shared-id")
        self._init("legacy-id")

        result = self._read("explicit-id", "--dir", str(self.custom_dir),
                            BOOTGEAR_SESSION_ID="shared-id",
                            CLAUDE_CODE_SESSION_ID="legacy-id")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("# session: explicit-id", result.stdout)

    def test_shared_environment_id_is_used_when_positional_id_is_omitted(self):
        self._init("shared-id")
        self._init("legacy-id")

        result = self._read("--dir", str(self.custom_dir),
                            BOOTGEAR_SESSION_ID="shared-id",
                            CLAUDE_CODE_SESSION_ID="legacy-id")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("# session: shared-id", result.stdout)

    def test_claude_environment_id_is_used_when_shared_id_is_absent(self):
        self._init("legacy-id")

        result = self._task("state", "current", "--dir", str(self.custom_dir), "--prose",
                            CLAUDE_CODE_SESSION_ID="legacy-id")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("STATE    current: clarify", result.stdout)

    def test_session_and_state_report_a_missing_run_id_without_either_environment_id(self):
        for args in (("session", "read", "--dir", str(self.custom_dir)),
                     ("state", "current", "--dir", str(self.custom_dir))):
            with self.subTest(args=args):
                result = self._task(*args)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("missing run-id", result.stderr)

    def test_explicit_positional_form_with_later_operands_still_works(self):
        self._init("positional-id")

        todo = self._task("session", "update-todo", "positional-id", "keep positional",
                          "--dir", str(self.custom_dir), "--prose")
        pitch = self._task("session", "record-pitch", "positional-id", "keep pitch",
                           "--dir", str(self.custom_dir), "--prose")
        self.assertEqual(todo.returncode, 0, todo.stderr)
        self.assertEqual(pitch.returncode, 0, pitch.stderr)

        todo_read = self._read("positional-id", "--dir", str(self.custom_dir),
                               "--section", "todos")
        pitch_read = self._read("positional-id", "--dir", str(self.custom_dir),
                                "--section", "pitches")
        self.assertIn("keep positional", todo_read.stdout)
        self.assertIn("keep pitch", pitch_read.stdout)

    def test_environment_id_with_later_operands_uses_named_options(self):
        self._init("implicit-id")
        todo = self._task("session", "update-todo", "--text", "from environment",
                          "--dir", str(self.custom_dir), "--prose",
                          BOOTGEAR_SESSION_ID="implicit-id")
        pitch = self._task("session", "record-pitch", "--text", "from environment",
                           "--dir", str(self.custom_dir), "--prose",
                           BOOTGEAR_SESSION_ID="implicit-id")
        self.assertEqual(todo.returncode, 0, todo.stderr)
        self.assertEqual(pitch.returncode, 0, pitch.stderr)

        closed_dir = self._init("implicit-close")
        moved = self._task("state", "transition", "implicit-close", "--dir", str(closed_dir),
                           "--to", "succeeded", "--reason", "done", "--prose")
        self.assertEqual(moved.returncode, 0, moved.stderr)
        closed = self._task("session", "close", "--outcome", "succeeded",
                            "--dir", str(closed_dir), "--prose",
                            BOOTGEAR_SESSION_ID="implicit-close")
        self.assertEqual(closed.returncode, 0, closed.stderr)
        self.assertTrue((closed_dir / "implicit-close.md").read_text().endswith("succeeded\n"))

    def test_next_commands_omit_default_dir_and_keep_custom_dir(self):
        for default_dir in (True, False):
            with self.subTest(default_dir=default_dir):
                directory = self._init(f"next-{default_dir}", default_dir=default_dir)
                dir_args = [] if default_dir else ["--dir", str(directory)]
                self._task("session", "record-decision", f"next-{default_dir}", *dir_args,
                           "--mode", "debate", "--question", "q1",
                           "--summary", "round 0, party 'main-agent': scope", "--prose")
                decision = self._task("session", "record-decision", f"next-{default_dir}",
                                      *dir_args, "--mode", "scope-settled", "--question", "q1",
                                      "--summary", "scope_settled: topic and cutoff", "--prose")
                self.assertEqual(decision.returncode, 0, decision.stderr)
                decision_next = decision.stdout.strip().splitlines()[-1]
                self.assertIn("session record-decision next-", decision_next)

                state_id = f"state-{default_dir}"
                self._init(state_id, default_dir=default_dir)
                moved = self._task("state", "transition", state_id, *dir_args,
                                   "--to", "succeeded", "--reason", "done", "--prose")
                self.assertEqual(moved.returncode, 0, moved.stderr)
                current = self._task("state", "current", state_id, *dir_args, "--prose")
                self.assertEqual(current.returncode, 0, current.stderr)
                state_next = current.stdout.strip().splitlines()[-1]
                self.assertIn(f"session close {state_id}", state_next)

                for command in (decision_next, state_next):
                    if default_dir:
                        self.assertNotIn("--dir", command)
                    else:
                        self.assertIn(f"--dir {directory}", command)


if __name__ == "__main__":
    unittest.main()
