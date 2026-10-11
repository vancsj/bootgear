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
sys.path.insert(0, str(PLUGIN / "scripts"))
# Subprocess ledger calls sign with this id when the host did not set one.
os.environ.setdefault("CLAUDE_CODE_SESSION_ID", "deputy-test-session")

import deputy  # noqa: E402

QUESTION = "Should new scripts run with uv?"
CLAIM = "Scripts run with uv run --script"
WHY = "uv pins dependencies per script"


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
        session_file.write_text(f"decision: {claim}\n", encoding="utf-8")
        return self.run_deputy("record", "--question", question, "--claim", claim,
                               "--because", WHY, "--options", "uv or pip", "--stakes", "low",
                               "--session-ledger", str(session_file))

    def test_identical_answer_from_a_new_session_adds_a_vote(self) -> None:
        self.assertEqual(self.record(session="first.md")[0], 0)
        code, out, err = self.record(session="second.md")
        self.assertEqual(code, 0, err)
        self.assertIn("VOTED decisions/", out)
        self.assertIn("n=2", out)
        self.assertEqual(len(list(self.root.rglob("*.md"))), 1)

    def test_similar_question_with_the_same_answer_adds_a_vote(self) -> None:
        self.assertEqual(self.record()[0], 0)
        code, out, err = self.record(question="Should I run scripts with uv?", session="second.md")
        self.assertEqual(code, 0, err)
        self.assertIn("VOTED decisions/should-new-scripts-run-with-uv a1 n=2", out)
        self.assertEqual(len(list(self.root.rglob("*.md"))), 1)

    def test_similar_question_with_a_different_answer_writes_a_new_entry(self) -> None:
        self.assertEqual(self.record()[0], 0)
        code, out, err = self.record(claim="Scripts run with pip",
                                     question="Should I run scripts with uv?", session="second.md")
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
        code, out, _ = self.run_deputy("candidates", QUESTION)
        self.assertEqual(code, 0)
        self.assertIn("ESCALATE deputy-root-absent", out)

    def test_candidates_fails_loudly_when_gear_is_not_found(self) -> None:
        self.record()
        missing = self.base / "no-such-cli" / "gear.py"
        with unittest.mock.patch.object(deputy, "GEAR", missing):
            with self.assertRaises(SystemExit) as cm:
                self.run_deputy("candidates", QUESTION)
        self.assertIn("gear.py not found", str(cm.exception))

    def test_candidates_prints_the_matching_entry_in_full(self) -> None:
        self.assertEqual(self.record()[0], 0)
        code, out, err = self.run_deputy("candidates", QUESTION)
        self.assertEqual(code, 0, err)
        self.assertIn("CANDIDATE decisions/", out)
        self.assertIn(CLAIM, out)
        self.assertIn(WHY, out)
        self.assertIn("Context: options uv or pip; stakes low.", out)

    def test_identical_answer_writes_nothing(self) -> None:
        self.assertEqual(self.record()[0], 0)
        code, out, _ = self.record()
        self.assertEqual(code, 0)
        self.assertIn("UNCHANGED", out)
        self.assertEqual(len(list(self.root.rglob("*.md"))), 1)

    def test_repeat_answer_in_the_same_session_adds_a_vote(self) -> None:
        self.assertEqual(self.record()[0], 0)
        session = self.base / "session.md"
        session.write_text(f"decision: {CLAIM}\ndecision: {CLAIM}\n", encoding="utf-8")
        argv = ["record", "--question", QUESTION, "--claim", CLAIM, "--because", WHY,
                "--options", "uv or pip", "--stakes", "low", "--session-ledger", str(session)]
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
                                       "--because", WHY, "--options", "uv or pip",
                                       "--stakes", "low", "--session-ledger", str(session))
        self.assertEqual(code, 2)
        self.assertIn("does not contain the answer", err)
        self.assertEqual(list(self.root.rglob("*.md")), [])

    def test_different_answer_writes_a_newer_entry_beside_the_old_one(self) -> None:
        self.assertEqual(self.record()[0], 0)
        code, out, err = self.record(claim="Scripts run with pip")
        self.assertEqual(code, 0, err)
        self.assertIn("NEW decisions/", out)
        self.assertEqual(len(list(self.root.rglob("*.md"))), 2)
        _, listing, _ = self.run_deputy("candidates", QUESTION)
        self.assertIn("Newer than decisions/", listing)

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


if __name__ == "__main__":
    unittest.main()
