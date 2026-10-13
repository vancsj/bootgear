"""A charter (`_about.md`) is an entry like any other, so its personal Evidence paths are reported.

`audit` runs as a subprocess against temp ledger roots; the save-time check is called directly.
"""
from __future__ import annotations

import sys
import unittest
from types import SimpleNamespace

from test_rules import SCRIPTS, TempLedgerCase

sys.path.insert(0, str(SCRIPTS))

from ledgerlib.gitops import _check_unportable  # noqa: E402

CHARTER = """# tech/_about
Q: What belongs here?

## a1 · Browser automation notes.  conf 0.30 · checked 2026-10-10
Because: Keeps the browser checks in one place.
Evidence: ls ~/Repos/team-memory/tech/browser
"""


class CharterPortability(TempLedgerCase):
    def write_charter(self) -> None:
        folder = self.shared / "tech"
        folder.mkdir(exist_ok=True)
        (folder / "_about.md").write_text(CHARTER, encoding="utf-8")

    def test_audit_reports_a_charter_with_a_personal_path(self) -> None:
        self.write_charter()
        result = self.run_ledger("audit")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertIn("UNPORTABLE  tech/_about a1", result.stdout)
        self.assertIn("~/Repos/team-memory/tech/browser", result.stdout)

    def test_the_save_time_check_reports_a_charter(self) -> None:
        self.write_charter()
        lg = SimpleNamespace(kind="shared", root=self.shared)
        self.assertIsNotNone(_check_unportable(lg))


if __name__ == "__main__":
    unittest.main()
