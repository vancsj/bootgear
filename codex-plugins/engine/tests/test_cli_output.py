"""CLI output contract for `scripts/task`: prose by default through the
wrapper (even on a pipe), JSON with `--json` or `BOOTGEAR_OUTPUT=json`,
runnable refusals naming the wrapper path, every ledger problem in one
refusal, caller-relative paths, and `next` steps.

Drives the real wrapper as a subprocess; `BOOTGEAR_OUTPUT` is removed from the
child env, so JSON cases export `BOOTGEAR_OUTPUT=json` themselves.
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

PLUGIN_DIR = Path(__file__).resolve().parents[1]
TASK_BIN = PLUGIN_DIR / "scripts" / "task"
# The wrapper exports BOOTGEAR_PROG="$0": the path it was invoked by.
PROG = str(TASK_BIN)
FREQUENT = ("session recall", "session record-decision", "state transition")

SETTLEMENT = """\
task_type: ticket-to-pr
approach: output contract test
principles: none
goal:
  succeeded: output contract holds
  failed: never
state_machine: |
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

STRICT_FIELDS = """\
request_assessment: fixture assessment
source_of_truth:
  scope: fixture scope
debate_threshold: fixture reversibility rule
debate_round_cap: 1
convergence_policy: unanimous
consented_stop_allowed: true
debate_party_config: {}
spec_skill: spec
test_skill: test
review_skill: review
debate_roster: [main-agent, independent-reviewer]
review_fix_mode: accepted_only
autonomy:
  no_further_questions: true
  permitted_mutations: [run tests]
"""

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
from engine.clikit import leaf_commands
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
print(json.dumps({"leaves": sorted(leaf_commands(parser)),
                  "examples": sorted(cli.EXAMPLES), "bad": bad,
                  "frequent": list(cli.CATALOG.frequent)}))
