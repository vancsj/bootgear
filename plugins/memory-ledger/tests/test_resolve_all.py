"""`resolve --all`: every match is printed, and the default still applies the score-gap cut.

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
# `new` signs with this id when the host did not set one.
os.environ.setdefault("CLAUDE_CODE_SESSION_ID", "resolve-all-test-session")
QUESTION = "Should new scripts run with uv?"
# Six entries that all share some terms with QUESTION, so all six clear the fuzzy floor.
ENTRIES = [
    ("tools/uv-scripts", QUESTION, "Scripts run with uv run --script"),
    ("tools/uv-deps", "Should new scripts pin dependencies with uv?", "Pin script dependencies"),
    ("tools/pip-scripts", "Should scripts run with pip?", "Scripts use pip"),
    ("tools/shell-scripts", "Should new scripts be shell?", "Scripts are shell"),
    ("tools/uv-lock", "Should the repo lock with uv?", "Lock files are uv lock"),
    ("tools/venv-scripts", "Should scripts use a venv?", "Scripts use a venv"),
]


class ResolveAllTest(unittest.TestCase):
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
        for slug, question, claim in ENTRIES:
            r = cls.ledger("new", slug, "--shared", "--q", question, "--claim", claim,
                           "--because", "Because: test. Context: none.", "--evidence", "true")
            assert r.returncode == 0, r.stderr

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    @classmethod
    def ledger(cls, *args: str) -> subprocess.CompletedProcess:
        shared, local, deputy = cls.roots
        return subprocess.run([sys.executable, str(LEDGER), "--root", shared,
                               "--local-root", local, "--deputy-root", deputy, *args],
                              capture_output=True, text=True)

    def listed_slugs(self, stdout: str) -> list[str]:
        return [line.split()[2] for line in stdout.splitlines()
                if line.startswith("   ") and "  tools/" in line]

    def test_default_resolve_cuts_the_weaker_matches(self) -> None:
        r = self.ledger("resolve", QUESTION)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertLess(len(self.listed_slugs(r.stdout)), len(ENTRIES), r.stdout)

    def test_all_lists_every_match(self) -> None:
        r = self.ledger("resolve", QUESTION, "--all")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(sorted(self.listed_slugs(r.stdout)),
                         sorted(slug for slug, _, _ in ENTRIES), r.stdout)
        self.assertIn(f"{len(ENTRIES)} candidate(s)", r.stdout)
        self.assertNotIn("more in", r.stdout)
        self.assertNotIn("weaker candidate", r.stdout)

    def test_all_keeps_the_exact_match_and_the_inline_top(self) -> None:
        r = self.ledger("resolve", QUESTION, "--all")
        self.assertIn("── tools/uv-scripts", r.stdout)
        exact = self.ledger("resolve", "tools/uv-scripts", "--all")
        self.assertIn("EXACT    tools/uv-scripts", exact.stdout)


if __name__ == "__main__":
    unittest.main()
