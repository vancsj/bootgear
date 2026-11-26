from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

from rules_test_support import (
    LEDGER,
    RULES_FILE,
    TempLedgerCase,
    _default_text,
    _git,
    clikit,
)


class RuleFileGuardTests(TempLedgerCase):
    """A rule path that is a symlink or not a regular file is never read, written or staged."""

    def setUp(self) -> None:
        super().setUp()
        self.outside = self.temp / "outside"
        self.outside.mkdir()
        self.outside_content = "outside fixture content"

    def dangling(self, kind: str) -> Path:
        target = self.outside / f"{kind}-target.txt"
        self.rules_file(kind).symlink_to(target)
        return target

    def outside_link(self, kind: str) -> Path:
        target = self.outside / f"{kind}-existing.txt"
        target.write_text(self.outside_content + "\n", encoding="utf-8")
        self.rules_file(kind).symlink_to(target)
        return target

    def directory(self, kind: str) -> Path:
        self.rules_file(kind).mkdir()
        return self.rules_file(kind)

    SHAPES = ("dangling", "outside_link", "directory")

    def make(self, shape: str, kind: str = "shared") -> Path:
        return getattr(self, shape)(kind)

    def assert_clean(self, result: subprocess.CompletedProcess[str]) -> None:
        both = result.stdout + result.stderr
        self.assertNotIn("Traceback", both)
        self.assertNotIn(str(self.outside), both)
        self.assertNotIn(self.outside_content, both)

    def assert_outside_untouched(self, shape: str) -> None:
        names = sorted(p.name for p in self.outside.iterdir())
        expected = ["shared-existing.txt"] if shape == "outside_link" else []
        self.assertEqual(names, expected)
        if shape == "outside_link":
            self.assertEqual((self.outside / "shared-existing.txt").read_text(encoding="utf-8"),
                             self.outside_content + "\n")

    def run_mode(self, mode: str, *args: str) -> subprocess.CompletedProcess[str]:
        env = {**self.env(), clikit.ENV_MODE: mode}
        return subprocess.run([sys.executable, str(LEDGER), *args], cwd=self.temp, env=env,
                              capture_output=True, text=True, check=False)

    def test_rules_does_not_read_through_the_path(self) -> None:
        for shape in self.SHAPES:
            for mode in ("prose", "json"):
                with self.subTest(shape=shape, mode=mode):
                    self.setUp()
                    self.make(shape)
                    result = self.run_mode(mode, "rules", "--only", "shared")
                    self.assertNotEqual(result.returncode, 0, result.stdout)
                    self.assert_clean(result)
                    self.assertNotIn("next:", result.stdout)
                    self.assert_outside_untouched(shape)

    def test_rules_names_the_problem_on_the_rules_line(self) -> None:
        self.outside_link("shared")
        out = self.run_ledger("rules", "--only", "shared").stdout
        self.assertRegex(out, rf"(?m)^RULES\s+shared\s+{re.escape(str(self.rules_file('shared')))} "
                              r"is a symbolic link")

    def test_init_refuses_and_writes_nothing(self) -> None:
        for shape in self.SHAPES:
            for mode in ("prose", "json"):
                with self.subTest(shape=shape, mode=mode):
                    self.setUp()
                    self.make(shape)
                    result = self.run_mode(mode, "rules", "--init")
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assert_clean(result)
                    self.assert_outside_untouched(shape)
                    self.assertFalse(self.rules_file("local").exists(),
                                     "a refusal must write no ledger at all")
                    if mode == "json":
                        error = json.loads(result.stderr)["error"]
                        self.assertEqual(error["command"], "rules")
                        self.assertIn("not a regular file", error["message"])
                    else:
                        lines = result.stderr.splitlines()
                        self.assertTrue(lines[0].startswith("example: "), result.stderr)
                        self.assertIn("not a regular file", "\n".join(lines[1:]))
                        self.assertIn(" is a ", lines[-1])

    def test_doctor_warns_with_the_problem(self) -> None:
        for shape, problem in (("dangling", "is a symbolic link"),
                               ("outside_link", "is a symbolic link"),
                               ("directory", "is a directory")):
            with self.subTest(shape=shape):
                self.setUp()
                self.make(shape)
                result = self.run_ledger("doctor", "--json")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assert_clean(result)
                data = json.loads(result.stdout)
                warnings = [w for w in data["warnings"] if w.startswith("shared rules")]
                self.assertEqual(len(warnings), 1, data["warnings"])
                self.assertIn(problem, warnings[0])
                self.assertNotIn("present", warnings[0])
                prose = self.run_ledger("doctor", "--prose")
                self.assert_clean(prose)
                self.assertRegex(prose.stdout, rf"(?m)^warn\s+shared rules\s+.*{problem}")

    def test_save_does_not_stage_the_path(self) -> None:
        for shape in self.SHAPES:
            with self.subTest(shape=shape):
                self.setUp()
                self.assertEqual(self.new_entry("shared").returncode, 0)
                self.make(shape)
                result = self.run_ledger("save", "--only", "shared", "--no-push")
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                self.assert_clean(result)
                self.assertRegex(result.stdout, rf"(?m)^WARN\s+.*{re.escape(RULES_FILE)}.*not staged")
                tracked = _git(self.shared, "ls-tree", "-r", "--name-only", "HEAD").split()
                self.assertIn("tech/seeded.md", tracked)
                self.assertNotIn(RULES_FILE, tracked)
                self.assert_outside_untouched(shape)

    def test_save_with_no_entries_still_warns(self) -> None:
        self.outside_link("local")
        result = self.run_ledger("save", "--only", "local", "--no-push")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_clean(result)
        self.assertRegex(result.stdout, r"(?m)^WARN\s+.*not staged")
        self.assertIn("holds no entries yet", result.stdout)

    def stage_rules(self, root: Path) -> None:
        _git(root, "add", "-f", "--", RULES_FILE)

    def bare_remote(self, root: Path) -> Path:
        remote = self.temp / f"{root.name}-remote.git"
        subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True)
        _git(root, "remote", "add", "origin", str(remote))
        return remote

    def refused_line(self, result: subprocess.CompletedProcess[str], mode: str) -> str:
        lines = (json.loads(result.stdout)["lines"] if mode == "json"
                 else result.stdout.splitlines())
        refused = [line for line in lines if line.startswith("REFUSED  save ")]
        self.assertEqual(len(refused), 1, result.stdout + result.stderr)
        return refused[0]

    def has_head(self, root: Path) -> bool:
        return subprocess.run(["git", "-C", str(root), "rev-parse", "-q", "--verify", "HEAD"],
                              capture_output=True, text=True, check=False).returncode == 0

    def test_save_refuses_a_staged_symlink(self) -> None:
        for mode in ("prose", "json"):
            with self.subTest(mode=mode):
                self.setUp()
                self.assertEqual(self.new_entry("shared").returncode, 0)
                self.outside_link("shared")
                self.stage_rules(self.shared)
                remote = self.bare_remote(self.shared)
                result = self.run_mode(mode, "save", "--only", "shared")
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assert_clean(result)
                line = self.refused_line(result, mode)
                self.assertIn(str(self.shared), line)
                self.assertIn(f"{RULES_FILE} is a symbolic link and is staged", line)
                self.assertFalse(self.has_head(self.shared), "nothing may be committed")
                self.assertEqual(_git(remote, "for-each-ref").strip(), "", "nothing may be pushed")

    def test_save_refusal_in_one_ledger_still_saves_the_other(self) -> None:
        for mode in ("prose", "json"):
            with self.subTest(mode=mode):
                self.setUp()
                self.assertEqual(self.new_entry("shared").returncode, 0)
                self.outside_link("shared")
                self.stage_rules(self.shared)
                remote = self.bare_remote(self.shared)
                self.assertEqual(self.new_entry("local", "tech/local-one",
                                                "Is the local entry saved?").returncode, 0)
                result = self.run_mode(mode, "save", "--no-push")
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                self.assert_clean(result)
                self.assertIn(str(self.shared), self.refused_line(result, mode))
                self.assertFalse(self.has_head(self.shared), "the refused ledger may not commit")
                self.assertEqual(_git(remote, "for-each-ref").strip(), "")
                self.assertIn("tech/local-one.md",
                              _git(self.local, "ls-tree", "-r", "--name-only", "HEAD").split())

    def test_save_leaves_a_staged_symlink_alone_in_an_empty_ledger(self) -> None:
        self.outside_link("local")
        self.stage_rules(self.local)
        before = _git(self.local, "ls-files", "-s", "--", RULES_FILE)
        result = self.run_ledger("save", "--only", "local")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_clean(result)
        self.assertIn("holds no entries yet", result.stdout)
        self.assertEqual(_git(self.local, "ls-files", "-s", "--", RULES_FILE), before)
        head = subprocess.run(["git", "-C", str(self.local), "rev-parse", "-q", "--verify", "HEAD"],
                              capture_output=True, text=True, check=False)
        self.assertNotEqual(head.returncode, 0)

    def advised_command(self, line: str) -> list[str]:
        commands = re.findall(r"`([^`]+)`", line)
        self.assertEqual(len(commands), 1, line)
        return shlex.split(commands[0])

    def test_the_advised_unstage_command_clears_the_refusal(self) -> None:
        for history in ("unborn", "committed"):
            with self.subTest(history=history):
                self.setUp()
                self.assertEqual(self.new_entry("shared").returncode, 0)
                if history == "committed":
                    self.ok("rules", "--init", "--only", "shared")
                    self.ok("save", "--only", "shared", "--no-push")
                    self.rules_file("shared").unlink()
                    self.assertEqual(self.new_entry("shared", "tech/second",
                                                    "Is the grass green?").returncode, 0)
                self.outside_link("shared")
                self.stage_rules(self.shared)
                refused = self.run_ledger("save", "--only", "shared", "--no-push")
                self.assertEqual(refused.returncode, 1, refused.stdout + refused.stderr)
                command = self.advised_command(self.refused_line(refused, "prose"))
                ran = subprocess.run(command, capture_output=True, text=True, check=False)
                self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
                self.assertEqual(_git(self.shared, "diff", "--cached", "--name-only",
                                      "--", RULES_FILE).strip(), "")
                result = self.run_ledger("save", "--only", "shared", "--no-push")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assert_clean(result)
                self.assertRegex(result.stdout, r"(?m)^WARN\s+.*not staged")
                self.assertNotIn("REFUSED", result.stdout)
                tracked = _git(self.shared, "ls-tree", "-r", "--name-only", "HEAD").split()
                self.assertIn("tech/seeded.md", tracked)
                if history == "committed":
                    self.assertIn("tech/second.md", tracked)
                    mode = _git(self.shared, "ls-tree", "HEAD", "--", RULES_FILE).split()[0]
                    self.assertEqual(mode, "100644")
                else:
                    self.assertNotIn(RULES_FILE, tracked)

    def test_save_does_not_commit_a_tracked_file_repointed_to_a_symlink(self) -> None:
        self.assertEqual(self.new_entry("shared").returncode, 0)
        self.ok("rules", "--init", "--only", "shared")
        self.ok("save", "--only", "shared", "--no-push")
        self.rules_file("shared").unlink()
        self.outside_link("shared")
        self.assertEqual(self.new_entry("shared", "tech/second", "Is the grass green?").returncode, 0)
        result = self.run_ledger("save", "--only", "shared", "--no-push")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assert_clean(result)
        self.assertRegex(result.stdout, r"(?m)^WARN\s+.*not staged")
        self.assertIn("tech/second.md", _git(self.shared, "ls-tree", "-r", "--name-only", "HEAD"))
        self.assertEqual(_git(self.shared, "show", f"HEAD:{RULES_FILE}"), _default_text("shared"))
        mode = _git(self.shared, "ls-tree", "HEAD", "--", RULES_FILE).split()[0]
        self.assertEqual(mode, "100644")

    def test_new_warns_with_the_problem(self) -> None:
        self.outside_link("shared")
        result = self.new_entry("shared")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_clean(result)
        self.assertIn(f"WARN     shared ledger {RULES_FILE} is a symbolic link", result.stdout)
        self.assertNotIn("has no WHAT-BELONGS.txt", result.stdout)
