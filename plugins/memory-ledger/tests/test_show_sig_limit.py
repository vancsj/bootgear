"""`show` prints every ✗ and the newest few ✓; `--all-sigs` prints every signature.

Every run is a subprocess against temp ledger roots; nothing here touches a real ledger.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
LEDGER = PLUGIN / "scripts" / "ledger.py"
sys.path.insert(0, str(PLUGIN / "scripts"))
from ledgerlib.constants import SHOW_MAX_YES_SIGS

SLUG = "tools/vote-limit"
QUESTION = "Should show print every signature?"
CLAIM = "Show prints every signature"
# A Claude signer is the first segment of the session id, so these stay distinct.
AUTHOR = "a0000000-0000-0000-0000-000000000000"
DISSENT = "d0000000-0000-0000-0000-000000000000"
VOTERS = [f"{n:08d}-0000-0000-0000-000000000000" for n in range(1, 8)]
# ✓ sessions in signing order: the author signs at `new`, then the voters.
SIGNED_YES = [AUTHOR, *VOTERS]
TOTAL_YES = len(SIGNED_YES)


def who_of(session: str) -> str:
    return session.split("-")[0]


class ShowSigLimitTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        base = Path(cls._tmp.name)
        cls.roots = []
        for name in ("shared", "local", "deputy"):
            root = base / name
            root.mkdir()
            subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
            cls.roots.append(str(root))
        r = cls.ledger("new", SLUG, "--shared", "--q", QUESTION, "--claim", CLAIM,
                       "--because", "Because: test. Context: none.", "--evidence", "true",
                       session=AUTHOR)
        assert r.returncode == 0, r.stderr
        for n, session in enumerate(VOTERS, start=1):
            if n == 2:
                # The ✗ sits before the second ✓ in file order, outside the newest-five window.
                r = cls.ledger("sign", SLUG, "a1", "--fail", "--output", "boom",
                               session=DISSENT)
                assert r.returncode == 0, r.stderr
            r = cls.ledger("sign", SLUG, "a1", session=session)
            assert r.returncode == 0, r.stderr

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    @classmethod
    def ledger(cls, *args: str, session: str = AUTHOR) -> subprocess.CompletedProcess:
        shared, local, deputy = cls.roots
        env = {**os.environ, "CLAUDE_CODE_SESSION_ID": session}
        return subprocess.run([sys.executable, str(LEDGER), "--root", shared,
                               "--local-root", local, "--deputy-root", deputy, *args],
                              capture_output=True, text=True, check=False, env=env)

    @staticmethod
    def sig_lines(stdout: str) -> tuple[list[str], list[str]]:
        lines = stdout.splitlines()
        return ([ln for ln in lines if ln.startswith("    ✓ ")],
                [ln for ln in lines if ln.startswith("    ✗ ")])

    def test_default_shows_every_fail_and_the_newest_yes(self) -> None:
        r = self.ledger("show", SLUG)
        self.assertEqual(r.returncode, 0, r.stderr)
        yes, no = self.sig_lines(r.stdout)
        self.assertEqual(len(yes), SHOW_MAX_YES_SIGS, r.stdout)
        self.assertEqual(len(no), 1, r.stdout)
        self.assertIn(who_of(DISSENT), no[0])
        newest = SIGNED_YES[-SHOW_MAX_YES_SIGS:]
        oldest = SIGNED_YES[:-SHOW_MAX_YES_SIGS]
        for session in newest:
            self.assertTrue(any(f" {who_of(session)} " in ln for ln in yes), r.stdout)
        for session in oldest:
            self.assertFalse(any(f" {who_of(session)} " in ln for ln in yes), r.stdout)
        self.assertIn(who_of(VOTERS[-1]), yes[0])  # newest first
        self.assertIn(f"… {TOTAL_YES - SHOW_MAX_YES_SIGS} older ✓ not shown", r.stdout)
        self.assertIn(f"show {SLUG} --all-sigs", r.stdout)

    def test_all_sigs_prints_every_signature(self) -> None:
        r = self.ledger("show", SLUG, "--all-sigs")
        self.assertEqual(r.returncode, 0, r.stderr)
        yes, no = self.sig_lines(r.stdout)
        self.assertEqual(len(yes), TOTAL_YES, r.stdout)
        self.assertEqual(len(no), 1, r.stdout)
        self.assertNotIn("not shown", r.stdout)
        self.assertIn(who_of(VOTERS[-1]), yes[0])  # newest first

    def test_header_tally_counts_every_signature(self) -> None:
        for extra in ([], ["--all-sigs"]):
            r = self.ledger("show", SLUG, *extra)
            self.assertIn(f"{TOTAL_YES}✓/1✗", r.stdout, r.stdout)

    def test_default_cap_is_five(self) -> None:
        self.assertEqual(SHOW_MAX_YES_SIGS, 5)

    def test_footer_counts_only_valid_yes_signatures(self) -> None:
        slug = "tools/voided-tail"
        fresh = "f0000000-0000-0000-0000-000000000000"
        created = self.ledger("new", slug, "--shared", "--q", "Does the footer skip voided ✓?",
                              "--claim", "The footer skips voided ✓.",
                              "--because", "Because: test. Context: none.", "--evidence", "true")
        self.assertEqual(created.returncode, 0, created.stderr)
        for session in VOTERS:
            signed = self.ledger("sign", slug, "a1", session=session)
            self.assertEqual(signed.returncode, 0, signed.stderr)
        path = Path(self.roots[0]) / f"{slug}.md"
        body = path.read_text(encoding="utf-8")
        path.write_text(body.replace("The footer skips voided ✓.", "The footer skips voided ✓ only."),
                        encoding="utf-8")
        resigned = self.ledger("sign", slug, "a1", session=fresh)
        self.assertEqual(resigned.returncode, 0, resigned.stderr)
        r = self.ledger("show", slug)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("1✓/0✗", r.stdout, r.stdout)
        self.assertIn(f"{len(VOTERS) + 1} voided by an edit", r.stdout, r.stdout)
        self.assertNotIn("not shown", r.stdout)

    def test_footer_names_the_answer_that_hides_signatures(self) -> None:
        slug = "tools/two-answers"
        created = self.ledger("new", slug, "--shared", "--q", "Two answers?",
                              "--claim", "The first answer.",
                              "--because", "Because: test. Context: none.", "--evidence", "true")
        self.assertEqual(created.returncode, 0, created.stderr)
        for session in VOTERS:
            signed = self.ledger("sign", slug, "a1", session=session)
            self.assertEqual(signed.returncode, 0, signed.stderr)
        rival = self.ledger("rival", slug, "--claim", "The second answer.",
                            "--because", "Because: test. Context: none.", "--evidence", "true")
        self.assertEqual(rival.returncode, 0, rival.stderr)
        r = self.ledger("show", slug)
        self.assertEqual(r.returncode, 0, r.stderr)
        hidden = TOTAL_YES - SHOW_MAX_YES_SIGS
        self.assertIn(f"… {hidden} older ✓ not shown (a1 {hidden})", r.stdout, r.stdout)

    def test_footer_totals_hidden_check_marks_across_answers(self) -> None:
        slug = "tools/two-totals"
        created = self.ledger("new", slug, "--shared", "--q", "Two totals?",
                              "--claim", "The first answer.",
                              "--because", "Because: test. Context: none.", "--evidence", "true")
        self.assertEqual(created.returncode, 0, created.stderr)
        rival = self.ledger("rival", slug, "--claim", "The second answer.",
                            "--because", "Because: test. Context: none.", "--evidence", "true")
        self.assertEqual(rival.returncode, 0, rival.stderr)
        for aid in ("a1", "a2"):
            for session in VOTERS:
                signed = self.ledger("sign", slug, aid, session=session)
                self.assertEqual(signed.returncode, 0, signed.stderr)
        r = self.ledger("show", slug)
        self.assertEqual(r.returncode, 0, r.stderr)
        hidden = TOTAL_YES - SHOW_MAX_YES_SIGS
        self.assertIn(f"… {2 * hidden} older ✓ not shown (a1 {hidden}, a2 {hidden})", r.stdout, r.stdout)

    def test_data_refuses_all_sigs(self) -> None:
        r = self.ledger("show", SLUG, "--data", "--all-sigs")
        self.assertNotEqual(r.returncode, 0, r.stdout)
        self.assertIn("--all-sigs", r.stderr)


if __name__ == "__main__":
    unittest.main()
