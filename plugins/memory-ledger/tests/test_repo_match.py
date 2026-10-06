"""`same_repo_name` and `on_mainline`: how `lint` decides two `Repo:` values, or a `Ref:` and the mainline, are the same.

Pure functions, no subprocess.
"""
from __future__ import annotations

import sys
import unittest

from test_rules import SCRIPTS

sys.path.insert(0, str(SCRIPTS))

from ledgerlib.model import on_mainline, same_repo_name  # noqa: E402


class SameRepoNameTests(unittest.TestCase):
    def test_values_naming_one_repo_match_whatever_their_form(self) -> None:
        for other in ("widgets", "Widgets", "widgets.git", "acme/widgets", "/srv/checkouts/widgets/",
                      "git@github.com:acme/widgets.git"):
            with self.subTest(other=other):
                self.assertTrue(same_repo_name("widgets", other))
                self.assertTrue(same_repo_name(other, "widgets"))

    def test_different_repos_do_not_match(self) -> None:
        self.assertFalse(same_repo_name("widgets", "gadgets"))
        self.assertFalse(same_repo_name("widgets", "widgets-extra"))

    def test_two_empty_values_match_and_one_empty_value_does_not(self) -> None:
        self.assertTrue(same_repo_name(None, None))
        self.assertTrue(same_repo_name("", None))
        self.assertFalse(same_repo_name(None, "widgets"))
        self.assertFalse(same_repo_name("widgets", ""))


class OnMainlineTests(unittest.TestCase):
    def test_a_leading_origin_is_ignored_on_either_side(self) -> None:
        self.assertTrue(on_mainline("master", "origin/master"))
        self.assertTrue(on_mainline("origin/master", "master"))
        self.assertTrue(on_mainline("main", "main"))

    def test_another_branch_is_not_the_mainline(self) -> None:
        self.assertFalse(on_mainline("feature", "origin/main"))
        self.assertFalse(on_mainline("main", "origin/master"))

    def test_nothing_is_mainline_when_either_value_is_missing(self) -> None:
        self.assertFalse(on_mainline(None, None))
        self.assertFalse(on_mainline("main", None))
        self.assertFalse(on_mainline(None, "origin/main"))


if __name__ == "__main__":
    unittest.main()
