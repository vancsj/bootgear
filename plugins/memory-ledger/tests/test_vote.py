"""`vote` and `show --json`: a same-claim answer on a similar question gains checks, nothing else.

Every run is a subprocess against temp ledger roots; nothing here touches a real ledger.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
LEDGER = PLUGIN / "scripts" / "ledger.py"
# `new` signs with this id when the host did not set one.
os.environ.setdefault("CLAUDE_CODE_SESSION_ID", "vote-test-session")

QUESTION = "Should new scripts run with uv?"
CLAIM = "Scripts run with uv run --script"


class VoteTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.roots = []
        for name in ("shared", "local", "deputy"):
            root = base / name
            root.mkdir()
            subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
            self.roots.append(str(root))
        r = self.ledger("new", "decisions/scripts-uv", "--deputy", "--q", QUESTION,
                        "--claim", CLAIM, "--because", "Because: test. Context: none.",
                        "--evidence", "true")
        self.assertEqual(r.returncode, 0, r.stderr)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def ledger(self, *args: str) -> subprocess.CompletedProcess:
        shared, local, deputy = self.roots
        return subprocess.run([sys.executable, str(LEDGER), "--root", shared,
                               "--local-root", local, "--deputy-root", deputy, *args],
                              capture_output=True, text=True)

    def vote(self, question: str, claim: str, check: str) -> subprocess.CompletedProcess:
        return self.ledger("vote", "--question", question, "--claim", claim,
                           "--evidence", check, "--only", "deputy")

    def show_json(self) -> dict:
        r = self.ledger("show", "decisions/scripts-uv", "--only", "deputy", "--data")
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def test_resolve_data_names_the_exact_slug_or_scored_candidates(self) -> None:
        exact = json.loads(self.ledger("resolve", "decisions/scripts-uv", "--data",
                                       "--only", "deputy").stdout)
        self.assertEqual(exact["exact"], "decisions/scripts-uv")
        found = json.loads(self.ledger("resolve", "Should I run scripts with uv?", "--data",
                                       "--only", "deputy").stdout)
        self.assertIsNone(found["exact"])
        self.assertEqual(found["candidates"][0]["slug"], "decisions/scripts-uv")
        scores = [row["score"] for row in found["candidates"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_show_json_reports_the_answer_and_its_checks(self) -> None:
        data = self.show_json()
        self.assertEqual(data["question"], QUESTION)
        [answer] = data["answers"]
        self.assertEqual(answer["aid"], "a1")
        self.assertEqual(answer["claim"], CLAIM)
        self.assertEqual(answer["evidence"], ["true"])

    def test_same_claim_on_a_similar_question_adds_a_vote(self) -> None:
        r = self.vote("Should I run scripts with uv?", CLAIM, "test -n a")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("VOTED decisions/scripts-uv a1 n=2", r.stdout)
        self.assertEqual(self.show_json()["answers"][0]["evidence"], ["true", "test -n a"])

    def test_same_check_twice_is_unchanged(self) -> None:
        self.assertEqual(self.vote(QUESTION, CLAIM, "test -n b").returncode, 0)
        r = self.vote(QUESTION, CLAIM, "test -n b")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("UNCHANGED decisions/scripts-uv a1", r.stdout)
        self.assertEqual(self.show_json()["answers"][0]["evidence"], ["true", "test -n b"])

    def test_different_claim_gives_no_vote_and_lists_the_same_question(self) -> None:
        r = self.vote(QUESTION, "Scripts run with pip", "test -n c")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("SAME-QUESTION decisions/scripts-uv", r.stdout)
        self.assertIn("NO-VOTE", r.stdout)
        self.assertEqual(self.show_json()["answers"][0]["evidence"], ["true"])

    def test_claim_matching_ignores_case_and_punctuation(self) -> None:
        r = self.vote(QUESTION, "scripts run with uv, run --script.", "test -n d")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("VOTED", r.stdout)


if __name__ == "__main__":
    unittest.main()
