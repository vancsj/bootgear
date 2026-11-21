import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from host_adapter_test_support import PLUGIN_DIR, REPO_ROOT


class SessionRecallAdapterTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="host-adapter-session-recall-")
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name) / "home"
        self.cwd = Path(tmp.name) / "project"
        self.session_dir = self.home / ".bootgear" / "session"
        self.session_dir.mkdir(parents=True)
        (self.cwd / ".bootgear" / "config").mkdir(parents=True)
        (self.cwd / ".bootgear" / "config" / "principles.md").write_text("- project rule\n")
        self.ledger = self.session_dir / "fixture-claude.md"

    def _invoke(self, source: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                sys.executable,
                str(PLUGIN_DIR / "hooks" / "adapter.py"),
                "--handler",
                "session_recall",
                "--matcher-pattern",
                "startup|clear|compact",
            ],
            input=json.dumps({
                "session_id": "fixture-claude",
                "cwd": str(cwd or self.cwd),
                "hook_event_name": "SessionStart",
                "source": source,
            }),
            capture_output=True,
            text=True,
            env={**os.environ, "HOME": str(self.home), "CLAUDE_PLUGIN_ROOT": str(PLUGIN_DIR), "BOOTGEAR_HOST": "claude"},
            check=False,
        )

    def _run(self, source: str = "compact") -> str:
        result = self._invoke(source)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def _context(self, source: str = "compact") -> str:
        return json.loads(self._run(source))["hookSpecificOutput"]["additionalContext"]

    ACTIVE_LEDGER = "## settlement\ngoal: the goal text\n"
    GOAL_AND_PRINCIPLES = (
        "This run's /goal:\nthe goal text\n\n"
        "Merged principles (user/project/task):\n[project]\n- project rule"
    )
    STANDARDS_BLOCK = (
        "Standards (read each file in full before you judge or write):\n"
        "[review-standard] .bootgear/config/review-standard.md: R001 [must], R002 [should]\n"
        "[test-standard] .bootgear/config/test-standard.md: R001 [must]"
    )

    def _write_standards(self):
        config = self.cwd / ".bootgear" / "config"
        (config / "review-standard.md").write_text(
            "    ```text\n    Literal code example.\n    ```\n\n"
            "# review-standard\n\nseverities: [must, should]\ncutoff: must\n\n"
            "## R001 [must]\nFirst review rule.\n\n## R002 [should]\nSecond review rule.\n"
            "\n```md\n## R003 [must]\nExample rule.\n```\n"
            "\n<!--\n## R004 [must]\nCommented rule.\n-->\n"
        )
        (config / "test-standard.md").write_text(
            "# test-standard\n\nseverities: [must, should]\ncutoff: must\n\n"
            "## R001 [must]\nFirst test rule.\n"
        )

    def test_active_ledger_adds_recall_context(self):
        self.ledger.write_text(self.ACTIVE_LEDGER)
        context = self._context()
        self.assertIn("This session just compacted", context)
        self.assertTrue(context.endswith(self.GOAL_AND_PRINCIPLES), context)

    def test_startup_and_clear_sources_are_accepted(self):
        self.ledger.write_text(self.ACTIVE_LEDGER)
        for source in ("startup", "clear"):
            with self.subTest(source=source):
                self.assertEqual(self._context(source), self.GOAL_AND_PRINCIPLES)

    def test_resume_source_is_refused(self):
        result = self._invoke("resume")
        self.assertEqual(result.stdout, "")
        self.assertIn("engine hook adapter: ", result.stderr)

    def test_standard_files_add_the_standards_block_after_the_principles(self):
        self.ledger.write_text(self.ACTIVE_LEDGER)
        self._write_standards()
        expected = f"{self.GOAL_AND_PRINCIPLES}\n\n{self.STANDARDS_BLOCK}"
        for source in ("startup", "clear"):
            with self.subTest(source=source):
                self.assertEqual(self._context(source), expected)
        self.assertTrue(self._context("compact").endswith(expected))

    def test_no_standard_file_omits_the_standards_block(self):
        self.ledger.write_text(self.ACTIVE_LEDGER)
        for source in ("startup", "clear", "compact"):
            with self.subTest(source=source):
                self.assertNotIn("Standards", self._context(source))

    def test_partial_standard_files_list_only_the_files_with_rules(self):
        self.ledger.write_text(self.ACTIVE_LEDGER)
        config = self.cwd / ".bootgear" / "config"
        cases = {
            "only review": ("test-standard.md", None, self.STANDARDS_BLOCK.rsplit("\n", 1)[0]),
            "only test": (
                "review-standard.md",
                None,
                self.STANDARDS_BLOCK.split("\n", 1)[0] + "\n" + self.STANDARDS_BLOCK.rsplit("\n", 1)[1],
            ),
            "empty file": ("test-standard.md", "", self.STANDARDS_BLOCK.rsplit("\n", 1)[0]),
            "unreadable file": ("test-standard.md", b"\xff\xfe", self.STANDARDS_BLOCK.rsplit("\n", 1)[0]),
            "no rule heading": (
                "test-standard.md",
                "# test-standard\n",
                self.STANDARDS_BLOCK.rsplit("\n", 1)[0]
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
                self.assertEqual(self._context("startup"), f"{self.GOAL_AND_PRINCIPLES}\n\n{block}")

    def test_active_ledger_adds_the_nudge_on_compact_only(self):
        self.ledger.write_text(self.ACTIVE_LEDGER)
        for source in ("startup", "clear"):
            with self.subTest(source=source):
                context = self._context(source)
                self.assertNotIn("This session just compacted", context)
                self.assertIn("the goal text", context)
        self.assertIn("This session just compacted", self._context("compact"))

    def test_repo_hook_output_fits_the_limit(self):
        self.ledger.write_text(self.ACTIVE_LEDGER)
        result = self._invoke("startup", cwd=REPO_ROOT)
        self.assertEqual(result.returncode, 0, result.stderr)
        context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
        self.assertIn("Standards (read each file in full before you judge or write):", context)
        self.assertLess(len(context), 10000)

    def test_no_ledger_prints_nothing(self):
        self._write_standards()
        for source in ("startup", "clear", "compact"):
            with self.subTest(source=source):
                self.assertEqual(self._run(source), "")

    def test_closed_ledger_prints_nothing(self):
        self._write_standards()
        self.ledger.write_text(f"{self.ACTIVE_LEDGER}\n## closed\nsucceeded\n")
        self.assertEqual(self._run(), "")

    def test_closed_text_that_is_not_a_heading_keeps_the_ledger_active(self):
        self.ledger.write_text("## settlement\ngoal: the goal text\n\n## notes\nnot ## closed yet\n## closed-loop notes\n")
        context = self._context()
        self.assertIn("This session just compacted", context)
        self.assertIn("the goal text", context)

    def test_unreadable_ledger_prints_nothing(self):
        self.ledger.write_bytes(b"\xff\xfe\x00bad-utf8")
        self.assertEqual(self._run(), "")
