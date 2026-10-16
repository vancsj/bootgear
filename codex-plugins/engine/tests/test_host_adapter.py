import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
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

    def _context(self, source: str) -> str:
        result = subprocess.run(
            [
                sys.executable,
                str(PLUGIN_DIR / "hooks" / "adapter.py"),
                "--handler",
                "session_recall",
                "--matcher-pattern",
                "^(startup|resume|compact)$",
            ],
            input=json.dumps({
                "session_id": "fixture-codex",
                "cwd": str(self.cwd),
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

    def test_active_ledger_adds_nudge_on_compact_with_goal_and_principles(self):
        self.ledger.write_text("## settlement\ngoal: the goal text\n")
        context = self._context("compact")
        self.assertIn("This session just compacted", context)
        self.assertIn(IDENTITY, context)
        self.assertIn("the goal text", context)
        self.assertIn("[project]\n- project rule", context)

    def test_no_ledger_emits_identity_only(self):
        for source in ("startup", "resume", "compact"):
            with self.subTest(source=source):
                self.assertEqual(self._context(source), IDENTITY)

    def test_closed_ledger_emits_identity_only(self):
        self.ledger.write_text("## settlement\ngoal: the goal text\n\n## closed\nsucceeded\n")
        for source in ("startup", "resume", "compact"):
            with self.subTest(source=source):
                self.assertEqual(self._context(source), IDENTITY)

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

    def test_unreadable_ledger_emits_identity_only(self):
        self.ledger.write_bytes(b"\xff\xfe\x00bad-utf8")
        self.assertEqual(self._context("compact"), IDENTITY)
