from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from quality import check_content

# Fixture paths are assembled at run time so this file never holds a literal
# home or scratchpad path for the repository scan to flag.
USERS = "/" + "Users" + "/"
HOME = "/" + "home" + "/"


class ContentTests(unittest.TestCase):
    def test_repository_is_clean(self) -> None:
        self.assertEqual(check_content.find_violations(denylist=[]), [])

    def test_flags_real_home_directories(self) -> None:
        self.assertEqual(check_content.line_violations(f"see {USERS}alice/x"), [f"{USERS}alice"])
        self.assertEqual(check_content.line_violations(f"cd {HOME}bob"), [f"{HOME}bob"])
        windows = "C:" + "\\" + "Users" + "\\" + "carol"
        self.assertEqual(check_content.line_violations(windows), [windows])
        tilde = "~" + "dave/"
        self.assertEqual(check_content.line_violations(tilde + "notes"), [tilde])

    def test_allows_placeholder_users_and_own_home(self) -> None:
        for text in (f"{USERS}someone/x", f"{HOME}<you>/x", "~/.bootgear/session",
                     f"{USERS}…", f"{USERS}...", "$HOME/.bootgear", "~" + "someone/x"):
            self.assertEqual(check_content.line_violations(text), [], text)

    def test_flags_session_scratchpads(self) -> None:
        scratch = "/private/tmp/" + "claude-501/p/s"
        self.assertEqual(check_content.line_violations(scratch), ["/tmp/" + "claude-501/"])
        folders = "/var/" + "folders/ab/T/x"
        self.assertEqual(check_content.line_violations(folders), ["/var/" + "folders/ab/"])

    def test_reports_file_and_line(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="content-test-"))
        (root / "a.md").write_text(f"ok\nsee {USERS}alice/notes\n")
        violations = check_content.find_violations(root, [Path("a.md")], denylist=[])
        self.assertEqual([(v.path, v.line) for v in violations], [(Path("a.md"), 2)])

    def test_flags_docs_pointers_in_code_and_skills_only(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="content-test-"))
        pointer = "doc" + "s/engine.md"
        names = ("a.py", "skills/x/SKILL.md", "tests/t.py", "doc" + "s/x.md", "README.md", "CONTRIBUTING.md")
        for name in names:
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text(f"# see {pointer}\n# see ../{pointer}\n")
        violations = check_content.find_violations(root, [Path(n) for n in names], denylist=[])
        self.assertEqual(
            sorted({(v.path, v.rule) for v in violations}),
            [(Path("a.py"), "points to docs"), (Path("skills/x/SKILL.md"), "points to docs")],
        )
        self.assertEqual(len(violations), 4)

    def test_docs_pointer_forms(self) -> None:
        folder = "doc" + "s/"
        repo = "https://github.com/o/boot" + "gear"
        for text in (f"see {folder}engine.md", f"{repo}/blob/main/{folder}engine.md",
                     f"{repo}/tree/main/{folder}engine.md", f"{repo}/blob/feat/x/{folder}a.md",
                     f"https://raw.githubusercontent.com/o/boot" + f"gear/main/{folder}a.md",
                     f"[x](/{folder}x.md)", f"../{folder}x.md", f"./{folder}x.md"):
            self.assertTrue(check_content.DOCS_POINTER_RE.search(text), text)
        for text in ("plugins/x/" + folder + "y.md", "my" + folder + "z",
                     f"never points to `{folder}`", f"the {folder} folder",
                     f"https://github.com/other/proj/blob/main/{folder}api.md"):
            self.assertIsNone(check_content.DOCS_POINTER_RE.search(text), text)

    def test_scans_untracked_files(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="content-test-"))
        subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
        (root / "new.md").write_text(f"see {USERS}alice/x\n")
        (root / ".gitignore").write_text("ignored.md\n")
        (root / "ignored.md").write_text(f"see {USERS}alice/x\n")
        violations = check_content.find_violations(root, denylist=[])
        self.assertEqual([v.path for v in violations], [Path("new.md")])

    def test_denylist_path_from_env(self) -> None:
        path = Path(tempfile.mkdtemp(prefix="content-test-")) / "deny.txt"
        path.write_text("Acme\n")
        with patch.dict(os.environ, {check_content.DENYLIST_ENV: str(path)}):
            self.assertEqual(check_content.load_denylist(), ["acme"])

    def test_denylist_default_path_under_bootgear(self) -> None:
        self.assertEqual(check_content.DEFAULT_DENYLIST, Path.home() / ".bootgear" / "content-denylist.txt")
        default = Path(tempfile.mkdtemp(prefix="content-test-")) / "default.txt"
        default.write_text("Acme\n")
        with patch.dict(os.environ, {check_content.DENYLIST_ENV: ""}), \
                patch.object(check_content, "DEFAULT_DENYLIST", default):
            self.assertEqual(check_content.load_denylist(), ["acme"])

    def test_flags_development_diary_phrases(self) -> None:
        for phrase in ("before this " + "fix", "found in " + "review", "tried and " + "rejected",
                       "an earlier " + "version", "previous version of this " + "test"):
            self.assertEqual(check_content.diary_phrases(f"# {phrase.title()}: x"), [phrase], phrase)
        self.assertEqual(check_content.diary_phrases("# used to compute the hash"), [])

    def test_flags_denylisted_terms_case_insensitively(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="content-test-"))
        (root / "a.md").write_text("fine\nAcme Widgets rule\n")
        violations = check_content.find_violations(root, [Path("a.md")], denylist=["acme widgets"])
        self.assertEqual([(v.line, v.rule) for v in violations], [(2, "denylisted term")])

    def test_denylist_file_ignores_blanks_and_comments(self) -> None:
        path = Path(tempfile.mkdtemp(prefix="content-test-")) / "deny.txt"
        path.write_text("# comment\n\nAcme\n  Widget  \n")
        self.assertEqual(check_content.load_denylist(path), ["acme", "widget"])

    def test_missing_denylist_file_means_no_terms(self) -> None:
        missing = Path(tempfile.mkdtemp(prefix="content-test-")) / "absent.txt"
        self.assertEqual(check_content.load_denylist(missing), [])


if __name__ == "__main__":
    unittest.main()
