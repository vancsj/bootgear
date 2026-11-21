from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
import unittest

from rules_test_support import (
    CACHE_FILE,
    DIRECT_COMMAND,
    GEAR,
    GEAR_COMMAND,
    LEDGER,
    LOCAL_HEADINGS,
    RULES_DIR,
    RULES_FILE,
    SHARED_HEADINGS,
    TempLedgerCase,
    _default_text,
    _git,
    clikit,
    ledger_cli,
)


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
                f"{self.rules_file(kind)} missing — run: {DIRECT_COMMAND} rules --init --only {kind}", out)
        self.assertFalse(self.rules_file("shared").exists())
        self.assertFalse(self.rules_file("local").exists())

    def test_rules_ends_with_the_init_command_when_a_file_is_missing(self) -> None:
        out = self.ok("rules")
        self.assertEqual(out.splitlines()[-1], f"next: {DIRECT_COMMAND} rules --init")
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
        self.assertEqual(out.splitlines()[-1], f"next: {DIRECT_COMMAND} save")

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
            self.assertIn(f"{DIRECT_COMMAND} rules --init --only {kind}", warnings[0])
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
        self.assertIn(f"Each ledger's rules: {DIRECT_COMMAND} rules.", out)

    def test_resolve_mint_note_is_silent_about_rules_with_one_ledger(self) -> None:
        out = self.ok("resolve", "Which colour is the sky?", "--only", "local")
        self.assertIn("MINT", out)
        self.assertNotIn(f"{DIRECT_COMMAND} rules", out)

    # -- new -------------------------------------------------------------------

    def test_new_warns_when_the_ledger_has_no_rule_file(self) -> None:
        for kind in ("shared", "local"):
            result = self.new_entry(kind, f"tech/{kind}-entry", f"Is {kind} warned about rules?")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(
                f"WARN     {kind} ledger has no WHAT-BELONGS.txt — run: {DIRECT_COMMAND} rules --init --only {kind}",
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
    """`rules` run through Gear and keep `next` runnable in prose and JSON."""

    def run_wrapper(self, *args: str, mode: str = "prose") -> subprocess.CompletedProcess[str]:
        env = {**self.env(), clikit.ENV_MODE: mode}
        return subprocess.run([str(GEAR), "--host", "codex", "memory-ledger", "ledger", *args],
                              cwd=self.temp, env=env,
                              capture_output=True, text=True, check=False)

    def test_wrapper_init_next_names_the_wrapper(self) -> None:
        result = self.run_wrapper("rules", "--init")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[-1], f"next: {GEAR_COMMAND} save")

    def test_wrapper_init_json_next_names_the_wrapper(self) -> None:
        result = self.run_wrapper("rules", "--init", mode="json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["next"], f"{GEAR_COMMAND} save")

    def test_wrapper_missing_file_next_names_the_wrapper(self) -> None:
        result = self.run_wrapper("rules")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines()[-1], f"next: {GEAR_COMMAND} rules --init")

    def test_only_keeps_the_scope_on_the_next_lines(self) -> None:
        for kind in ("shared", "local"):
            for mode in ("prose", "json"):
                with self.subTest(kind=kind, mode=mode):
                    self.setUp()
                    for runner, prog in ((self.run_direct, DIRECT_COMMAND),
                                         (self.run_wrapper, GEAR_COMMAND)):
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
                self.assertEqual(self.next_of(read, mode), f"{GEAR_COMMAND} rules --init")
                init = self.run_wrapper("rules", "--init", mode=mode)
                self.assertEqual(self.next_of(init, mode), f"{GEAR_COMMAND} save")

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
        self.assertEqual(data["next"], f"{GEAR_COMMAND} rules --init")
        self.assertFalse(any(line.startswith("next:") for line in data["lines"]))


if __name__ == "__main__":
    unittest.main()
