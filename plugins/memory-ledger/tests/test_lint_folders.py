"""`lint` folder checks for a ledger root that sits under a dot-directory (the default `~/.memory-ledger`).

Every run is a subprocess against temp ledger roots.
"""
from __future__ import annotations

import re
import unittest

from test_rules import TempLedgerCase, _git_repo


class DotRootLintTests(TempLedgerCase):
    def setUp(self) -> None:
        super().setUp()
        self.shared = self.temp / ".dot" / "shared"
        _git_repo(self.shared)

    def lint_shared(self) -> str:
        return self.run_ledger("lint", "--only", "shared").stdout

    def test_a_folder_without_an_about_file_is_reported_and_dot_folders_are_not(self) -> None:
        self.assertTrue((self.shared / ".git").is_dir())
        (self.shared / "tech" / "orphan").mkdir(parents=True)
        (self.shared / ".cache").mkdir()
        (self.shared / "tech" / ".hidden").mkdir()
        out = self.lint_shared()
        self.assertRegex(out, r"NO-ABOUT\s+tech/orphan/")
        self.assertNotRegex(out, r"NO-ABOUT\s+\.git")
        self.assertNotIn(".cache", out)
        self.assertNotIn(".hidden", out)

    def test_an_oversize_folder_labels_a_token_that_names_an_existing_folder(self) -> None:
        (self.shared / "tech" / "widget").mkdir(parents=True)
        pile = self.shared / "tech" / "pile"
        pile.mkdir()
        for n in range(1, 52):
            (pile / f"widget-{n}.md").write_text(
                f"# tech/pile/widget-{n}\nQ: Which widget is number {n}?\n", encoding="utf-8")
        out = self.lint_shared()
        self.assertRegex(out, re.compile(r"OVERSIZE\s+tech/pile/ holds 51 entries.*"
                                         r"tech/widget/ \(51, already exists\)"))


if __name__ == "__main__":
    unittest.main()
