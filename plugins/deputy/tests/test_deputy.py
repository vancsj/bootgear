"""The deputy's ledger commands against a temporary deputy root.

Each run goes through the gear route to memory-ledger; nothing here touches a real ledger.
"""
from __future__ import annotations

import io
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

    def record(self, claim: str = CLAIM, question: str = QUESTION) -> tuple[int, str, str]:
        session = self.base / "session.md"
        session.write_text(f"decision: {claim}\n", encoding="utf-8")
        return self.run_deputy("record", "--question", question, "--claim", claim,
                               "--because", WHY, "--options", "uv or pip", "--stakes", "low",
                               "--session-ledger", str(session))

    def test_candidates_says_the_resolver_may_hide_weaker_matches(self) -> None:
        self.record()
        code, out, _ = self.run_deputy("candidates", QUESTION)
        self.assertEqual(code, 0)
        self.assertIn("weaker matches may be hidden", out)

    def test_record_does_not_run_shell_text_from_the_answer(self) -> None:
        target = self.base / "pwned"
        self.record(claim=f'x"; touch {target}; echo "')
        self.assertFalse(target.exists())

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
