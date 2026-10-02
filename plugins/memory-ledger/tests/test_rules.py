"""The per-ledger rule file: `rules`, `save`, `doctor`, `resolve`, `new` and the shipped defaults.

Every run is a subprocess against temp ledger roots; nothing here touches a real ledger.
"""
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
SCRIPTS = PLUGIN / "scripts"
LEDGER = SCRIPTS / "ledger.py"
WRAPPER = SCRIPTS / "ledger"
RULES_DIR = PLUGIN / "rules"
RULES_FILE = "WHAT-BELONGS.txt"
CACHE_FILE = ".ledger-cache.json"

SHARED_HEADINGS = (
    "What belongs in the shared ledger",
    "An entry",
    "Belongs here",
    "A check must run on any teammate's machine",
    "Does not belong here",
    "Dating and change",
    "This team's own rules",
)
LOCAL_HEADINGS = (
    "What belongs in the local ledger",
    "Belongs here",
    "Moving entries",
    "Keep out",
    "This team's own rules",
)

sys.path.insert(0, str(SCRIPTS))
import ledger as ledger_cli
from ledgerlib import clikit


def _git_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                            text=True, check=True)
    return result.stdout


def _default_text(kind: str) -> str:
    return (RULES_DIR / f"{kind}.txt").read_text(encoding="utf-8")


class TempLedgerCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = Path(tempfile.mkdtemp(prefix="memory-ledger-rules-"))
        self.home = self.temp / "home"
        self.home.mkdir()
        self.shared = self.temp / "shared"
        self.local = self.temp / "local"
        _git_repo(self.shared)
        _git_repo(self.local)

    def env(self) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items()
               if k not in (clikit.ENV_MODE, clikit.ENV_PROG, clikit.ENV_CALLER_CWD)}
        env.update(HOME=str(self.home), LEDGER_ROOT=str(self.shared),
                   LEDGER_LOCAL_ROOT=str(self.local),
                   GIT_AUTHOR_NAME="Test", GIT_AUTHOR_EMAIL="test@example.invalid",
                   GIT_COMMITTER_NAME="Test", GIT_COMMITTER_EMAIL="test@example.invalid")
        return env

    def run_ledger(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(LEDGER), *args], cwd=self.temp,
                              env=self.env(), capture_output=True, text=True, check=False)

    def ok(self, *args: str) -> str:
        result = self.run_ledger(*args)
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        return result.stdout

    def new_entry(self, kind: str, slug: str = "tech/seeded",
                  question: str = "Which colour is the sky?") -> subprocess.CompletedProcess[str]:
        return self.run_ledger(
            "new", slug, f"--{kind}", "--q", question, "--claim", "The sky is blue.",
            "--because", "Look up.", "--evidence", "true", "--as", "author-a")

    def rules_file(self, kind: str) -> Path:
        return (self.shared if kind == "shared" else self.local) / RULES_FILE


