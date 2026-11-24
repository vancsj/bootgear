"""The deputy's round trip: record, then find the entry again, verbatim and by paraphrase.

Runs against a temporary deputy root through the gear route. The judgement is not run here;
only the candidate list is checked.
"""
from __future__ import annotations

import io
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "scripts"))

import deputy

QUESTION = "Should new scripts run with uv?"
PARAPHRASE = "Should I run scripts with uv?"
CLAIM = "Scripts run with uv run --script"
CANDIDATE = re.compile(r"^CANDIDATE (\S+)$", re.MULTILINE)


class RoundTripTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "deputy"
        self.root.mkdir()
        subprocess.run(["git", "-C", str(self.root), "init", "-q"], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.name", "Deputy Fixture"], check=True)
        subprocess.run(["git", "-C", str(self.root), "config", "user.email", "deputy@example.test"], check=True)
        out = io.StringIO()
        with redirect_stdout(out):
            code = deputy.main(["--deputy-root", str(self.root), "record",
                                "--question", QUESTION, "--claim", CLAIM,
                                "--confirmed-by-user"])
        self.assertEqual(code, 0)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def candidates(self, question: str) -> str:
        out = io.StringIO()
        with redirect_stdout(out):
            code = deputy.main(["--deputy-root", str(self.root), "candidates", question])
        self.assertEqual(code, 0)
        return out.getvalue()

    def test_verbatim_question_lists_its_entry(self) -> None:
        listed = CANDIDATE.findall(self.candidates(QUESTION))
        self.assertTrue(listed, "no candidates for the verbatim question")

    def test_paraphrase_lists_the_entry(self) -> None:
        listed = CANDIDATE.findall(self.candidates(PARAPHRASE))
        self.assertTrue(listed, "no candidates for the paraphrase")

    def test_every_listed_slug_exists_in_the_root(self) -> None:
        for question in (QUESTION, PARAPHRASE):
            for slug in CANDIDATE.findall(self.candidates(question)):
                self.assertTrue((self.root / f"{slug}.md").is_file(), slug)


if __name__ == "__main__":
    unittest.main()
