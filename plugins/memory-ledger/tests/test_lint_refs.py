"""`lint` SPLIT and ref-state lines: SPLIT after a rival, mainline recognition, REF-GONE next to a mainline sibling.

Every run is a subprocess against temp ledger roots; ref tests need a clone whose origin URL names the repo
(`widgets`), so they build one and run every `ledger.py` call from inside it.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from test_rules import TempLedgerCase

Q = "Which colour is the sky?"


class RefLintCase(TempLedgerCase):
    def make_clone(self, branch: str) -> Path:
        """A clone of `widgets.git` with one commit pushed to `origin/<branch>`."""
        bare = self.temp / "widgets.git"
        clone = self.temp / "widgets"
        subprocess.run(["git", "init", "--bare", "-q", "-b", branch, str(bare)], check=True)
        subprocess.run(["git", "clone", "-q", str(bare), str(clone)], check=True,
                       capture_output=True)
        for args in (["checkout", "-q", "-b", branch], ["commit", "-q", "--allow-empty", "-m", "init"],
                     ["push", "-q", "origin", branch]):
            subprocess.run(["git", "-C", str(clone), *args], check=True, env=self.env(),
                           capture_output=True)
        return clone

    def run_in(self, cwd: Path, *args: str, env: dict[str, str] | None = None
               ) -> subprocess.CompletedProcess[str]:
        import sys
        from test_rules import LEDGER
        return subprocess.run([sys.executable, str(LEDGER), *args], cwd=cwd,
                              env=env or self.env(), capture_output=True, text=True, check=False)

    def new(self, cwd: Path, slug: str, *extra: str, question: str = Q) -> None:
        result = self.run_in(cwd, "new", slug, "--local", "--q", question, "--claim", "The sky is blue.",
                             "--because", "Look up.", "--evidence", "true", "--as", "author-a", *extra)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def rival(self, cwd: Path, slug: str, claim: str, *extra: str) -> None:
        result = self.run_in(cwd, "rival", slug, "--claim", claim, "--because", "Look up.",
                             "--evidence", "true", "--as", "author-b", *extra)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def lint(self, cwd: Path, env: dict[str, str] | None = None) -> str:
        return self.run_in(cwd, "lint", "--only", "local", env=env).stdout


class SplitLintTests(RefLintCase):
    def split(self, cwd: Path, slug: str, aid: str) -> None:
        result = self.run_in(cwd, "sign", slug, aid, "--fail", "--output", "differs", "--as", "other")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def test_a_split_answer_stops_reporting_once_a_rival_exists(self) -> None:
        self.new(self.temp, "tech/seed")
        self.split(self.temp, "tech/seed", "a1")
        self.assertRegex(self.lint(self.temp), r"SPLIT\s+tech/seed a1")
        self.rival(self.temp, "tech/seed", "The sky is grey.")
        self.assertNotIn("SPLIT", self.lint(self.temp))

    def test_the_last_answer_of_an_entry_still_reports_a_split(self) -> None:
        self.new(self.temp, "tech/two")
        self.rival(self.temp, "tech/two", "The sky is grey.")
        self.split(self.temp, "tech/two", "a2")
        out = self.lint(self.temp)
        self.assertRegex(out, r"SPLIT\s+tech/two a2")
        self.assertNotRegex(out, r"SPLIT\s+tech/two a1")


class MainlineRecognitionTests(RefLintCase):
    def test_a_short_mainline_name_is_not_ref_checked(self) -> None:
        clone = self.make_clone("master")
        self.new(clone, "tech/short", "--ref", "master", "--repo", "widgets")
        self.assertNotIn("REF-", self.lint(clone))

    def test_a_remote_mainline_name_is_not_ref_checked_under_a_configured_short_one(self) -> None:
        clone = self.make_clone("master")
        self.new(clone, "tech/remote", "--ref", "origin/master", "--repo", "widgets")
        env = {**self.env(), "LEDGER_REF": "master"}
        self.assertNotIn("REF-", self.lint(clone, env))


class RefLandedTests(RefLintCase):
    def test_a_landed_branch_is_reported_until_a_mainline_sibling_exists(self) -> None:
        clone = self.make_clone("main")
        subprocess.run(["git", "-C", str(clone), "branch", "feature"], check=True)
        self.new(clone, "tech/landed", "--ref", "feature")
        self.assertRegex(self.lint(clone), r"REF-LANDED\s+tech/landed a1")
        self.rival(clone, "tech/landed", "The sky is grey.", "--ref", "main", "--repo", str(clone))
        self.assertNotIn("REF-", self.lint(clone))


class RefGoneTests(RefLintCase):
    def test_a_mainline_sibling_silences_ref_gone_by_path_and_by_name(self) -> None:
        clone = self.make_clone("main")
        self.new(clone, "tech/by-path", "--ref", "ghost")
        self.assertRegex(self.lint(clone), r"REF-GONE\s+tech/by-path a1")
        self.rival(clone, "tech/by-path", "The sky is grey.", "--ref", "main", "--repo", str(clone))
        self.assertNotIn("REF-", self.lint(clone))
        self.new(clone, "tech/by-name", "--ref", "ghost", question="How tall is the old tower?")
        self.rival(clone, "tech/by-name", "The sky is grey.", "--ref", "main", "--repo", "widgets")
        self.assertNotIn("REF-", self.lint(clone))

    def test_a_mainline_sibling_in_another_repo_keeps_ref_gone(self) -> None:
        clone = self.make_clone("main")
        self.new(clone, "tech/other", "--ref", "ghost")
        self.rival(clone, "tech/other", "The sky is grey.", "--ref", "main", "--repo", "otherrepo")
        self.assertRegex(self.lint(clone), r"REF-GONE\s+tech/other a1")

    def test_without_a_detectable_mainline_a_refless_sibling_keeps_ref_gone(self) -> None:
        """A sibling without a `Ref:` is not a mainline sibling when no mainline can be found."""
        clone = self.make_clone("trunk")
        self.new(clone, "tech/none", "--ref", "ghost")
        self.rival(clone, "tech/none", "The sky is grey.", "--repo", "widgets")
        self.assertRegex(self.lint(clone), r"REF-GONE\s+tech/none a1")

    def test_a_ref_without_a_repo_still_reports_ref_unscoped(self) -> None:
        """A `Ref:` with no `Repo:` is still reported as unscoped."""
        clone = self.make_clone("main")
        self.new(self.temp, "tech/unscoped", "--ref", "ghost")
        self.assertRegex(self.lint(clone), r"REF-UNSCOPED\s+tech/unscoped a1")