class RulesCommandTests(TempLedgerCase):
    # -- rules ---------------------------------------------------------------

    def test_rules_prints_the_seeded_text_of_both_ledgers(self) -> None:
        self.ok("rules", "--init")
        out = self.ok("rules")
        for kind in ("shared", "local"):
            self.assertRegex(out, rf"(?m)^RULES\s+{kind}\s+{re.escape(str(self.rules_file(kind)))}\s*$")
            self.assertIn(_default_text(kind).strip(), out)

    def test_rules_prints_an_edited_file_verbatim(self) -> None:
        self.rules_file("shared").write_text("Only these things belong here.\n", encoding="utf-8")
        out = self.ok("rules", "--only", "shared")
        self.assertIn("Only these things belong here.", out)

    def test_rules_names_the_missing_file_and_the_command_that_seeds_it(self) -> None:
        out = self.ok("rules")
        for kind in ("shared", "local"):
            self.assertIn(
                f"{self.rules_file(kind)} missing — run: ledger.py rules --init --only {kind}", out)
        self.assertFalse(self.rules_file("shared").exists())
        self.assertFalse(self.rules_file("local").exists())

    def test_rules_ends_with_the_init_command_when_a_file_is_missing(self) -> None:
        out = self.ok("rules")
        self.assertEqual(out.splitlines()[-1], "next: ledger.py rules --init")
        self.assertEqual(out.count("next:"), 1)

    def test_rules_has_no_next_line_when_every_file_exists(self) -> None:
        self.ok("rules", "--init")
        self.assertNotIn("next:", self.ok("rules"))

    def test_rules_only_narrows_the_listing(self) -> None:
        out = self.ok("rules", "--only", "local")
        self.assertIn("local", out)
        self.assertNotIn(str(self.shared), out)

    # -- rules --init ----------------------------------------------------------

    def test_init_writes_the_default_into_an_empty_ledger(self) -> None:
        out = self.ok("rules", "--init")
        for kind in ("shared", "local"):
            self.assertEqual(self.rules_file(kind).read_text(encoding="utf-8"), _default_text(kind))
            self.assertRegex(out, rf"(?m)^RULES\s+{kind}\s+seeded {re.escape(str(self.rules_file(kind)))}\s*$")
        self.assertEqual(out.splitlines()[-1], "next: ledger.py save")

    def test_init_twice_keeps_the_file_and_changes_no_bytes(self) -> None:
        self.ok("rules", "--init")
        before = {kind: self.rules_file(kind).read_bytes() for kind in ("shared", "local")}
        out = self.ok("rules", "--init")
        for kind in ("shared", "local"):
            self.assertRegex(out, rf"(?m)^RULES\s+{kind}\s+kept {re.escape(str(self.rules_file(kind)))}\s*$")
            self.assertNotIn("seeded", out)
            self.assertEqual(self.rules_file(kind).read_bytes(), before[kind])

    def test_init_never_overwrites_a_team_edited_file(self) -> None:
        self.rules_file("shared").write_text("Team wording.\n", encoding="utf-8")
        self.ok("rules", "--init", "--only", "shared")
        self.assertEqual(self.rules_file("shared").read_text(encoding="utf-8"), "Team wording.\n")

    def test_init_only_limits_which_ledger_is_seeded(self) -> None:
        out = self.ok("rules", "--init", "--only", "local")
        self.assertTrue(self.rules_file("local").is_file())
        self.assertFalse(self.rules_file("shared").exists())
        self.assertNotIn(str(self.shared), out)

        out = self.ok("rules", "--init", "--only", "shared")
        self.assertTrue(self.rules_file("shared").is_file())
        self.assertRegex(out, r"(?m)^RULES\s+shared\s+seeded ")
        self.assertNotRegex(out, r"(?m)^RULES\s+local\b")

    def test_rules_example_parses(self) -> None:
        self.assertIn("rules", ledger_cli.EXAMPLES)
        args, extra = ledger_cli.build_parser().parse_known_args(
            shlex.split(ledger_cli.EXAMPLES["rules"]))
        self.assertEqual(extra, [])
        self.assertEqual(args.cmd, "rules")

    def test_rules_accepts_init_and_only_flags(self) -> None:
        args, extra = ledger_cli.build_parser().parse_known_args(
            ["rules", "--init", "--only", "local"])
        self.assertEqual(extra, [])
        self.assertTrue(args.init)
        self.assertEqual(args.only, "local")

    # -- save ------------------------------------------------------------------

    def test_save_commits_the_rule_file_with_the_entries(self) -> None:
        self.assertEqual(self.new_entry("shared").returncode, 0)
        self.ok("rules", "--init", "--only", "shared")
        self.assertTrue((self.shared / CACHE_FILE).is_file(), "the cache must exist for this check")
        self.ok("save", "--only", "shared")
        tracked = _git(self.shared, "ls-tree", "-r", "--name-only", "HEAD").split()
        self.assertIn(RULES_FILE, tracked)
        self.assertIn("tech/seeded.md", tracked)
        self.assertNotIn(CACHE_FILE, tracked)

    def test_save_commits_an_edited_rule_file(self) -> None:
        self.assertEqual(self.new_entry("shared").returncode, 0)
        self.ok("rules", "--init", "--only", "shared")
        self.ok("save", "--only", "shared")
        self.rules_file("shared").write_text("Edited rules.\n", encoding="utf-8")
        self.ok("save", "--only", "shared")
        self.assertEqual(_git(self.shared, "show", f"HEAD:{RULES_FILE}"), "Edited rules.\n")
        self.assertEqual(_git(self.shared, "status", "--porcelain", "--", RULES_FILE).strip(), "")

    def test_save_commits_a_rule_file_in_a_ledger_without_entries(self) -> None:
        self.ok("rules", "--init", "--only", "local")
        out = self.ok("save", "--only", "local")
        self.assertNotIn("holds no entries yet", out)
        self.assertIn(RULES_FILE, _git(self.local, "ls-tree", "-r", "--name-only", "HEAD").split())

    def test_save_still_reports_an_empty_ledger_without_a_rule_file(self) -> None:
        out = self.ok("save", "--only", "local")
        self.assertIn("holds no entries yet", out)

    # -- doctor ----------------------------------------------------------------

    def rules_warnings(self, kind: str) -> list[str]:
        data = json.loads(self.ok("doctor", "--json"))
        return [w for w in data["warnings"] if w.startswith(f"{kind} rules")]

    def test_doctor_warns_about_a_missing_rule_file_and_stays_configured(self) -> None:
        data = json.loads(self.ok("doctor", "--json"))
        self.assertEqual(data["status"], "configured")
        for kind in ("shared", "local"):
            warnings = self.rules_warnings(kind)
            self.assertEqual(len(warnings), 1, data["warnings"])
            self.assertIn(f"{self.rules_file(kind)} missing", warnings[0])
            self.assertIn(f"ledger.py rules --init --only {kind}", warnings[0])
        self.assertFalse(any(f.startswith(("shared rules", "local rules")) for f in data["failures"]))

    def test_doctor_drops_the_rules_warning_once_the_file_is_seeded(self) -> None:
        self.ok("rules", "--init")
        for kind in ("shared", "local"):
            self.assertEqual(self.rules_warnings(kind), [])

    def test_doctor_prose_shows_a_rules_row_per_ledger(self) -> None:
        out = self.ok("doctor", "--prose")
        self.assertRegex(out, r"(?m)^warn\s+shared rules\s+.*missing")
        self.assertRegex(out, r"(?m)^warn\s+local rules\s+.*missing")
        self.ok("rules", "--init")
        out = self.ok("doctor", "--prose")
        self.assertRegex(out, rf"(?m)^ok\s+shared rules\s+{re.escape(str(self.rules_file('shared')))} present")
        self.assertRegex(out, rf"(?m)^ok\s+local rules\s+{re.escape(str(self.rules_file('local')))} present")

    # -- resolve ---------------------------------------------------------------

    def test_resolve_mint_note_names_the_rules_command_with_two_ledgers(self) -> None:
        out = self.ok("resolve", "Which colour is the sky?")
        self.assertIn("MINT", out)
        self.assertIn("Each ledger's rules: ledger.py rules.", out)

    def test_resolve_mint_note_is_silent_about_rules_with_one_ledger(self) -> None:
        out = self.ok("resolve", "Which colour is the sky?", "--only", "local")
        self.assertIn("MINT", out)
        self.assertNotIn("ledger.py rules", out)

    # -- new -------------------------------------------------------------------

    def test_new_warns_when_the_ledger_has_no_rule_file(self) -> None:
        for kind in ("shared", "local"):
            result = self.new_entry(kind, f"tech/{kind}-entry", f"Is {kind} warned about rules?")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(
                f"WARN     {kind} ledger has no WHAT-BELONGS.txt — run: ledger.py rules --init --only {kind}",
                result.stdout)

    def test_new_does_not_warn_once_the_rule_file_exists(self) -> None:
        self.ok("rules", "--init")
        result = self.new_entry("local")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("WHAT-BELONGS.txt", result.stdout)

    # -- shipped defaults ------------------------------------------------------

    def test_default_files_exist(self) -> None:
        for kind in ("shared", "local"):
            self.assertTrue((RULES_DIR / f"{kind}.txt").is_file(), kind)

    def test_defaults_carry_their_required_headings(self) -> None:
        for kind, headings in (("shared", SHARED_HEADINGS), ("local", LOCAL_HEADINGS)):
            lines = {line.strip() for line in _default_text(kind).splitlines()}
            for heading in headings:
                self.assertIn(heading, lines, f"{kind}.txt lacks the heading {heading!r}")

    def test_defaults_are_project_free(self) -> None:
        forbidden = {
            "a home path": re.compile(r"/Users/|~/"),
            "a script file name": re.compile(r"\.(sh|py)\b"),
            "a URL": re.compile(r"http"),
            "a hash-like token": re.compile(r"[0-9a-f]{7,}"),
        }
        for kind in ("shared", "local"):
            text = _default_text(kind)
            self.assertTrue(text.strip(), f"{kind}.txt is empty")
            for label, pattern in forbidden.items():
                match = pattern.search(text)
                self.assertIsNone(match, f"{kind}.txt contains {label}: {match and match.group(0)!r}")

    def test_default_team_section_is_a_short_placeholder(self) -> None:
        for kind in ("shared", "local"):
            lines = _default_text(kind).splitlines()
            start = next(i for i, line in enumerate(lines) if line.strip() == "This team's own rules")
            body = [line for line in lines[start + 1:] if line.strip()]
            self.assertLessEqual(len(body), 3, f"{kind}.txt team section should hold only a placeholder")

    def test_defaults_say_why_they_are_txt(self) -> None:
        for kind in ("shared", "local"):
            head = "\n".join(_default_text(kind).splitlines()[:8])
            self.assertIn(RULES_FILE, head, kind)
            self.assertIn(".md", head, kind)


