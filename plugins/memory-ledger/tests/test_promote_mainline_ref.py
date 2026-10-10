"""`promote` treats `origin/<branch>` and `<branch>` as the same mainline, as `lint` does.

Runs `promote` as a subprocess against temp ledger roots.
"""
from __future__ import annotations

import unittest

from test_rules import TempLedgerCase

ENTRY = """# tech/dup
Q: Is the widget ready?

## a1 · The widget is ready.  conf 0.30 · checked 2026-10-10
Because: Verified on the feature branch.
Evidence: true
Ref: feature/widget

## a2 · The widget is ready.  conf 0.30 · checked 2026-10-10
Because: Already verified on mainline.
Evidence: true
Ref: origin/master
"""


class PromoteMainlineRef(TempLedgerCase):
    def test_promote_refuses_when_mainline_already_says_it_with_origin_prefix(self) -> None:
        folder = self.shared / "tech"
        folder.mkdir(exist_ok=True)
        (folder / "dup.md").write_text(ENTRY, encoding="utf-8")
        result = self.run_ledger("promote", "tech/dup", "a1", "--to", "master")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already says this about master", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
