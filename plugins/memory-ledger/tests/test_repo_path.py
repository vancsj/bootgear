"""A shared ledger's `Repo:` is a repo name, never a path only one machine can resolve.

Covers `machine_path`, the write gates on `new`, `rival` and `set-repo`, and the
`REPO-PATH` line in `lint`. Every run is a subprocess against temp ledger roots.
"""
from __future__ import annotations

import re
import subprocess
import sys
import unittest
from pathlib import Path

from test_rules import LEDGER, TempLedgerCase, _git, _git_repo

POSIX_PATH = "/srv/checkouts/app"
WINDOWS_PATH = "C:\\work\\app"
RELATIVE_PATH = "../app"
SPACED_PATH = "/srv/my checkouts/app"
QUESTION = "Which colour is the sky?"
LABEL = "Repo: is a machine path (1):"


def refusal_text(value: str, local_option: bool) -> str:
    options = ("Use the repo name (for example widgets), write to the local ledger instead "
               "(--local), or pass --force to file the path anyway."
               if local_option else
               "Use the repo name (for example widgets), or pass --force to file the path anyway.")
    return f"Repo: {value} is a machine path, which only this machine can resolve. {options}"


def lint_line(slug: str, aid: str, value: str) -> str:
    return (f"REPO-PATH  {slug} {aid}  Repo: {value} is a machine path — the shared ledger "
            f"takes a repo name; run `set-repo` with the name (`--force` keeps the path)")