class WrapperAndJsonTests(TempLedgerCase):
    """`rules` run through the Codex wrapper, which exports BOOTGEAR_PROG, and in JSON mode."""

    def run_wrapper(self, *args: str, mode: str = "prose") -> subprocess.CompletedProcess[str]:
        env = {**self.env(), clikit.ENV_MODE: mode}
        return subprocess.run([str(WRAPPER), *args], cwd=self.temp, env=env,
                              capture_output=True, text=True, check=False)

    def test_wrapper_init_next_names_the_wrapper(self) -> None:
        result = self.run_wrapper("rules", "--init")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[-1], f"next: {WRAPPER} save")

    def test_wrapper_init_json_next_names_the_wrapper(self) -> None:
        result = self.run_wrapper("rules", "--init", mode="json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["next"], f"{WRAPPER} save")

    def test_wrapper_missing_file_next_names_the_wrapper(self) -> None:
        result = self.run_wrapper("rules")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[-1], f"next: {WRAPPER} rules --init")

    def test_only_keeps_the_scope_on_the_next_lines(self) -> None:
        for kind in ("shared", "local"):
            for mode in ("prose", "json"):
                with self.subTest(kind=kind, mode=mode):
                    self.setUp()
                    for runner, prog in ((self.run_direct, "ledger.py"), (self.run_wrapper, str(WRAPPER))):
                        self.setUp()
                        read = runner("rules", "--only", kind, mode=mode)
                        self.assertEqual(read.returncode, 0, read.stderr)
                        self.assertEqual(self.next_of(read, mode),
                                         f"{prog} rules --init --only {kind}")
                        init = runner("rules", "--init", "--only", kind, mode=mode)
                        self.assertEqual(init.returncode, 0, init.stderr)
                        self.assertEqual(self.next_of(init, mode), f"{prog} save --only {kind}")

    def test_both_ledgers_keep_the_unscoped_next_lines(self) -> None:
        for mode in ("prose", "json"):
            with self.subTest(mode=mode):
                self.setUp()
                read = self.run_wrapper("rules", mode=mode)
                self.assertEqual(self.next_of(read, mode), f"{WRAPPER} rules --init")
                init = self.run_wrapper("rules", "--init", mode=mode)
                self.assertEqual(self.next_of(init, mode), f"{WRAPPER} save")

    def run_direct(self, *args: str, mode: str = "prose") -> subprocess.CompletedProcess[str]:
        env = {**self.env(), clikit.ENV_MODE: mode}
        return subprocess.run([sys.executable, str(LEDGER), *args], cwd=self.temp, env=env,
                              capture_output=True, text=True, check=False)

    @staticmethod
    def next_of(result: subprocess.CompletedProcess[str], mode: str) -> str:
        if mode == "json":
            return json.loads(result.stdout)["next"]
        last = result.stdout.splitlines()[-1]
        assert last.startswith("next: "), result.stdout
        return last[len("next: "):]

    def test_json_missing_file_carries_a_next_key(self) -> None:
        result = self.run_wrapper("rules", mode="json")
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data["next"], f"{WRAPPER} rules --init")
        self.assertFalse(any(line.startswith("next:") for line in data["lines"]))


