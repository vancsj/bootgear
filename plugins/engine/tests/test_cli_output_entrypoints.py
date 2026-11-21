import json
import subprocess
import sys

from cli_output_test_support import (
    PLUGIN_DIR,
    PROBE,
    PROG,
    SETTLEMENT,
    CliOutputTestCase,
    _env,
)
from gear_commands import HOST


class CliOutputTest(CliOutputTestCase):
    def test_unreadable_inputs_are_refused_without_traceback(self):
        missing = self._task("session", "init", "fresh-run", "--dir", str(self.session_dir),
                             "--settlement-file", str(self.tmp / "missing.txt"), "--prose")
        self.assertEqual(missing.returncode, 1)
        self.assertNotIn("Traceback", missing.stderr)
        self.assertIn("cannot init", missing.stderr)
        self.assertLess(missing.stderr.index("example: "), missing.stderr.index("cannot init"))
        self.assertFalse((self.session_dir / "fresh-run.md").exists())
        for mode in (0o555, 0o000):
            locked = self.tmp / f"locked-{mode:o}"
            locked.mkdir()
            locked.chmod(mode)
            self.addCleanup(locked.chmod, 0o755)
            target = locked if mode == 0o555 else locked / "inner"
            denied = self._task("session", "init", "fresh-run", "--dir", str(target),
                                "--settlement-file", str(self.tmp / "settlement.txt"), "--prose")
            self.assertEqual(denied.returncode, 1, denied.stderr)
            self.assertNotIn("Traceback", denied.stderr)
            self.assertIn("cannot init", denied.stderr)
            self.assertIn("Permission denied", denied.stderr)
        binary = self.tmp / "binary.yaml"
        binary.write_bytes(b"\xff\xfe\x00")
        invalid = self._task("state", "validate", str(binary), "--prose")
        self.assertEqual(invalid.returncode, 1)
        self.assertNotIn("Traceback", invalid.stderr)
        self.assertIn("cannot read", invalid.stdout)

    def test_module_entry_point_renders_refusals(self):
        result = subprocess.run(
            [sys.executable, "-m", "engine.session", "record-decision", self.run_id,
             "--dir", str(self.session_dir), "--mode", "debate",
             "--summary", "round 1, party 'main-agent': x", "--prose"],
            capture_output=True, text=True, check=False,
            env=_env(BOOTGEAR_PROG=PROG, BOOTGEAR_HOST=HOST))
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("record-decision refused", result.stderr)
        self.assertLess(result.stderr.index("example: "), result.stderr.index("record-decision refused"))

    def test_engine_modules_load_by_file_path(self):
        source = PLUGIN_DIR / "src" / "engine"
        paths = [
            ("session", [str(source / "session.py"), "--help"], "usage:"),
            ("state", [str(source / "state.py"), "--help"], "usage:"),
            ("artefact", [
                "-c",
                "import runpy, sys; assert callable(runpy.run_path(sys.argv[1])['add_subparsers'])",
                str(source / "artefact.py"),
            ], ""),
        ]
        for name, args, usage in paths:
            with self.subTest(module=name):
                result = subprocess.run(
                    [sys.executable, *args], capture_output=True, text=True, check=False,
                    env=_env(BOOTGEAR_PROG=PROG, BOOTGEAR_HOST=HOST))
                self.assertEqual(result.returncode, 0, result.stderr)
                if usage:
                    self.assertIn(usage, result.stdout)

    def test_record_decision_help_lists_debate_summary_forms(self):
        result = self._task("session", "record-decision", "--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        for summary in ("round N, party '<role>':", "scope_settled:",
                        "unanimous_convergence:", "consented_stop:", "round_cap:",
                        "degraded_convergence:"):
            with self.subTest(summary=summary):
                self.assertIn(summary, result.stdout)

    def test_examples_parse_and_cover_every_leaf(self):
        result = subprocess.run(
            [sys.executable, "-c", PROBE], capture_output=True, text=True,
            check=False, env=_env())
        self.assertEqual(result.returncode, 0, result.stderr)
        probe = json.loads(result.stdout)
        self.assertEqual(probe["examples"], probe["leaves"])
        self.assertEqual(probe["bad"], {})
        self.assertEqual(tuple(probe["frequent"]), self.frequent)

    def test_wrapper_pipe_default_is_prose(self):
        result = self._task("session", "read", self.run_id, "--dir",
                            str(self.session_dir), "--section", "state")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith("current: clarify\n"), result.stdout)
        flagged = self._task("session", "read", self.run_id, "--dir",
                             str(self.session_dir), "--section", "state", "--json")
        self.assertEqual(json.loads(flagged.stdout)["current"], "clarify")

    def test_recall_json(self):
        self._session("update-todo", "write tests")
        data = json.loads(self._session("recall").stdout)
        self.assertEqual(set(data), {"run_id", "settlement", "decisions", "open_todos",
                                     "state", "current_node", "recent_pitches"})
        self.assertEqual(set(data["current_node"]), {"current", "terminal", "reminder", "next"})
        self.assertEqual(data["current_node"]["next"], "check the output contract")
        self.assertEqual(data["current_node"]["current"], "clarify")
        self.assertFalse(data["current_node"]["terminal"])
        self.assertEqual(data["current_node"]["reminder"]["do"], "check the output contract")
        self.assertIn("task_type: ticket-to-pr", data["settlement"])
        self.assertEqual(data["open_todos"], ["- [ ] write tests"])
        self.assertEqual(data["state"][0], "current: clarify")
        self.assertEqual((data["decisions"], data["recent_pitches"]), ([], []))
        prose = self._session("recall", "--prose").stdout
        self.assertTrue(prose.startswith("-- settlement --\ntask_type: ticket-to-pr\n"),
                        prose)
        self.assertIn("-- open todos --\n- [ ] write tests\n", prose)
        self.assertIn("-- current node --\nclarify\ndo: check the output contract\n", prose)

    def test_json_mode_state_fields(self):
        result = self._exported_session("read", "--section", "state")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["run_id"], self.run_id)
        self.assertEqual(data["section"], "state")
        self.assertEqual(data["current"], "clarify")
        self.assertRegex(data["started"], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
        self.assertEqual(data["transitions"], [])
        self.assertEqual(data["lines"][0], "current: clarify")

    def test_prose_flag_beats_exported_json(self):
        result = self._exported_session("read", "--section", "state", "--prose")
        self.assertTrue(result.stdout.startswith("current: clarify\n"), result.stdout)

    def test_json_mode_refusal_is_one_json_error_object(self):
        result = self._exported_session("read", "--last", "0")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        error = json.loads(result.stderr)["error"]
        self.assertEqual(error["command"], "session read")
        self.assertEqual(error["message"], "--last must be a positive integer")
        self.assertEqual(error["example"], f"{self.prog} session read --dir "
                                           f"<session-dir> --section state")
        self.assertIn("session recall", error["commands"])
        self.assertLessEqual(len(error["commands"]), 5)
        self.assertNotIn("session read", error["commands"])
        self.assertEqual(set(error["examples"]), set(self.frequent))

    def test_recall_current_node_matches_state_current_on_terminal_node(self):
        self._transition("succeeded")
        close = (f"{self.prog} session close {self.run_id} --dir "
                 f"{self.session_dir.resolve()} --outcome succeeded")
        prose = self._task("session", "recall", self.run_id, "--dir",
                           str(self.session_dir), "--prose").stdout
        self.assertIn(f"-- current node --\nsucceeded\nterminal: close the ledger\n"
                      f"next: {close}\n", prose)
        data = json.loads(self._session("recall").stdout)["current_node"]
        self.assertEqual(data, {"current": "succeeded", "terminal": True,
                                "reminder": None, "next": close})
        self._session("close", "succeeded")
        prose = self._task("session", "recall", self.run_id, "--dir",
                           str(self.session_dir), "--prose").stdout
        self.assertIn("-- current node --\nsucceeded\nterminal: the run already ended\n",
                      prose)

    def test_recall_survives_unusable_machine(self):
        self._init_run_raw("no-machine", SETTLEMENT.split("state_machine: |")[0])
        result = self._json_task("session", "recall", "no-machine", "--dir",
                                 str(self.session_dir))
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertIsNone(data["current_node"])
        self.assertIn("task_type: ticket-to-pr", data["settlement"])
        prose = self._task("session", "recall", "no-machine", "--dir",
                           str(self.session_dir), "--prose").stdout
        self.assertIn("-- current node --\n(unavailable: ", prose)
