import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = PLUGIN_DIR.parents[1]
RUNNER = PLUGIN_DIR / "tests" / "run_host_adapter_fixture.py"


class CodexHostAdapterFixtureTest(unittest.TestCase):
    def test_codex_fixture_corpus_is_collected_and_runs(self):
        with tempfile.TemporaryDirectory(prefix="codex-host-adapter-test-home-") as home:
            result = subprocess.run(
                [sys.executable, str(RUNNER), "--host", "codex"],
                capture_output=True,
                text=True,
                env={**os.environ, "HOME": home},
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("host-adapter fixtures passed: codex", result.stdout)


IDENTITY = (
    "Codex session_id: fixture-codex. Use this exact value as the engine "
    "run-id; do not generate a UUID or other replacement."
)
IDENTITY_AND_PRINCIPLES = (
    f"{IDENTITY}\n\nMerged principles (user/project/task):\n[project]\n- project rule"
)
STANDARDS_BLOCK = (
    "Standards (read each file in full before you judge or write):\n"
    "[review-standard] .bootgear/config/review-standard.md: R001 [must], R002 [should]\n"
    "[test-standard] .bootgear/config/test-standard.md: R001 [must]"
)


class CodexSessionRecallAdapterTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="codex-host-adapter-session-recall-")
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name) / "home"
        self.cwd = Path(tmp.name) / "project"
        self.session_dir = self.home / ".bootgear" / "session"
        self.session_dir.mkdir(parents=True)
        (self.cwd / ".bootgear" / "config").mkdir(parents=True)
        (self.cwd / ".bootgear" / "config" / "principles.md").write_text("- project rule\n")
        self.ledger = self.session_dir / "fixture-codex.md"

    def _context(self, source: str, cwd: Path | None = None) -> str:
        result = subprocess.run(
            [
                sys.executable,
                str(PLUGIN_DIR / "hooks" / "adapter.py"),
                "--handler",
                "session_recall",
                "--matcher-pattern",
                "^(startup|resume|clear|compact)$",
            ],
            input=json.dumps({
                "session_id": "fixture-codex",
                "cwd": str(cwd or self.cwd),
                "hook_event_name": "SessionStart",
                "source": source,
            }),
            capture_output=True,
            text=True,
            env={**os.environ, "HOME": str(self.home), "PLUGIN_ROOT": str(PLUGIN_DIR)},
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]

    def _write_standards(self):
        config = self.cwd / ".bootgear" / "config"
        (config / "review-standard.md").write_text(
            "# review-standard\n\nseverities: [must, should]\ncutoff: must\n\n"
            "## R001 [must]\nFirst review rule.\n\n## R002 [should]\nSecond review rule.\n"
        )
        (config / "test-standard.md").write_text(
            "# test-standard\n\nseverities: [must, should]\ncutoff: must\n\n"
            "## R001 [must]\nFirst test rule.\n"
        )

    def test_clear_source_is_accepted(self):
        self.assertEqual(self._context("clear"), IDENTITY_AND_PRINCIPLES)

    def test_standard_files_add_the_standards_block_after_the_principles(self):
        self._write_standards()
        for source in ("startup", "resume", "clear", "compact"):
            with self.subTest(source=source):
                self.assertEqual(
                    self._context(source),
                    f"{IDENTITY_AND_PRINCIPLES}\n\n{STANDARDS_BLOCK}",
                )

    def test_no_standard_file_omits_the_standards_block(self):
        for source in ("startup", "resume", "clear", "compact"):
            with self.subTest(source=source):
                self.assertNotIn("Standards", self._context(source))

    def test_partial_standard_files_list_only_the_files_with_rules(self):
        self._write_standards()
        config = self.cwd / ".bootgear" / "config"
        cases = {
            "only review": ("test-standard.md", None, STANDARDS_BLOCK.rsplit("\n", 1)[0]),
            "only test": (
                "review-standard.md",
                None,
                STANDARDS_BLOCK.split("\n", 1)[0] + "\n" + STANDARDS_BLOCK.rsplit("\n", 1)[1],
            ),
            "empty file": ("test-standard.md", "", STANDARDS_BLOCK.rsplit("\n", 1)[0]),
            "unreadable file": ("test-standard.md", b"\xff\xfe", STANDARDS_BLOCK.rsplit("\n", 1)[0]),
            "no rule heading": (
                "test-standard.md",
                "# test-standard\n",
                STANDARDS_BLOCK.rsplit("\n", 1)[0]
                + "\n[test-standard] .bootgear/config/test-standard.md",
            ),
        }
        for name, (file, text, block) in cases.items():
            with self.subTest(case=name):
                self._write_standards()
                if text is None:
                    (config / file).unlink()
                elif isinstance(text, bytes):
                    (config / file).write_bytes(text)
                else:
                    (config / file).write_text(text)
                self.assertEqual(self._context("startup"), f"{IDENTITY_AND_PRINCIPLES}\n\n{block}")

    def test_repo_hook_output_fits_the_limit(self):
        context = self._context("startup", cwd=REPO_ROOT)
        self.assertIn("Standards (read each file in full before you judge or write):", context)
        self.assertLess(len(context), 8000)

    def test_active_ledger_adds_nudge_on_compact_with_goal_and_principles(self):
        self.ledger.write_text("## settlement\ngoal: the goal text\n")
        context = self._context("compact")
        self.assertIn("This session just compacted", context)
        self.assertIn(IDENTITY, context)
        self.assertIn("the goal text", context)
        self.assertIn("[project]\n- project rule", context)

    def test_no_ledger_emits_identity_and_principles(self):
        for source in ("startup", "resume", "compact"):
            with self.subTest(source=source):
                self.assertEqual(self._context(source), IDENTITY_AND_PRINCIPLES)

    def test_no_ledger_and_no_principles_emits_identity_only(self):
        (self.cwd / ".bootgear" / "config" / "principles.md").unlink()
        for source in ("startup", "resume", "compact"):
            with self.subTest(source=source):
                self.assertEqual(self._context(source), IDENTITY)

    def test_closed_ledger_emits_identity_and_principles(self):
        self.ledger.write_text("## settlement\ngoal: the goal text\n\n## closed\nsucceeded\n")
        for source in ("startup", "resume", "compact"):
            with self.subTest(source=source):
                self.assertEqual(self._context(source), IDENTITY_AND_PRINCIPLES)

    def test_active_ledger_on_startup_and_resume_adds_goal_without_the_nudge(self):
        self.ledger.write_text("## settlement\ngoal: the goal text\n")
        for source in ("startup", "resume"):
            with self.subTest(source=source):
                context = self._context(source)
                self.assertIn(IDENTITY, context)
                self.assertIn("the goal text", context)
                self.assertNotIn("This session just compacted", context)

    def test_closed_text_that_is_not_a_heading_keeps_the_ledger_active(self):
        self.ledger.write_text("## settlement\ngoal: the goal text\n\n## notes\nnot ## closed yet\n## closed-loop notes\n")
        context = self._context("compact")
        self.assertIn("This session just compacted", context)
        self.assertIn("the goal text", context)

    def test_unreadable_ledger_emits_identity_and_principles(self):
        self.ledger.write_bytes(b"\xff\xfe\x00bad-utf8")
        self.assertEqual(self._context("compact"), IDENTITY_AND_PRINCIPLES)