class RepoPathCase(TempLedgerCase):
    def run_ledger_in(self, cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(LEDGER), *args], cwd=cwd,
                              env=self.env(), capture_output=True, text=True, check=False)

    def entry_path(self, kind: str, slug: str) -> Path:
        return (self.shared if kind == "shared" else self.local) / f"{slug}.md"

    def seed(self, kind: str, slug: str = "probe", repo: str | None = None) -> Path:
        args = ["new", slug, f"--{kind}", "--q", QUESTION, "--claim", "The sky is blue.",
                "--because", "Look up.", "--evidence", "true", "--as", "author-a", "--anyway"]
        if repo is not None:
            args += ["--repo", repo]
        result = self.run_ledger(*args)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        return self.entry_path(kind, slug)

    def seed_with_repo_line(self, kind: str, repo_line: str, slug: str = "probe") -> Path:
        """An entry whose `Repo:` line is exactly `repo_line`, as a hand edit would leave it."""
        path = self.seed(kind, slug)
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace("Evidence: true\n", f"Evidence: true\n{repo_line}\n"),
                        encoding="utf-8")
        return path

    def seed_without_evidence(self, kind: str, repo_line: str, slug: str = "probe") -> Path:
        path = self.entry_path(kind, slug)
        path.write_text(
            f"# {slug}\nQ: {QUESTION}\n\n"
            "## a1 · The sky is blue.                                      "
            f"conf 0.30 · checked 2026-01-01\n{repo_line}\n", encoding="utf-8")
        return path

    def checkout(self, name: str, origin: str) -> Path:
        path = self.temp / name
        _git_repo(path)
        _git(path, "remote", "add", "origin", origin)
        return path

    def write_new(self, repo: str, *extra: str, kind: str = "shared", slug: str = "fresh",
                  cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return self.run_ledger_in(
            cwd or self.temp, "new", slug, f"--{kind}", "--q", QUESTION, "--claim",
            "The sky is blue.", "--because", "Look up.", "--evidence", "true",
            "--as", "author-a", "--anyway", "--repo", repo, *extra)

    def write_rival(self, repo: str | None, *extra: str, slug: str = "probe",
                    cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        repo_args = ["--repo", repo] if repo is not None else []
        return self.run_ledger_in(
            cwd or self.temp, "rival", slug, "--claim", "The sky is grey.",
            "--because", "Overcast.", "--evidence", "true", "--as", "author-b",
            *repo_args, *extra)

    def write_set_repo(self, repo: str, *extra: str,
                       slug: str = "probe") -> subprocess.CompletedProcess[str]:
        return self.run_ledger("set-repo", slug, "a1", repo, *extra)

    def lint(self, *args: str) -> subprocess.CompletedProcess[str]:
        return self.run_ledger("lint", *args)

    @staticmethod
    def repo_path_lines(result: subprocess.CompletedProcess[str]) -> list[str]:
        return [ln for ln in result.stdout.splitlines() if ln.startswith("REPO-PATH")]

    @staticmethod
    def repo_lines(path: Path) -> list[str]:
        return [ln for ln in path.read_text(encoding="utf-8").splitlines()
                if ln.startswith("Repo:")]

    def assert_accepted(self, result: subprocess.CompletedProcess[str]) -> None:
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)

    def assert_refused(self, result: subprocess.CompletedProcess[str], value: str,
                       local_option: bool) -> None:
        self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
        self.assertIn(LABEL, result.stderr)
        self.assertIn(refusal_text(value, local_option), result.stderr)


def machine_path(value: str | None) -> bool:
    from ledgerlib.model import machine_path as under_test

    return under_test(value)


class MachinePathTests(unittest.TestCase):
    def test_paths_are_machine_paths(self) -> None:
        values = [
            POSIX_PATH, "/", "~", "~/work/app", "~someone", "\\work\\app", "\\\\host\\share\\app",
            "file:///srv/app", "file:app", "FILE:///srv/app", "File:/srv/app", WINDOWS_PATH, "C:/work/app", "d:\\app", RELATIVE_PATH,
            "..", "a/../b", "a\\..\\b", "a/..", "my app", "acme/my app", SPACED_PATH, "\t../app",
        ]
        for value in values:
            with self.subTest(value=value):
                self.assertTrue(machine_path(value))

    def test_names_are_not_machine_paths(self) -> None:
        values = [
            "widgets", "acme/widgets", "acme/widgets.git", "apps/widgets/sub", "./app",
            "app/..foo", "a..b/c", "..foo", "C:", "x:app", " widgets ", "\twidgets\n",
        ]
        for value in values:
            with self.subTest(value=value):
                self.assertFalse(machine_path(value))

    def test_unset_and_empty_are_not_machine_paths(self) -> None:
        self.assertFalse(machine_path(None))
        self.assertFalse(machine_path(""))

    def test_a_leading_space_does_not_hide_a_path(self) -> None:
        self.assertTrue(machine_path(" /srv/checkouts/app"))


class SharedWriteGateTests(RepoPathCase):
    def test_new_shared_refuses_a_path_and_writes_nothing(self) -> None:
        result = self.write_new(POSIX_PATH)
        self.assert_refused(result, POSIX_PATH, local_option=True)
        self.assertFalse(self.entry_path("shared", "fresh").exists())

    def test_rival_refuses_a_path_on_a_shared_slug_and_writes_nothing(self) -> None:
        path = self.seed("shared")
        before = path.read_bytes()
        result = self.write_rival(WINDOWS_PATH)
        self.assert_refused(result, WINDOWS_PATH, local_option=False)
        self.assertEqual(path.read_bytes(), before)

    def test_set_repo_refuses_a_relative_path_on_a_shared_slug(self) -> None:
        path = self.seed("shared")
        before = path.read_bytes()
        result = self.write_set_repo(RELATIVE_PATH)
        self.assert_refused(result, RELATIVE_PATH, local_option=False)
        self.assertEqual(path.read_bytes(), before)

    def test_set_repo_refuses_a_bare_tilde_on_a_shared_slug(self) -> None:
        path = self.seed("shared")
        before = path.read_bytes()
        result = self.write_set_repo("~")
        self.assert_refused(result, "~", local_option=False)
        self.assertEqual(path.read_bytes(), before)

    def test_set_repo_refusal_leaves_an_existing_repo_line_alone(self) -> None:
        path = self.seed("shared", repo="acme/widgets")
        before = path.read_bytes()
        result = self.write_set_repo(POSIX_PATH)
        self.assert_refused(result, POSIX_PATH, local_option=False)
        self.assertEqual(path.read_bytes(), before)

    def test_file_url_is_refused_on_every_shared_write(self) -> None:
        value = "file:///srv/app"
        path = self.seed("shared")
        before = path.read_bytes()
        self.assert_refused(self.write_new(value), value, local_option=True)
        self.assertFalse(self.entry_path("shared", "fresh").exists())
        self.assert_refused(self.write_rival(value), value, local_option=False)
        self.assert_refused(self.write_set_repo(value), value, local_option=False)
        self.assertEqual(path.read_bytes(), before)

    def test_an_upper_case_file_url_is_refused_on_a_shared_write(self) -> None:
        value = "FILE:///srv/app"
        self.assert_refused(self.write_new(value), value, local_option=True)
        self.assertFalse(self.entry_path("shared", "fresh").exists())

    def test_a_leading_space_does_not_bypass_the_gate(self) -> None:
        value = " /srv/checkouts/app"
        path = self.seed("shared")
        before = path.read_bytes()
        for label, result in (("new", self.write_new(value)),
                              ("rival", self.write_rival(value)),
                              ("set-repo", self.write_set_repo(value))):
            with self.subTest(command=label):
                self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
                self.assertIn(LABEL, result.stderr)
        self.assertFalse(self.entry_path("shared", "fresh").exists())
        self.assertEqual(path.read_bytes(), before)

    def test_a_value_with_a_space_is_refused_on_a_shared_write(self) -> None:
        path = self.seed("shared")
        before = path.read_bytes()
        self.assert_refused(self.write_new(SPACED_PATH), SPACED_PATH, local_option=True)
        self.assertFalse(self.entry_path("shared", "fresh").exists())
        self.assert_refused(self.write_rival(SPACED_PATH), SPACED_PATH, local_option=False)
        self.assert_refused(self.write_set_repo(SPACED_PATH), SPACED_PATH, local_option=False)
        self.assertEqual(path.read_bytes(), before)

    def test_a_refused_rival_and_set_repo_leave_the_file_byte_identical(self) -> None:
        path = self.seed("shared", repo="acme/widgets")
        before = path.read_bytes()
        for value in (POSIX_PATH, WINDOWS_PATH, RELATIVE_PATH, "~", "file:///srv/app"):
            for label, run in (("rival", self.write_rival), ("set-repo", self.write_set_repo)):
                with self.subTest(command=label, value=value):
                    self.assertEqual(run(value).returncode, 1)
                    self.assertEqual(path.read_bytes(), before)


class ForceTests(RepoPathCase):
    def test_new_force_files_a_path_on_the_shared_ledger(self) -> None:
        self.assert_accepted(self.write_new(POSIX_PATH, "--force"))
        self.assertEqual(self.repo_lines(self.entry_path("shared", "fresh")),
                         [f"Repo: {POSIX_PATH}"])

    def test_rival_force_files_a_path_on_a_shared_slug(self) -> None:
        path = self.seed("shared")
        self.assert_accepted(self.write_rival(POSIX_PATH, "--force"))
        self.assertEqual(self.repo_lines(path), [f"Repo: {POSIX_PATH}"])

    def test_set_repo_force_files_a_path_on_a_shared_slug(self) -> None:
        path = self.seed("shared")
        self.assert_accepted(self.write_set_repo(RELATIVE_PATH, "--force"))
        self.assertEqual(self.repo_lines(path), [f"Repo: {RELATIVE_PATH}"])

    def test_force_help_names_the_machine_path_gate(self) -> None:
        for command in ("new", "rival", "set-repo"):
            with self.subTest(command=command):
                result = self.run_ledger(command, "--help")
                self.assertEqual(result.returncode, 0, result.stderr)
                force_help = re.search(r"^ +--force\b(.*?)(?=^ +-|\Z)", result.stdout,
                                       re.MULTILINE | re.DOTALL)
                self.assertIsNotNone(force_help, result.stdout)
                self.assertRegex(" ".join(force_help.group(1).split()), r"machine[- ]+path")


class LocalAndNameTests(RepoPathCase):
    def test_new_local_accepts_a_path(self) -> None:
        self.assert_accepted(self.write_new(POSIX_PATH, kind="local"))
        self.assertEqual(self.repo_lines(self.entry_path("local", "fresh")),
                         [f"Repo: {POSIX_PATH}"])

    def test_rival_on_a_local_slug_accepts_a_path(self) -> None:
        path = self.seed("local", "scratch")
        self.assert_accepted(self.write_rival(POSIX_PATH, slug="scratch"))
        self.assertEqual(self.repo_lines(path), [f"Repo: {POSIX_PATH}"])

    def test_set_repo_on_a_local_slug_accepts_a_path(self) -> None:
        path = self.seed("local", "scratch")
        self.assert_accepted(self.write_set_repo(WINDOWS_PATH, slug="scratch"))
        self.assertEqual(self.repo_lines(path), [f"Repo: {WINDOWS_PATH}"])

    def test_rival_accepts_an_owner_and_name(self) -> None:
        path = self.seed("shared")
        self.assert_accepted(self.write_rival("acme/widgets"))
        self.assertEqual(self.repo_lines(path), ["Repo: acme/widgets"])

    def test_set_repo_accepts_a_bare_name(self) -> None:
        path = self.seed("shared")
        self.assert_accepted(self.write_set_repo("widgets"))
        self.assertEqual(self.repo_lines(path), ["Repo: widgets"])

    def test_set_repo_replaces_a_hand_written_spaced_value_in_place(self) -> None:
        path = self.seed_with_repo_line("shared", f"Repo: {SPACED_PATH}")
        self.assert_accepted(self.write_set_repo("widgets"))
        self.assertEqual(self.repo_lines(path), ["Repo: widgets"])

    def test_new_shared_accepts_a_name(self) -> None:
        self.assert_accepted(self.write_new("widgets"))
        self.assertEqual(self.repo_lines(self.entry_path("shared", "fresh")), ["Repo: widgets"])


class InferredRepoTests(RepoPathCase):
    def test_new_infers_the_repo_name_from_an_https_origin(self) -> None:
        cwd = self.checkout("app", "https://example.invalid/acme/widgets.git")
        result = self.run_ledger_in(
            cwd, "new", "inferred", "--shared", "--q", QUESTION, "--claim", "The sky is blue.",
            "--because", "Look up.", "--evidence", "true", "--as", "author-a",
            "--anyway", "--ref", "feature/x")
        self.assert_accepted(result)
        text = self.entry_path("shared", "inferred").read_text(encoding="utf-8")
        self.assertIn("Repo: widgets", text.splitlines())

    def test_rival_with_a_ref_infers_the_repo_name_from_the_checkout(self) -> None:
        cwd = self.checkout("app", "https://example.invalid/acme/widgets.git")
        path = self.seed("shared")
        self.assert_accepted(self.write_rival(None, "--ref", "feature/x", cwd=cwd))
        self.assertEqual(self.repo_lines(path), ["Repo: widgets"])

    def test_a_backslash_origin_is_inferred_as_a_path_and_lint_reports_it(self) -> None:
        cwd = self.checkout("app", WINDOWS_PATH)
        result = self.run_ledger_in(
            cwd, "new", "inferred", "--shared", "--q", QUESTION, "--claim", "The sky is blue.",
            "--because", "Look up.", "--evidence", "true", "--as", "author-a",
            "--anyway", "--ref", "feature/x")
        self.assert_accepted(result)
        text = self.entry_path("shared", "inferred").read_text(encoding="utf-8")
        self.assertIn(f"Repo: {WINDOWS_PATH}", text.splitlines())
        report = self.lint("--only", "shared")
        self.assertEqual(report.returncode, 1, report.stdout)
        self.assertIn(lint_line("inferred", "a1", WINDOWS_PATH), self.repo_path_lines(report))


class LintRepoPathTests(RepoPathCase):
    def test_shared_lint_reports_a_path_and_exits_one(self) -> None:
        self.seed_with_repo_line("shared", f"Repo: {POSIX_PATH}")
        result = self.lint("--only", "shared")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(self.repo_path_lines(result), [lint_line("probe", "a1", POSIX_PATH)])
        self.assertIn("1 problem(s)", result.stdout)

    def test_shared_lint_reports_an_answer_that_has_no_evidence(self) -> None:
        self.seed_without_evidence("shared", f"Repo: {POSIX_PATH}")
        result = self.lint("--only", "shared")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(self.repo_path_lines(result), [lint_line("probe", "a1", POSIX_PATH)])

    def test_shared_lint_reports_a_stored_value_with_extra_leading_space(self) -> None:
        self.seed_with_repo_line("shared", f"Repo:  {POSIX_PATH}")
        result = self.lint("--only", "shared")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(len(self.repo_path_lines(result)), 1, result.stdout)

    def test_shared_lint_reports_a_hand_written_value_with_a_space(self) -> None:
        self.seed_with_repo_line("shared", f"Repo: {SPACED_PATH}")
        result = self.lint("--only", "shared")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(self.repo_path_lines(result), [lint_line("probe", "a1", SPACED_PATH)])

    def test_shared_lint_reports_each_answer_that_names_a_path(self) -> None:
        path = self.seed_with_repo_line("shared", f"Repo: {POSIX_PATH}")
        self.assert_accepted(self.write_rival(WINDOWS_PATH, "--force"))
        result = self.lint("--only", "shared")
        self.assertEqual(
            self.repo_path_lines(result),
            [lint_line("probe", "a1", POSIX_PATH), lint_line("probe", "a2", WINDOWS_PATH)],
            path.read_text(encoding="utf-8"))

    def test_lint_is_clean_for_names_and_unscoped_answers(self) -> None:
        self.seed("shared", "named", repo="acme/widgets")
        self.seed("shared", "bare", repo="widgets")
        self.seed("shared", "unscoped")
        result = self.lint("--only", "shared")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.repo_path_lines(result), [])

    def test_local_lint_prints_nothing_for_a_path(self) -> None:
        self.seed_with_repo_line("local", f"Repo: {POSIX_PATH}")
        result = self.lint("--only", "local")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("REPO-PATH", result.stdout)

    def test_unscoped_lint_reports_only_the_shared_side(self) -> None:
        self.seed_with_repo_line("shared", f"Repo: {POSIX_PATH}", "up")
        self.seed_with_repo_line("local", f"Repo: {WINDOWS_PATH}", "down")
        result = self.lint()
        self.assertEqual(self.repo_path_lines(result), [lint_line("up", "a1", POSIX_PATH)])

    def test_lint_fix_leaves_the_repo_line_byte_identical(self) -> None:
        for kind in ("shared", "local"):
            with self.subTest(kind=kind):
                path = self.seed_with_repo_line(kind, f"Repo: {POSIX_PATH}", f"fix-{kind}")
                before = self.repo_lines(path)
                self.lint("--only", kind, "--fix")
                self.assertEqual(self.repo_lines(path), before)
                self.assertEqual(before, [f"Repo: {POSIX_PATH}"])


if __name__ == "__main__":
    unittest.main()