"""


def _env(**extra):
    env = {k: v for k, v in os.environ.items()
           if k not in ("BOOTGEAR_OUTPUT", "BOOTGEAR_PROG", "GEAR_CALLER_CWD",
                        "VIRTUAL_ENV", "PLUGIN_ROOT")}
    env.update(extra)
    return env


class CliOutputTest(unittest.TestCase):
    task_bin = TASK_BIN
    prog = PROG
    frequent = FREQUENT

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="engine-cli-output-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.session_dir = self.tmp / "session"
        self.run_id = "out-run"
        settlement = self.tmp / "settlement.txt"
        settlement.write_text(SETTLEMENT)
        result = self._task("session", "init", self.run_id, "--dir",
                            str(self.session_dir), "--settlement-file", str(settlement))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.ledger = self.session_dir / f"{self.run_id}.md"

    def _task(self, *args, stdout: Any = subprocess.PIPE, cwd=None, **env):
        return subprocess.run([str(self.task_bin), *args], stdout=stdout,
                              stderr=subprocess.PIPE, text=True, check=False,
                              cwd=cwd, env=_env(**env))

    def _json_task(self, *args, **env):
        """A command on a pipe with the caller exporting JSON mode (the
        wrapper's own default is prose)."""
        return self._task(*args, **{"BOOTGEAR_OUTPUT": "json", **env})

    def _session(self, cmd, *args, **env):
        return self._json_task("session", cmd, self.run_id, "--dir",
                               str(self.session_dir), *args, **env)

    def _assert_refusal_lines(self, stderr, command, example):
        self.assertIn(f"\nexample: {self.prog} {example}\n", stderr)
        self.assertIn("\ncommands: ", stderr)
        for leaf in self.frequent:
            if leaf != command:
                self.assertIn(f"\n  {self.prog} {leaf} ", stderr)

    # --- mode -------------------------------------------------------------

    def test_wrapper_pipe_default_is_prose(self):
        result = self._task("session", "read", self.run_id, "--dir",
                            str(self.session_dir), "--section", "state")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.startswith("current: clarify\n"), result.stdout)
        flagged = self._task("session", "read", self.run_id, "--dir",
                             str(self.session_dir), "--section", "state", "--json")
        self.assertEqual(json.loads(flagged.stdout)["current"], "clarify")

    def test_session_validate_returns_strict_json_summary(self):
        settlement = self.tmp / "strict.txt"
        settlement.write_text(SETTLEMENT + STRICT_FIELDS)
        init = self._task("session", "init", "strict-run", "--dir",
                          str(self.session_dir), "--settlement-file", str(settlement))
        self.assertEqual(init.returncode, 0, init.stderr)
        result = self._task("session", "validate", "strict-run", "--dir",
                            str(self.session_dir), "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["run_id"], "strict-run")
        self.assertTrue(data["valid"])
        self.assertEqual(data["fields"]["task_type"], "ticket-to-pr")
        self.assertEqual(data["fields"]["state_machine"], "smoke")

    def test_session_validate_groups_strict_refusal_problems(self):
        settlement = self.tmp / "invalid-strict.txt"
        settlement.write_text("task_type: custom\nsession_dir: /wrong\n")
        result = self._task("session", "validate", "invalid-run", "--dir",
                            str(self.session_dir), "--settlement-file", str(settlement),
                            "--prose")
        self.assertEqual(result.returncode, 1)
        self.assertIn("task_type", result.stderr)
        self.assertIn("approach", result.stderr)
        self.assertIn("session_dir", result.stderr)

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
        result = self._session("read", "--section", "state")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["run_id"], self.run_id)
        self.assertEqual(data["section"], "state")
        self.assertEqual(data["current"], "clarify")
        self.assertRegex(data["started"], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
        self.assertEqual(data["transitions"], [])
        self.assertEqual(data["lines"][0], "current: clarify")

    def test_state_json_lists_transitions(self):
        moved = self._task("state", "transition", self.run_id, "--dir",
                           str(self.session_dir), "--to", "succeeded",
                           "--reason", "done", "--prose")
        self.assertEqual(moved.returncode, 0, moved.stderr)
        data = json.loads(self._session("read", "--section", "state").stdout)
        self.assertEqual(data["current"], "succeeded")
        [transition] = data["transitions"]
        self.assertEqual((transition["from"], transition["to"]), ("clarify", "succeeded"))
        self.assertRegex(transition["at"], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$")
        self.assertTrue(transition["line"].startswith(f"- {transition['at']} clarify"))

    def test_read_json_shapes(self):
        whole = json.loads(self._session("read").stdout)
        self.assertEqual(set(whole), {"run_id", "title", "sections", "closed"})
        self.assertIsNone(whole["closed"])
        self.assertIn("task_type: ticket-to-pr", whole["sections"]["settlement"])
        self.assertEqual(whole["sections"]["todos"], [])
        todo = self._session("update-todo", "write tests")
        self.assertEqual(json.loads(todo.stdout), {"todo": "write tests", "status": "added"})
        self.assertEqual(json.loads(self._session("read", "--open-only").stdout),
                         {"run_id": self.run_id, "open_todos": ["- [ ] write tests"]})
        last = json.loads(self._session("read", "--last", "2").stdout)
        self.assertEqual((last["decisions"], last["decisions_total"]), ([], 0))
        self.assertEqual(json.loads(self._session("read", "--question", "q1").stdout),
                         {"run_id": self.run_id, "question": "q1", "decisions": []})

    def test_stdout_to_regular_file_is_prose(self):
        out = self.tmp / "out.txt"
        with out.open("w") as handle:
            result = self._task("session", "read", self.run_id, "--dir",
                                str(self.session_dir), "--section", "state",
                                stdout=handle)
        self.assertEqual(result.returncode, 0, result.stderr)
        text = out.read_text()
        self.assertTrue(text.startswith("current: clarify\nstarted: "), text)

    def test_prose_flag_beats_exported_json(self):
        result = self._session("read", "--section", "state", "--prose")
        self.assertTrue(result.stdout.startswith("current: clarify\n"), result.stdout)

    # --- refusals ---------------------------------------------------------

    def test_argparse_refusal_is_runnable(self):
        # No --prose: the wrapper's default is prose on this pipe.
        result = self._task("state", "transition", self.run_id, "--dir",
                            str(self.session_dir), "--to", "succeeded")
        self.assertEqual(result.returncode, 2)
        self.assertIn("task state transition: error: the following arguments are "
                      "required: --reason", result.stderr)
        self.assertNotIn("usage:", result.stderr)
        self._assert_refusal_lines(
            result.stderr, "state transition", 'state transition <run-id> --dir <session-dir> --to <node> '
                           '--reason "<why>"')

    def test_domain_refusal_is_runnable(self):
        result = self._session("read", "--last", "0", "--prose")
        self.assertEqual(result.returncode, 1)
        self.assertTrue(result.stderr.startswith("--last must be a positive integer\n"),
                        result.stderr)
        self._assert_refusal_lines(
            result.stderr, "session read", "session read <run-id> --dir <session-dir> --section state")

    def test_json_mode_refusal_is_one_json_error_object(self):
        result = self._session("read", "--last", "0")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, "")
        error = json.loads(result.stderr)["error"]
        self.assertEqual(error["command"], "session read")
        self.assertEqual(error["message"], "--last must be a positive integer")
        self.assertEqual(error["example"], f"{self.prog} session read <run-id> --dir "
                                           f"<session-dir> --section state")
        self.assertIn("state transition", error["commands"])
        self.assertNotIn("session read", error["commands"])
        self.assertEqual(set(error["examples"]), set(self.frequent))

    # --- one refusal per scan ---------------------------------------------

    def test_malformed_ledger_reports_every_problem_once(self):
        text = self.ledger.read_text()
        text = text.replace("## todos\n\n",
                            "## todos\n- [y] bad box\n- []\n\n")
        text = text.replace("## decisions\n\n",
                            "## decisions\n- 2026-09-24 10:00 [debate] [q2] round 0, "
                            "party 'a': x\n\n")
        self.ledger.write_text(text)
        result = self._session("read", "--section", "state", "--prose")
        self.assertEqual(result.returncode, 1)
        self.assertTrue(result.stderr.startswith(
            f"malformed ledger at {self.ledger.resolve()}: 3 problem(s)\n"), result.stderr)
        self.assertIn("  question id out of sequence (1):\n", result.stderr)
        self.assertIn("'q2' is the first entry tagging this question, but 'q1'",
                      result.stderr)
        self.assertIn("  bad todo checkbox (2):\n", result.stderr)
        self.assertIn("- '- [y] bad box': ", result.stderr)
        self.assertIn("- '- []': ", result.stderr)

    def test_structure_problems_are_reported_together(self):
        text = self.ledger.read_text().replace("## pitches\n", "").replace(
            "## todos\n", "## todos\n\n## todos\n")
        self.ledger.write_text(text)
        result = self._session("read", "--prose")
        self.assertEqual(result.returncode, 1)
        self.assertIn("2 problem(s)", result.stderr)
        self.assertIn("  missing section (1):\n    - '## pitches'", result.stderr)
        self.assertIn("  duplicated section (1):\n    - '## todos' ×2", result.stderr)

    def test_record_decision_reports_every_problem_once(self):
        result = self._session("record-decision", "--mode", "solo", "--question", "q9",
                               "--summary", "AMENDMENT session_dir: a -> b", "--prose")
        self.assertEqual(result.returncode, 1)
        self.assertIn("record-decision (2):", result.stderr)
        self.assertIn("--question is only for debate modes", result.stderr)
        self.assertIn("'session_dir' cannot be recorded as an AMENDMENT", result.stderr)

    # --- caller-relative paths --------------------------------------------

    def test_relative_dir_and_path_resolve_against_caller_cwd(self):
        caller = self.tmp / "caller"
        caller.mkdir()
        (caller / "machine.yaml").write_text(MACHINE)
        elsewhere = self.tmp / "elsewhere"
        elsewhere.mkdir()
        shutil.copytree(self.session_dir, caller / "rel-session")
        read = self._json_task("session", "read", self.run_id, "--dir", "rel-session",
                               "--section", "state", cwd=elsewhere,
                               GEAR_CALLER_CWD=str(caller))
        self.assertEqual(read.returncode, 0, read.stderr)
        self.assertEqual(json.loads(read.stdout)["current"], "clarify")
        validated = self._json_task("state", "validate", "machine.yaml", cwd=elsewhere,
                                    GEAR_CALLER_CWD=str(caller))
        self.assertEqual(validated.returncode, 0, validated.stderr)
        self.assertEqual(json.loads(validated.stdout),
                         {"path": str(caller / "machine.yaml"), "ok": True, "problems": []})

    # --- next steps -------------------------------------------------------

    def test_next_question_id_names_round_0(self):
        result = self._session("next-question-id")
        data = json.loads(result.stdout)
        self.assertEqual(data["question"], "q1")
        self.assertEqual(
            data["next"],
            f"{self.prog} session record-decision {self.run_id} --dir "
            f"{self.session_dir.resolve()} --mode debate --question q1 --summary "
            f"\"round 0, party '<role>': <topic, scope, principles, cutoff>\"")
        prose = self._session("next-question-id", "--prose")
        self.assertEqual(prose.stdout.splitlines()[0], "q1")
        self.assertEqual(prose.stdout.splitlines()[1], f"next: {data['next']}")

    def test_scope_settled_names_round_1(self):
        self._session("record-decision", "--mode", "debate", "--question", "q1",
                      "--summary", "round 0, party 'a': scope")
        result = self._session("record-decision", "--mode", "scope-settled",
                               "--question", "q1", "--summary", "scope_settled: done")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertTrue(data["line"].endswith("[scope-settled] [q1] scope_settled: done"))
        self.assertEqual(
            data["next"],
            f"{self.prog} session record-decision {self.run_id} --dir "
            f"{self.session_dir.resolve()} --mode debate --question q1 --summary "
            f"\"round 1, party '<role>': <position>\"")

    def test_solo_decision_has_no_next(self):
        result = self._session("record-decision", "--mode", "solo", "--summary", "pick A")
        self.assertNotIn("next", json.loads(result.stdout))
        prose = self._session("record-decision", "--mode", "solo", "--summary", "pick B",
                              "--prose")
        self.assertEqual(prose.stdout, "DECISION recorded\n")

    def test_transition_to_succeeded_names_close(self):
        result = self._session("record-pitch", "shipped")
        self.assertTrue(json.loads(result.stdout)["line"].endswith(" — shipped"))
        result = self._json_task("state", "transition", self.run_id, "--dir",
                                 str(self.session_dir), "--to", "succeeded",
                                 "--reason", "done")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual((data["from"], data["to"], data["reminder"]),
                         ("clarify", "succeeded", None))
        self.assertIn("condition genuinely holds now", data["confirm"])
        self.assertEqual(data["next"], f"{self.prog} session close {self.run_id} --dir "
                                       f"{self.session_dir.resolve()} succeeded")

    def test_transition_prose_ends_with_next_on_terminal_only(self):
        result = self._task("state", "transition", self.run_id, "--dir",
                            str(self.session_dir), "--to", "failed",
                            "--reason", "cannot", "--prose")
        lines = result.stdout.splitlines()
        self.assertEqual(lines[0], "STATE    clarify -> failed")
        self.assertTrue(lines[1].startswith("CONFIRM  before entering 'failed'"))
        self.assertEqual(lines[2], f"next: {self.prog} session close {self.run_id} --dir "
                                   f"{self.session_dir.resolve()} failed --reason "
                                   f"\"<why the goal is undoable>\"")

    # --- state current ----------------------------------------------------

    def _init_run(self, run_id, settlement_text):
        settlement = self.tmp / f"{run_id}-settlement.txt"
        settlement.write_text(settlement_text)
        result = self._task("session", "init", run_id, "--dir",
                            str(self.session_dir), "--settlement-file", str(settlement))
        self.assertEqual(result.returncode, 0, result.stderr)

    def _current(self, run_id=None, *extra):
        return self._task("state", "current", run_id or self.run_id, "--dir",
                          str(self.session_dir), *extra)

    def _current_json(self, run_id=None):
        result = self._json_task("state", "current", run_id or self.run_id, "--dir",
                                 str(self.session_dir))
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_state_current_prints_node_and_full_reminder(self):
        data = self._current_json()
        self.assertEqual(set(data), {"current", "terminal", "reminder", "next"})
        self.assertEqual((data["current"], data["terminal"]), ("clarify", False))
        self.assertEqual(set(data["reminder"]), {"do", "branches", "leave", "leave_check"})
        self.assertEqual(data["reminder"]["do"], "check the output contract")
        self.assertEqual(data["next"], "check the output contract")
        prose = self._current(None, "--prose")
        self.assertEqual(prose.returncode, 0, prose.stderr)
        self.assertEqual(prose.stdout.splitlines(),
                         ["STATE    current: clarify", "do: check the output contract"])

    def test_state_current_node_without_reminder(self):
        self._init_run("bare-run", SETTLEMENT.replace(
            "      reminder:\n        do: check the output contract\n", ""))
        prose = self._current("bare-run", "--prose")
        self.assertEqual(prose.returncode, 0, prose.stderr)
        self.assertEqual(prose.stdout.splitlines(),
                         ["STATE    current: clarify", "no reminder: work toward goal"])
        data = self._current_json("bare-run")
        self.assertEqual(set(data), {"current", "terminal", "reminder"})
        self.assertIsNone(data["reminder"])

    def test_state_current_terminal_on_open_ledger_names_close(self):
        self._transition("succeeded")
        close = (f"{self.prog} session close {self.run_id} --dir "
                 f"{self.session_dir.resolve()} succeeded")
        prose = self._current(None, "--prose")
        self.assertEqual(prose.returncode, 0, prose.stderr)
        self.assertEqual(prose.stdout.splitlines(),
                         ["STATE    current: succeeded", "terminal: close the ledger",
                          f"next: {close}"])
        data = self._current_json()
        self.assertEqual((data["current"], data["terminal"], data["reminder"]),
                         ("succeeded", True, None))
        self.assertEqual(data["next"], close)

    def test_state_current_terminal_on_closed_ledger(self):
        self._transition("succeeded")
        closed = self._session("close", "succeeded")
        self.assertEqual(closed.returncode, 0, closed.stderr)
        prose = self._current(None, "--prose")
        self.assertEqual(prose.returncode, 0, prose.stderr)
        self.assertEqual(prose.stdout.splitlines(),
                         ["STATE    current: succeeded", "terminal: the run already ended"])
        self.assertNotIn("next", self._current_json())

    def test_state_current_reads_the_amended_machine(self):
        machine = self.tmp / "amended.yaml"
        machine.write_text(
            "name: smoke\n"
            "nodes:\n"
            "  clarify:\n"
            "    next: [succeeded]\n"
            "    reminder:\n"
            "      do: check the amended contract with the debate skill\n"
            "  succeeded:\n"
            "    terminal: true\n"
            "  failed:\n"
            "    terminal: true\n")
        amended = self._task("state", "amend", self.run_id, "--dir", str(self.session_dir),
                             "--machine-file", str(machine), "--reason", "r", "--prose")
        self.assertEqual(amended.returncode, 0, amended.stderr)
        self.assertEqual(self._current_json()["reminder"]["do"],
                         "check the amended contract with the debate skill")

    def test_legacy_reminder_skill_folds_into_do(self):
        legacy = SETTLEMENT.replace(
            "    clarify:\n      next: [succeeded]\n",
            "    clarify:\n      next: [work, succeeded]\n"
        ).replace(
            "        do: check the output contract\n",
            "        do: check the output contract\n        skill: test\n"
            "    work:\n      next: [succeeded]\n      reminder:\n        skill: debate\n")
        self._init_run("old-run", legacy)
        prose = self._current("old-run", "--prose")
        self.assertEqual(prose.returncode, 0, prose.stderr)
        self.assertEqual(prose.stdout.splitlines(),
                         ["STATE    current: clarify",
                          "do: check the output contract Call the test skill."])
        data = self._current_json("old-run")
        self.assertEqual(data["reminder"]["do"],
                         "check the output contract Call the test skill.")
        self.assertNotIn("skill", data["reminder"])
        moved = self._json_task("state", "transition", "old-run", "--dir",
                                str(self.session_dir), "--to", "work", "--reason", "r")
        self.assertEqual(moved.returncode, 0, moved.stderr)
        reminder = json.loads(moved.stdout)["reminder"]
        self.assertEqual(reminder["do"], "Call the debate skill.")
        self.assertNotIn("skill", reminder)

    def test_terminal_node_with_reminder_has_no_next_once_closed(self):
        self._init_run("pitch-run", SETTLEMENT.replace(
            "    succeeded:\n      terminal: true\n",
            "    succeeded:\n      terminal: true\n      reminder:\n        do: report the pitch\n"))
        moved = self._task("state", "transition", "pitch-run", "--dir", str(self.session_dir),
                           "--to", "succeeded", "--reason", "r", "--prose")
        self.assertEqual(moved.returncode, 0, moved.stderr)
        close = (f"{self.prog} session close pitch-run --dir "
                 f"{self.session_dir.resolve()} succeeded")
        self.assertEqual(self._current_json("pitch-run")["next"], close)
        closed = self._json_task("session", "close", "pitch-run", "--dir",
                                 str(self.session_dir), "succeeded")
        self.assertEqual(closed.returncode, 0, closed.stderr)
        data = self._current_json("pitch-run")
        self.assertEqual(data["reminder"]["do"], "report the pitch")
        self.assertNotIn("next", data)
        recalled = json.loads(self._json_task("session", "recall", "pitch-run", "--dir",
                                              str(self.session_dir)).stdout)
        self.assertNotIn("next", recalled["current_node"])

    def test_state_current_refuses_unusable_machine(self):
        self._init_run("no-machine", SETTLEMENT.split("state_machine: |")[0])
        result = self._current("no-machine", "--prose")
        self.assertEqual(result.returncode, 1)
        self.assertIn("no 'state_machine: |' block", result.stderr)
        self._init_run("scalar-node", SETTLEMENT.replace(
            "    clarify:\n      next: [succeeded]\n"
            "      reminder:\n        do: check the output contract\n",
            "    clarify: oops\n"))
        result = self._current("scalar-node", "--prose")
        self.assertEqual(result.returncode, 1)
        self.assertIn("is not a node in this run's state_machine", result.stderr)

    def test_recall_current_node_matches_state_current_on_terminal_node(self):
        self._transition("succeeded")
        close = (f"{self.prog} session close {self.run_id} --dir "
                 f"{self.session_dir.resolve()} succeeded")
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
        self._init_run("no-machine", SETTLEMENT.split("state_machine: |")[0])
        result = self._json_task("session", "recall", "no-machine", "--dir",
                                 str(self.session_dir))
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertIsNone(data["current_node"])
        self.assertIn("task_type: ticket-to-pr", data["settlement"])
        prose = self._task("session", "recall", "no-machine", "--dir",
                           str(self.session_dir), "--prose").stdout
        self.assertIn("-- current node --\n(unavailable: ", prose)

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
        line = result.stderr.splitlines()[0]
        self.assertTrue(line.startswith(first_line), line)
        self.assertNotIn("## closed", self.ledger.read_text())
        argv = shlex.split(line.split(" — run: ", 1)[1])
        self.assertEqual(argv[0], self.prog)
        argv = [str(self.task_bin), *(a if not a.startswith("<") else "r" for a in argv[1:])]
        fixed = subprocess.run(argv, capture_output=True, text=True, check=False, env=_env())
        self.assertEqual(fixed.returncode, 0, fixed.stderr)
        return argv

    def test_close_from_a_non_terminal_names_a_runnable_transition(self):
        for outcome in ("succeeded", "failed"):
            with self.subTest(outcome=outcome):
                self.setUp()
                argv = self._refused_close_fix(
                    outcome, f"close {outcome} requires current state '{outcome}', "
                             f"but it is 'clarify'")
                self.assertEqual(argv[1:3], ["state", "transition"])
                self.assertIn(f"--to {outcome}", " ".join(argv))
                closed = self._session(*self._close_args(outcome), "--prose")
                self.assertEqual(closed.returncode, 0, closed.stderr)

    def test_close_after_the_other_terminal_names_a_runnable_close(self):
        for ended, outcome in (("failed", "succeeded"), ("succeeded", "failed")):
            with self.subTest(ended=ended):
                self.setUp()
                self._transition(ended)
                argv = self._refused_close_fix(
                    outcome, f"close {outcome} refused: the run already ended at "
                             f"'{ended}'")
                self.assertEqual(argv[1:3], ["session", "close"])
                self.assertIn("## closed\n", self.ledger.read_text())
                self.assertIn(f" — {ended}", self.ledger.read_text())

    def test_close_without_a_direct_edge_defers_to_transitions_refusal(self):
        settlement = self.tmp / "indirect.txt"
        settlement.write_text(SETTLEMENT.replace("next: [succeeded]", "next: [review]")
                              .replace("    succeeded:\n",
                                       "    review:\n      next: [succeeded]\n    succeeded:\n"))
        self.run_id = "indirect-run"
        init = self._task("session", "init", self.run_id, "--dir", str(self.session_dir),
                          "--settlement-file", str(settlement))
        self.assertEqual(init.returncode, 0, init.stderr)
        self.ledger = self.session_dir / f"{self.run_id}.md"
        refused = self._session("close", "succeeded", "--prose")
        self.assertIn("has no legal edge to 'succeeded'", refused.stderr.splitlines()[0])
        argv = shlex.split(refused.stderr.splitlines()[0].split(" — run: ", 1)[1])
        argv = [str(self.task_bin), *(a if not a.startswith("<") else "r" for a in argv[1:])]
        fixed = subprocess.run(argv, capture_output=True, text=True, check=False, env=_env())
        self.assertEqual(fixed.returncode, 1, fixed.stderr)
        self.assertIn("legal destinations", fixed.stderr)
        self.assertIn("'review'", fixed.stderr)

    def test_close_from_a_gated_node_defers_to_transitions_refusal(self):
        settlement = self.tmp / "gated.txt"
        settlement.write_text(SETTLEMENT.replace(
            "        do: check the output contract\n",
            "        do: check the output contract\n        leave: the contract holds\n"))
        self.run_id = "gated-run"
        init = self._task("session", "init", self.run_id, "--dir", str(self.session_dir),
                          "--settlement-file", str(settlement))
        self.assertEqual(init.returncode, 0, init.stderr)
        self.ledger = self.session_dir / f"{self.run_id}.md"
        refused = self._session("close", "succeeded", "--prose")
        line = refused.stderr.splitlines()[0]
        self.assertIn("--confirm-leave", line)
        argv = shlex.split(line.split(" — run: ", 1)[1])
        argv = [str(self.task_bin), *(a if not a.startswith("<") else "r" for a in argv[1:])]
        fixed = subprocess.run(argv, capture_output=True, text=True, check=False, env=_env())
        self.assertEqual(fixed.returncode, 1, fixed.stderr)
        self.assertIn("--confirm-leave", fixed.stderr)

    def test_close_without_a_current_line_is_a_malformed_ledger(self):
        text = self.ledger.read_text()
        self.ledger.write_text(text.replace("current: clarify\n", ""))
        result = self._session("close", "succeeded", "--prose")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("'## state' has no 'current: <node>' line", result.stderr)
        self.assertNotIn(" — run: ", result.stderr)
        self.assertNotIn("## closed", self.ledger.read_text())

    def test_close_after_matching_transition_closes(self):
        self._transition("succeeded")
        result = self._session("close", "succeeded", "--prose")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("## closed", self.ledger.read_text())

    # --- refusals, not tracebacks or result objects -----------------------

    def test_diagram_of_invalid_machine_is_a_refusal(self):
        machine = self.tmp / "bad.yaml"
        machine.write_text("name: bad\nnodes:\n  clarify:\n    next: [nowhere]\n")
        prose = self._task("state", "diagram", str(machine), "--prose")
        self.assertEqual(prose.returncode, 1)
        self.assertEqual(prose.stdout, "")
        self.assertIn("refusing to diagram an invalid machine", prose.stderr)
        self._assert_refusal_lines(prose.stderr, "state diagram", "state diagram <machine.yaml>")
        piped = self._json_task("state", "diagram", str(machine))
        self.assertEqual(piped.returncode, 1)
        self.assertEqual(piped.stdout, "")
        error = json.loads(piped.stderr)["error"]
        self.assertEqual(error["command"], "state diagram")
        self.assertTrue(error["problems"][0]["items"])

    def test_unreadable_inputs_are_refused_without_traceback(self):
        missing = self._task("session", "init", "fresh-run", "--dir", str(self.session_dir),
                             "--settlement-file", str(self.tmp / "missing.txt"), "--prose")
        self.assertEqual(missing.returncode, 1)
        self.assertNotIn("Traceback", missing.stderr)
        self.assertIn("cannot init", missing.stderr)
        self.assertIn("example: ", missing.stderr)
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
        binary = self.tmp / "binary.yaml"
        binary.write_bytes(b"\xff\xfe\x00")
        invalid = self._task("state", "validate", str(binary), "--prose")
        self.assertEqual(invalid.returncode, 1)
        self.assertNotIn("Traceback", invalid.stderr)
        self.assertIn("cannot read", invalid.stdout)

    def test_module_entry_point_renders_refusals(self):
        result = subprocess.run(
            ["uv", "run", "--project", str(self.task_bin.parents[1]), "python", "-m",
             "engine.session", "record-decision", self.run_id, "--dir", str(self.session_dir),
             "--mode", "debate", "--summary", "round 1, party 'main-agent': x", "--prose"],
            capture_output=True, text=True, check=False, env=_env())
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("record-decision refused", result.stderr)
        self.assertIn("example: ", result.stderr)

    def test_examples_parse_and_cover_every_leaf(self):
        result = subprocess.run(
            ["uv", "run", "--project", str(PLUGIN_DIR), "python", "-c", PROBE],
            capture_output=True, text=True, check=False, env=_env())
        self.assertEqual(result.returncode, 0, result.stderr)
        probe = json.loads(result.stdout)
        self.assertEqual(probe["examples"], probe["leaves"])
        self.assertEqual(probe["bad"], {})
        self.assertEqual(tuple(probe["frequent"]), self.frequent)


if __name__ == "__main__":
    unittest.main()