class RuleFileGuardTests(TempLedgerCase):
    """A rule path that is a symlink or not a regular file is never read, written or staged."""

    def setUp(self) -> None:
        super().setUp()
        self.outside = self.temp / "outside"
        self.outside.mkdir()
        self.secret = "OUTSIDE-SECRET-CONTENT"

    def dangling(self, kind: str) -> Path:
        target = self.outside / f"{kind}-target.txt"
        self.rules_file(kind).symlink_to(target)
        return target

    def outside_link(self, kind: str) -> Path:
        target = self.outside / f"{kind}-existing.txt"
        target.write_text(self.secret + "\n", encoding="utf-8")
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
        self.assertNotIn(self.secret, both)

    def assert_outside_untouched(self, shape: str) -> None:
        names = sorted(p.name for p in self.outside.iterdir())
        expected = ["shared-existing.txt"] if shape == "outside_link" else []
        self.assertEqual(names, expected)
        if shape == "outside_link":
            self.assertEqual((self.outside / "shared-existing.txt").read_text(encoding="utf-8"),
                             self.secret + "\n")

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
                        self.assertIn("not a regular file", result.stderr.splitlines()[0])

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
                              capture_output=True, text=True).returncode == 0

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
                              capture_output=True, text=True)
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


if __name__ == "__main__":
    unittest.main()
