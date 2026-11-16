"""The deputy's ledger commands against a temporary deputy root.

Each run goes through the gear route to memory-ledger; nothing here touches a real ledger.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
REPO = PLUGIN.parents[1]
sys.path.insert(0, str(PLUGIN / "scripts"))
# Subprocess ledger calls sign with this Claude id when the host did not set one, also in a Codex shell.
os.environ.setdefault("CLAUDE_CODE_SESSION_ID", "deputy-test-session")
os.environ["BOOTGEAR_HOST"] = "claude"

import deputy
from bootgear_cli import clikit, runtime

SESSION_VARIABLES = ("BOOTGEAR_SESSION_ID", "CLAUDE_CODE_SESSION_ID", "CODEX_SESSION_ID")
QUESTION = "Should new scripts run with uv?"
CLAIM = "Scripts run with uv run --script"
WHY = "uv pins dependencies per script"
FIXED_BECAUSE = "The user confirmed this canonical decision."


def engine_line(question: str, claim: str) -> str:
    return (f"- 2026-11-15 00:00 [solo] Canonical question: {question} | "
            f"Canonical decision: {claim}\n")


def git_root(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(path), "init", "-q"], check=True)
    return path


class DeputyTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.root = git_root(self.base / "deputy")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def run_deputy(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = deputy.main(["--deputy-root", str(self.root), *argv])
        return code, out.getvalue(), err.getvalue()

    def record(self, claim: str = CLAIM, question: str = QUESTION,
               session: str = "session.md") -> tuple[int, str, str]:
        session_file = self.base / session
        session_file.write_text(engine_line(question, claim), encoding="utf-8")
        return self.run_deputy("record", "--question", question, "--claim", claim,
                               "--session-ledger", str(session_file), "--confirmed-by-user")

    def test_identical_answer_from_a_new_session_adds_a_vote(self) -> None:
        self.assertEqual(self.record(session="first.md")[0], 0)
        code, out, err = self.record(session="second.md")
        self.assertEqual(code, 0, err)
        self.assertIn("VOTED decisions/", out)
        self.assertIn("n=2", out)
        self.assertEqual(len(list(self.root.rglob("*.md"))), 1)

    def test_similar_question_with_the_same_answer_adds_a_vote(self) -> None:
        self.assertEqual(self.record()[0], 0)
        code, out, err = self.record(question="Should scripts run with uv?", session="second.md")
        self.assertEqual(code, 0, err)
        self.assertRegex(out, r"VOTED decisions/\S+ a1 n=2")
        self.assertEqual(len(list(self.root.rglob("*.md"))), 1)

    def test_similar_question_with_a_different_answer_writes_a_new_entry(self) -> None:
        self.assertEqual(self.record()[0], 0)
        code, out, err = self.record(claim="Scripts run with pip",
                                     question="Should scripts run with pip?", session="second.md")
        self.assertEqual(code, 0, err)
        self.assertIn("NEW decisions/", out)
        self.assertEqual(len(list(self.root.rglob("*.md"))), 2)

    def test_candidates_lists_every_similar_entry_and_no_hidden_note(self) -> None:
        questions = [QUESTION, "Should new scripts pin dependencies with uv?",
                     "Should scripts run with pip?", "Should new scripts be shell?",
                     "Should the repo lock with uv?", "Should scripts use a venv?"]
        for i, question in enumerate(questions):
            self.assertEqual(self.record(claim=f"{CLAIM} variant {i}", question=question)[0], 0)
        code, out, err = self.run_deputy("candidates", QUESTION)
        self.assertEqual(code, 0, err)
        self.assertEqual(out.count("CANDIDATE decisions/"), len(questions), out)
        self.assertNotIn("CUT", out)
        self.assertNotIn("NOTE", out)

    def test_record_does_not_run_shell_text_from_the_answer(self) -> None:
        target = self.base / "pwned"
        self.record(claim=f'x"; touch {target}; echo "')
        self.assertFalse(target.exists())

    def test_matching_slugs_sorts_by_score_and_puts_the_exact_slug_first(self) -> None:
        printed = json.dumps({"exact": None, "mint": "q", "candidates": [
            {"slug": "decisions/weak", "score": 0.2},
            {"slug": "decisions/strong", "score": 0.9},
            {"slug": "other/assertion", "score": 0.85},
        ]})
        fake = subprocess.CompletedProcess([], 0, stdout=printed, stderr="")
        with unittest.mock.patch.object(deputy, "ledger", return_value=fake):
            self.assertEqual(deputy.matching_slugs(self.root, "q"),
                             ["decisions/strong", "other/assertion", "decisions/weak"])
            exact = json.dumps({"exact": "decisions/strong", "mint": "q", "candidates": [
                {"slug": "decisions/weak", "score": 0.2}]})
            fake.stdout = exact
            self.assertEqual(deputy.matching_slugs(self.root, "q"),
                             ["decisions/strong", "decisions/weak"])

    def test_candidates_escalates_when_the_root_is_absent(self) -> None:
        shutil.rmtree(self.root)
        code, _, _ = self.run_deputy("candidates", QUESTION)
        self.assertEqual(code, 0)

    def test_main_resolves_relative_roots_and_session_files_from_caller_cwd(self) -> None:
        caller_cwd = self.base / "caller"
        caller_cwd.mkdir()
        expected_root = caller_cwd / "relative-deputy"
        expected_session = caller_cwd / "sessions" / "run.md"
        with unittest.mock.patch.dict(os.environ, {"GEAR_CALLER_CWD": str(caller_cwd)}):
            with unittest.mock.patch.object(deputy, "candidates", return_value=0) as candidates:
                code = deputy.main([
                    "--deputy-root", "relative-deputy", "candidates", QUESTION,
                ])
                self.assertEqual(code, 0)
                self.assertEqual(candidates.call_args.args[0], expected_root)
            with unittest.mock.patch.object(deputy, "record", return_value=0) as record:
                code = deputy.main([
                    "--deputy-root", "relative-deputy", "record",
                    "--question", QUESTION, "--claim", CLAIM,
                    "--session-ledger", "sessions/run.md", "--confirmed-by-user",
                ])
                self.assertEqual(code, 0)
                self.assertEqual(record.call_args.args[0], expected_root)
                self.assertEqual(record.call_args.args[3], expected_session)

    def test_candidates_prints_the_matching_entry_in_full(self) -> None:
        self.assertEqual(self.record()[0], 0)
        code, out, err = self.run_deputy("candidates", QUESTION)
        self.assertEqual(code, 0, err)
        self.assertIn("CANDIDATE decisions/", out)
        self.assertIn(CLAIM, out)
        self.assertIn(FIXED_BECAUSE, out)
        self.assertNotIn(WHY, out)
        self.assertNotIn("options", out)
        self.assertNotIn("stakes", out)

    def test_identical_answer_writes_nothing(self) -> None:
        self.assertEqual(self.record()[0], 0)
        code, out, _ = self.record()
        self.assertEqual(code, 0)
        self.assertIn("UNCHANGED", out)
        self.assertEqual(len(list(self.root.rglob("*.md"))), 1)

    def test_retry_after_sign_failure_finishes_sign_and_save(self) -> None:
        session = self.base / "session.md"
        session.write_text(engine_line(QUESTION, CLAIM), encoding="utf-8")
        votes = 0
        signs = 0
        saves = 0

        def ledger(_root: Path, *args: str, signer: tuple[str, ...] = ()) -> subprocess.CompletedProcess:
            nonlocal votes, signs, saves
            command = args[0]
            if command == "vote":
                votes += 1
                output = ("VOTED decisions/canonical a1 n=1" if votes == 1
                          else "UNCHANGED decisions/canonical a1")
                return subprocess.CompletedProcess(args, 0, output, "")
            if command == "sign":
                signs += 1
                return subprocess.CompletedProcess(args, 1 if signs == 1 else 0,
                                                    "sign failed" if signs == 1 else "SIGNED", "")
            if command == "save":
                saves += 1
                return subprocess.CompletedProcess(args, 0, "SAVED", "")
            self.fail(f"unexpected ledger command: {command}")

        with unittest.mock.patch.object(deputy, "ledger", side_effect=ledger):
            with redirect_stderr(io.StringIO()):
                first = deputy.record(self.root, QUESTION, CLAIM, session, True)
            with redirect_stdout(io.StringIO()):
                retry = deputy.record(self.root, QUESTION, CLAIM, session, True)

        self.assertEqual(first, 1)
        self.assertEqual(retry, 0)
        self.assertEqual(votes, 2)
        self.assertEqual(signs, 2)
        self.assertEqual(saves, 1)

    def test_repeat_answer_in_the_same_session_adds_a_vote(self) -> None:
        self.assertEqual(self.record()[0], 0)
        session = self.base / "session.md"
        session.write_text(engine_line(QUESTION, CLAIM) * 2, encoding="utf-8")
        argv = ["record", "--question", QUESTION, "--claim", CLAIM,
                "--session-ledger", str(session), "--confirmed-by-user"]
        code, out, err = self.run_deputy(*argv)
        self.assertEqual(code, 0, err)
        self.assertIn("VOTED decisions/", out)
        self.assertIn("n=2", out)
        code, out, err = self.run_deputy(*argv)
        self.assertEqual(code, 0, err)
        self.assertIn("UNCHANGED", out)

    def test_record_refuses_an_answer_missing_from_the_session_ledger(self) -> None:
        session = self.base / "session.md"
        session.write_text("decision: something else\n", encoding="utf-8")
        code, _, err = self.run_deputy("record", "--question", QUESTION, "--claim", CLAIM,
                                       "--session-ledger", str(session), "--confirmed-by-user")
        self.assertEqual(code, 2)
        self.assertIn("does not contain the canonical record", err)
        self.assertEqual(list(self.root.rglob("*.md")), [])

    def test_record_refuses_a_line_with_only_the_decision_substring(self) -> None:
        session = self.base / "session.md"
        session.write_text(
            f"- 2026-11-15 00:00 [solo] Unrelated text mentions {CLAIM}\n", encoding="utf-8")
        code, _, err = self.run_deputy(
            "record", "--question", QUESTION, "--claim", CLAIM,
            "--session-ledger", str(session), "--confirmed-by-user")
        self.assertEqual(code, 2)
        self.assertIn("does not contain the canonical record", err)
        self.assertEqual(list(self.root.rglob("*.md")), [])

    def test_stored_evidence_requires_the_exact_engine_summary(self) -> None:
        session = self.base / "session.md"
        session.write_text(engine_line(QUESTION, CLAIM), encoding="utf-8")
        evidence_commands: list[str] = []

        def ledger(_root: Path, *args: str, signer: tuple[str, ...] = ()) -> subprocess.CompletedProcess:
            command = args[0]
            if command == "vote":
                evidence_commands.append(args[args.index("--evidence") + 1])
                return subprocess.CompletedProcess(args, 0, "VOTED decisions/canonical a1 n=1", "")
            if command == "sign":
                return subprocess.CompletedProcess(args, 0, "SIGNED", "")
            if command == "save":
                return subprocess.CompletedProcess(args, 0, "SAVED", "")
            self.fail(f"unexpected ledger command: {command}")

        with unittest.mock.patch.object(deputy, "ledger", side_effect=ledger), \
                redirect_stdout(io.StringIO()):
            code = deputy.record(self.root, QUESTION, CLAIM, session, True)
        self.assertEqual(code, 0)
        evidence = evidence_commands[0]

        matching = subprocess.run(evidence, shell=True, capture_output=True, text=True, check=False)
        self.assertEqual(matching.returncode, 0, matching.stderr)

        summary = f"Canonical question: {QUESTION} | Canonical decision: {CLAIM}"
        session.write_text(
            f"- 2026-11-15 00:00 [solo] Unrelated prefix {summary} suffix\n", encoding="utf-8")
        partial = subprocess.run(evidence, shell=True, capture_output=True, text=True, check=False)
        self.assertNotEqual(partial.returncode, 0, partial.stdout + partial.stderr)

    def test_record_refuses_without_user_confirmation(self) -> None:
        session = self.base / "session.md"
        session.write_text(engine_line(QUESTION, CLAIM), encoding="utf-8")
        code, _, err = self.run_deputy(
            "record", "--question", QUESTION, "--claim", CLAIM, "--session-ledger", str(session))
        self.assertEqual(code, 2)
        self.assertIn("example: record --question", err)
        self.assertIn("commands: candidates, record, assert", err)
        self.assertIn("REFUSED", err)
        self.assertEqual(list(self.root.rglob("*.md")), [])

    def test_record_rejects_legacy_context_flags(self) -> None:
        session = self.base / "session.md"
        session.write_text(f"decision: {CLAIM}\n", encoding="utf-8")
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), self.assertRaises(SystemExit) as exit_call:
            deputy.main([
                "--deputy-root", str(self.root), "record", "--question", QUESTION,
                "--claim", CLAIM, "--session-ledger", str(session), "--confirmed-by-user",
                "--because", WHY, "--options", "uv or pip", "--stakes", "low",
            ])
        self.assertEqual(exit_call.exception.code, 2)
        self.assertIn("unrecognized arguments", err.getvalue())
        self.assertEqual(list(self.root.rglob("*.md")), [])

    def test_different_answer_to_the_same_question_adds_a_rival_to_the_entry(self) -> None:
        self.assertEqual(self.record()[0], 0)
        code, out, err = self.record(claim="Scripts run with pip")
        self.assertEqual(code, 0, err)
        self.assertIn("RIVAL decisions/", out)
        entry, = self.root.rglob("*.md")
        text = entry.read_text(encoding="utf-8")
        self.assertIn("Scripts run with pip", text)
        self.assertIn("## a2", text)

    def test_new_entry_is_named_by_the_minted_slug(self) -> None:
        question = ("Should new scripts run with uv when the team builds them on every "
                    "laptop?")
        code, out, err = self.record(question=question)
        self.assertEqual(code, 0, err)
        slug = out.split()[1].removeprefix("decisions/")
        self.assertLessEqual(len(slug.split("-")), 4, slug)
        self.assertNotIn("?", slug)

    def test_record_refuses_an_entry_that_breaks_the_standards(self) -> None:
        code, _, err = self.record(question="Should I run scripts with uv?")
        self.assertEqual(code, 2)
        self.assertIn("REFUSED", err)
        self.assertEqual(list(self.root.rglob("*.md")), [])

    def test_record_never_passes_anyway_to_memory_ledger(self) -> None:
        with unittest.mock.patch.object(deputy, "ledger", side_effect=deputy.ledger) as spy:
            self.assertEqual(self.record()[0], 0)
            self.assertEqual(self.record(claim="Scripts run with pip",
                                         question="Should scripts run with pip?",
                                         session="second.md")[0], 0)
        self.assertTrue(spy.call_args_list)
        for call in spy.call_args_list:
            self.assertNotIn("--anyway", call.args)

    def test_record_refuses_a_deputy_root_with_a_remote(self) -> None:
        subprocess.run(["git", "-C", str(self.root), "remote", "add", "origin",
                        "https://example.invalid/x.git"], check=True)
        code, _, err = self.record()
        self.assertEqual(code, 2)
        self.assertIn("local only", err)
        self.assertEqual(list(self.root.rglob("*.md")), [])

    def test_assert_refuses_without_the_user_confirmation(self) -> None:
        self.assertEqual(self.record()[0], 0)
        slug = next(p for p in self.root.rglob("*.md")).relative_to(self.root).with_suffix("")
        code, _, err = self.run_deputy("assert", str(slug), "a1", "--why", "the user said so")
        self.assertEqual(code, 2)
        self.assertIn("--confirmed-by-user", err)

    def test_assert_with_the_confirmation_pins_the_answer(self) -> None:
        self.assertEqual(self.record()[0], 0)
        slug = next(p for p in self.root.rglob("*.md")).relative_to(self.root).with_suffix("")
        code, out, err = self.run_deputy("assert", str(slug), "a1", "--why", "the user said so",
                                         "--confirmed-by-user")
        self.assertEqual(code, 0, err)
        self.assertIn("ASSERTED", out)



    def record_as(self, session_id: str, claim: str = CLAIM) -> tuple[int, str, str]:
        session = self.base / f"session-{session_id}.md"
        session.write_text(engine_line(QUESTION, claim), encoding="utf-8")
        return self.run_deputy("record", "--question", QUESTION, "--claim", claim,
                               "--session-ledger", str(session), "--confirmed-by-user", "--host", "codex",
                               "--session-id", session_id)

    def test_a_vote_from_another_session_signs_the_answer(self) -> None:
        self.assertEqual(self.record_as("a")[0], 0)
        code, out, err = self.record_as("b")
        self.assertEqual(code, 0, err)
        self.assertIn("VOTED decisions/", out)
        entry, = self.root.rglob("*.md")
        signed = [line for line in entry.read_text(encoding="utf-8").splitlines()
                  if "codex:b" in line]
        self.assertTrue(signed, "no signature from the second session")
        self.assertFalse(any("(author)" in line for line in signed))

    def test_two_independent_sessions_read_well_confirmed(self) -> None:
        for session_id in ("a", "b", "c"):
            self.assertEqual(self.record_as(session_id)[0], 0)
        _, listing, _ = self.run_deputy("candidates", QUESTION)
        self.assertIn("[well-confirmed]", listing)

    def record_in_environment(self, env: dict[str, str], *extra: str) -> tuple[int, str, str, list]:
        """Record with only `env` as the session context; return the ledger calls too."""
        session = self.base / "session.md"
        session.write_text(engine_line(QUESTION, CLAIM), encoding="utf-8")
        with unittest.mock.patch.dict(os.environ), \
                unittest.mock.patch.object(deputy, "ledger", side_effect=deputy.ledger) as spy:
            for name in ("BOOTGEAR_HOST", *SESSION_VARIABLES):
                os.environ.pop(name, None)
            os.environ.update(env)
            code, out, err = self.run_deputy(
                "record", "--question", QUESTION, "--claim", CLAIM,
                "--session-ledger", str(session),
                "--confirmed-by-user",
                *extra)
        return code, out, err, spy.call_args_list

    def test_codex_record_reads_codex_session_id(self) -> None:
        code, _, err, calls = self.record_in_environment({"CODEX_SESSION_ID": "codex-env"},
                                                         "--host", "codex")
        self.assertEqual(code, 0, err)
        self.assertTrue(calls)
        for call in calls:
            self.assertEqual(call.kwargs["signer"], ("--host", "codex", "--session-id", "codex-env"))

    def test_codex_record_without_session_names_the_override(self) -> None:
        code, _, err, calls = self.record_in_environment({}, "--host", "codex")
        self.assertEqual(code, 2)
        self.assertEqual(err.strip(), "REFUSED " + clikit.missing_session("--session-id"))
        self.assertEqual(calls, [])

    def test_declared_host_picks_its_session_variable(self) -> None:
        for host in ("codex", "claude"):
            with self.subTest(host=host):
                code, _, err, calls = self.record_in_environment(
                    {"BOOTGEAR_HOST": host, "CLAUDE_CODE_SESSION_ID": "claude-env",
                     "CODEX_SESSION_ID": "codex-env"})
                self.assertEqual(code, 0, err)
                self.assertTrue(calls)
                for call in calls:
                    self.assertEqual(call.kwargs["signer"],
                                     ("--host", host, "--session-id", f"{host}-env"))

    def test_explicit_host_picks_its_session_variable(self) -> None:
        both = {"CLAUDE_CODE_SESSION_ID": "claude-env", "CODEX_SESSION_ID": "codex-env"}
        for host, ancestor in (("codex", "claude"), ("claude", "codex")):
            with self.subTest(host=host), unittest.mock.patch.object(
                    clikit, "_ancestor_host", return_value=ancestor):
                code, _, err, calls = self.record_in_environment(both, "--host", host)
                self.assertEqual(code, 0, err)
                self.assertTrue(calls)
                for call in calls:
                    self.assertEqual(call.kwargs["signer"],
                                     ("--host", host, "--session-id", f"{host}-env"))

    def test_record_infers_codex_from_the_environment(self) -> None:
        code, _, err, calls = self.record_in_environment({"CODEX_SESSION_ID": "codex-env"})
        self.assertEqual(code, 0, err)
        self.assertTrue(calls)
        for call in calls:
            self.assertEqual(call.kwargs["signer"], ("--host", "codex", "--session-id", "codex-env"))


class StandardsTest(unittest.TestCase):
    """The mechanical part of the Q&A standards, checked by `entry_problems`."""

    def problems(self, question: str = QUESTION, claim: str = CLAIM, because: str = WHY) -> list[str]:
        return deputy.entry_problems(question, claim, because)

    def test_a_general_entry_passes(self) -> None:
        self.assertEqual(self.problems(), [])

    def test_a_pronoun_in_the_question_is_refused(self) -> None:
        for question in ("Should I run scripts with uv?", "Should you run scripts with uv?",
                         "Should it run scripts with uv?", "Should its scripts run with uv?"):
            with self.subTest(question=question):
                self.assertTrue(self.problems(question=question))

    def test_a_pronoun_in_the_answer_is_refused(self) -> None:
        for claim in ("I run scripts with uv", "We run scripts with uv",
                      "She runs scripts with uv", "They run scripts with uv"):
            with self.subTest(claim=claim):
                self.assertTrue(self.problems(claim=claim))

    def test_options_in_the_question_are_refused(self) -> None:
        for question in ("Should scripts run with uv or pip?", "Should scripts run with (a) uv?",
                         "Should scripts run with a) uv?", "Should scripts run with uv? A: yes",
                         "Should scripts run with either uv?"):
            with self.subTest(question=question):
                self.assertTrue(self.problems(question=question))

    def test_a_question_over_twenty_words_is_refused(self) -> None:
        question = "Should " + " ".join(["scripts"] * 20) + " run with uv?"
        self.assertTrue(self.problems(question=question))

    def test_a_bare_letter_or_number_answer_is_refused(self) -> None:
        for claim in ("A", "b", "2", "(c)"):
            with self.subTest(claim=claim):
                self.assertTrue(self.problems(claim=claim))

    def test_a_reason_of_two_sentences_is_refused(self) -> None:
        self.assertTrue(self.problems(because="uv pins dependencies. Pip does not"))

    def test_a_reason_with_a_semicolon_is_refused(self) -> None:
        self.assertTrue(self.problems(because="uv pins dependencies; pip does not"))


class InstalledCopyTest(unittest.TestCase):
    """A copied deputy command uses the shared Gear CLI source."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.script = self.base / "cache" / "deputy" / "0.1.0" / "scripts" / "deputy.py"
        self.script.parent.mkdir(parents=True)
        shutil.copy2(PLUGIN / "scripts" / "deputy.py", self.script)
        self.root = git_root(self.base / "deputy-root")
        self.home = self.base / "home"
        self.home.mkdir()
        self.data = self.base / "data"
        runtimes = self.data / "bootgear" / "runtimes"
        runtimes.parent.mkdir(parents=True)
        runtimes.symlink_to(runtime.environment_path().parent, target_is_directory=True)
        self.session = self.base / "session.md"
        self.session.write_text(engine_line(QUESTION, CLAIM), encoding="utf-8")
        env = {key: value for key, value in os.environ.items()
               if key not in ("BOOTGEAR_HOST", "BOOTGEAR_PROG", "GEAR_PLUGIN", "VIRTUAL_ENV")}
        paths = [str(REPO / "plugins" / "cli" / "src")]
        if env.get("PYTHONPATH"):
            paths.append(env["PYTHONPATH"])
        self.env = {**env, "HOME": str(self.home), "XDG_DATA_HOME": str(self.data),
                    "PYTHONPATH": os.pathsep.join(paths),
                    "BOOTGEAR_HOST": "claude", "GEAR_PLUGIN": "deputy"}

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def run_copy(self, *argv: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(self.script), "--deputy-root", str(self.root), *argv],
                              capture_output=True, text=True, check=False, env=self.env, timeout=60)

    def record_argv(self, *extra: str) -> list[str]:
        return ["record", "--question", QUESTION, "--claim", CLAIM, "--session-ledger",
                str(self.session), "--confirmed-by-user", *extra]

    def test_copy_routes_queries_to_the_registered_ledger(self) -> None:
        result = self.run_copy("candidates", QUESTION)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "NO-CANDIDATES")

    def test_ledger_command_uses_registered_gear_before_path(self) -> None:
        with unittest.mock.patch.object(deputy, "resolve_command",
                                        return_value=["/gear", "--host", "claude",
                                                      "memory-ledger", "ledger"]), \
                unittest.mock.patch("shutil.which", return_value="/path/ledger") as which:
            self.assertEqual(deputy.ledger_command(),
                             ["/gear", "--host", "claude", "memory-ledger", "ledger"])
            which.assert_not_called()

    def test_ledger_command_does_not_fall_back_to_path_program(self) -> None:
        with unittest.mock.patch.object(deputy, "resolve_command", return_value=None), \
                unittest.mock.patch("shutil.which", return_value="/path/ledger") as which:
            with self.assertRaisesRegex(deputy.LedgerMissing, "memory-ledger not found"):
                deputy.ledger_command()
            which.assert_not_called()

    def test_ledger_command_reports_when_no_route_or_program_exists(self) -> None:
        with (unittest.mock.patch.object(deputy, "resolve_command", return_value=None),
              unittest.mock.patch("shutil.which", return_value=None) as which,
              self.assertRaises(deputy.LedgerMissing)):
            deputy.ledger_command()
            which.assert_not_called()

    def test_codex_record_writes_through_the_real_memory_ledger(self) -> None:
        result = self.run_copy(*self.record_argv("--host", "codex", "--session-id", "abc"))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertRegex(result.stdout.strip().splitlines()[-1], r"^(NEW|VOTED) decisions/")
        entry, = self.root.rglob("*.md")
        self.assertIn("codex:abc", entry.read_text(encoding="utf-8"))
