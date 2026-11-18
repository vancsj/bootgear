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

import deputy
from bootgear_cli import runtime

QUESTION = "Should new scripts run with uv?"
CLAIM = "Scripts run with uv run --script"
WHY = "uv pins dependencies per script"
FIXED_BECAUSE = "The user confirmed this canonical decision."


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

    def record(self, claim: str = CLAIM, question: str = QUESTION) -> tuple[int, str, str]:
        return self.run_deputy("record", "--question", question, "--claim", claim,
                               "--confirmed-by-user")

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

    def test_main_resolves_relative_roots_from_caller_cwd(self) -> None:
        caller_cwd = self.base / "caller"
        caller_cwd.mkdir()
        expected_root = caller_cwd / "relative-deputy"
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
                    "--confirmed-by-user",
                ])
                self.assertEqual(code, 0)
                self.assertEqual(record.call_args.args[0], expected_root)

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


    def test_record_refuses_an_entry_that_breaks_the_standards(self) -> None:
        code, _, err = self.record(question="Should I run scripts with uv?")
        self.assertEqual(code, 2)
        self.assertIn("REFUSED", err)
        self.assertEqual(list(self.root.rglob("*.md")), [])


    def test_record_refuses_a_deputy_root_with_a_remote(self) -> None:
        subprocess.run(["git", "-C", str(self.root), "remote", "add", "origin",
                        "https://example.invalid/x.git"], check=True)
        code, _, err = self.record()
        self.assertNotEqual(code, 0)
        self.assertIn("local only", err)
        self.assertEqual(list(self.root.rglob("*.md")), [])

    def test_assert_refuses_without_the_user_confirmation(self) -> None:
        self.assertEqual(self.record()[0], 0)
        slug = next(p for p in self.root.rglob("*.md")).relative_to(self.root).with_suffix("")
        code, _, err = self.run_deputy("assert", str(slug), "a1", "--why", "the user said so")
        self.assertEqual(code, 2)
        self.assertIn("--confirmed-by-user", err)


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
